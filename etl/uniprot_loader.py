"""UniProt loader for pathways-kg.

Enriches existing Protein nodes with metadata (gene_name, sequence_length,
function) and creates Gene, Disease, and Drug nodes with their relationships.

Input format (tab-separated with header):
    Entry  Gene Names  Protein names  Organism  Length  Involvement in disease
    Function [CC]  Cross-reference (DrugBank)  Cross-reference (GeneID)

Usage:
    from etl.uniprot_loader import load_uniprot
    counts = load_uniprot(client, "data", registry, tenant="default")
"""

from __future__ import annotations

import re
from pathlib import Path

from etl.helpers import (
    _escape,
    _q,
    _prop_str,
    batch_create_nodes,
    batch_create_edges_fast,
    create_index,
    Registry,
    ProgressReporter,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TSV_FILENAME = "uniprot_human_reviewed.tsv"
TSV_SUBDIR = "uniprot"

NODE_BATCH_SIZE = 100
EDGE_BATCH_SIZE = 50

# Column indices (0-based)
COL_ENTRY = 0
COL_GENE_NAMES = 1
COL_PROTEIN_NAMES = 2
COL_ORGANISM = 3
COL_LENGTH = 4
COL_DISEASE = 5
COL_FUNCTION = 6
COL_DRUGBANK = 7
COL_GENEID = 8

# Regex for extracting disease name from UniProt disease annotation.
# Pattern: "DISEASE: Name (Abbreviation) [MIM:123456]"
# Also handles entries without abbreviation or MIM.
_DISEASE_RE = re.compile(
    r"DISEASE:\s*(.+?)\s*(?:\(.*?\))?\s*\[MIM:\d+\]"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_diseases(disease_text: str) -> list[str]:
    """Extract disease names from UniProt 'Involvement in disease' field.

    Returns deduplicated list of disease names.
    """
    if not disease_text or disease_text.strip() == "":
        return []
    names = []
    seen = set()
    for match in _DISEASE_RE.finditer(disease_text):
        name = match.group(1).strip()
        if name and name.lower() not in seen:
            names.append(name)
            seen.add(name.lower())
    return names


def _parse_drugbank_ids(drugbank_text: str) -> list[str]:
    """Extract DrugBank IDs from UniProt cross-reference field.

    Field format: "DB00997;DB01169" or "DB00997; DB01169"
    """
    if not drugbank_text or drugbank_text.strip() == "":
        return []
    ids = []
    for token in drugbank_text.split(";"):
        token = token.strip()
        if token:
            ids.append(token)
    return ids


def _parse_gene_ids(geneid_text: str) -> list[str]:
    """Extract NCBI GeneID values from cross-reference field.

    Field format: "7157" or "7157;7158"
    """
    if not geneid_text or geneid_text.strip() == "":
        return []
    ids = []
    for token in geneid_text.split(";"):
        token = token.strip()
        if token:
            ids.append(token)
    return ids


def _get_field(fields: list[str], index: int) -> str:
    """Safely get a field by index, returning empty string if out of range."""
    if index < len(fields):
        return fields[index].strip()
    return ""


def _parse_sequence_length(length_str: str) -> int | None:
    """Parse the Length field as an integer."""
    length_str = length_str.strip()
    if length_str.isdigit():
        return int(length_str)
    return None


def _clean_function_text(func_text: str) -> str:
    """Clean up the Function [CC] field for storage.

    Strips the 'FUNCTION: ' prefix and trims to a reasonable length.
    """
    if not func_text:
        return ""
    text = func_text.strip()
    if text.upper().startswith("FUNCTION: "):
        text = text[10:]
    # Truncate very long function descriptions (Cypher property limit)
    if len(text) > 2000:
        text = text[:2000] + "..."
    return text


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_uniprot(
    client,
    data_dir: str,
    registry: Registry,
    tenant: str = "default",
) -> dict:
    """Load UniProt data: enrich Protein nodes, create Gene/Disease/Drug nodes.

    For proteins already in the graph (from Reactome/STRING), enriches them
    with gene_name, sequence_length, and function via SET.  For proteins not
    yet in the graph, creates new Protein nodes.

    Also creates:
    - Gene nodes + ENCODES edges (Gene -> Protein)
    - Disease nodes + ASSOCIATED_WITH edges (Protein -> Disease)
    - Drug nodes + TARGETS edges (Drug -> Protein)

    Args:
        client: SamyamaClient instance.
        data_dir: Root data directory containing uniprot/ subdirectory.
        registry: Shared dedup registry.
        tenant: Graph tenant name.

    Returns:
        Dict with counts for every entity/edge type created or enriched.
    """
    tsv_path = Path(data_dir) / TSV_SUBDIR / TSV_FILENAME
    if not tsv_path.exists():
        raise FileNotFoundError(f"UniProt TSV not found: {tsv_path}")

    print(f"\n=== UniProt Loader ===")
    print(f"  Input: {tsv_path}")

    # ---- Step 1: Create indexes ----------------------------------------
    create_index(client, "Gene", "gene_id", tenant)
    create_index(client, "Disease", "name", tenant)
    create_index(client, "Drug", "drugbank_id", tenant)

    # ---- Step 2: Count lines for progress ------------------------------
    with open(tsv_path, "r", encoding="utf-8") as fh:
        total_lines = sum(1 for ln in fh) - 1  # minus header
    total_lines = max(total_lines, 0)

    progress = ProgressReporter("UniProt", total_lines)

    # ---- Step 3: Parse and load ----------------------------------------
    proteins_enriched = 0
    proteins_created = 0
    genes_created = 0
    diseases_created = 0
    drugs_created = 0
    encodes_created = 0
    associated_created = 0
    targets_created = 0

    gene_node_buffer: list[tuple[str, dict]] = []
    disease_node_buffer: list[tuple[str, dict]] = []
    drug_node_buffer: list[tuple[str, dict]] = []
    protein_node_buffer: list[tuple[str, dict]] = []

    edge_buffer: list[tuple[str, str, str, str, str, str, str, dict]] = []

    with open(tsv_path, "r", encoding="utf-8") as fh:
        header = fh.readline()  # skip header

        for line in fh:
            line = line.rstrip("\n\r")
            if not line:
                continue

            fields = line.split("\t")
            uniprot_id = _get_field(fields, COL_ENTRY)
            if not uniprot_id:
                progress.error()
                continue

            progress.tick()

            gene_names_raw = _get_field(fields, COL_GENE_NAMES)
            protein_name = _get_field(fields, COL_PROTEIN_NAMES)
            organism = _get_field(fields, COL_ORGANISM)
            length_str = _get_field(fields, COL_LENGTH)
            disease_text = _get_field(fields, COL_DISEASE)
            function_text = _get_field(fields, COL_FUNCTION)
            drugbank_text = _get_field(fields, COL_DRUGBANK)
            geneid_text = _get_field(fields, COL_GENEID)

            # Primary gene symbol: first token in space-separated list
            gene_symbols = gene_names_raw.split() if gene_names_raw else []
            primary_gene = gene_symbols[0] if gene_symbols else ""
            seq_length = _parse_sequence_length(length_str)
            func_clean = _clean_function_text(function_text)

            # ------ 3a/3b: Protein node (enrich or create) --------------
            if uniprot_id in registry.proteins:
                # Enrich existing protein with SET
                set_parts = []
                if primary_gene:
                    set_parts.append(f"p.gene_name = {_q(primary_gene)}")
                if seq_length is not None:
                    set_parts.append(f"p.sequence_length = {seq_length}")
                if func_clean:
                    set_parts.append(f"p.function = {_q(func_clean)}")
                if protein_name:
                    set_parts.append(f"p.protein_name = {_q(protein_name)}")

                if set_parts:
                    cypher = (
                        f"MATCH (p:Protein {{uniprot_id: {_q(uniprot_id)}}}) "
                        f"SET {', '.join(set_parts)}"
                    )
                    try:
                        client.query(cypher, tenant)
                        proteins_enriched += 1
                    except Exception:
                        progress.error()
            else:
                # Create new Protein node
                props = {
                    "uniprot_id": uniprot_id,
                    "gene_name": primary_gene or None,
                    "protein_name": protein_name or None,
                    "organism": organism or "Homo sapiens",
                    "source": "UniProt",
                }
                if seq_length is not None:
                    props["sequence_length"] = seq_length
                if func_clean:
                    props["function"] = func_clean
                protein_node_buffer.append(("Protein", props))
                registry.proteins.add(uniprot_id)
                proteins_created += 1

            # ------ 3c/3d/3e: Gene node + ENCODES edge ------------------
            gene_ids = _parse_gene_ids(geneid_text)
            primary_gene_id = gene_ids[0] if gene_ids else None

            if primary_gene_id and primary_gene:
                if primary_gene_id not in registry.genes:
                    gene_props = {
                        "gene_id": primary_gene_id,
                        "symbol": primary_gene,
                        "name": primary_gene,
                        "organism": "Homo sapiens",
                    }
                    gene_node_buffer.append(("Gene", gene_props))
                    registry.genes.add(primary_gene_id)
                    genes_created += 1

                encodes_key = f"{primary_gene_id}|{uniprot_id}"
                if encodes_key not in registry.encodes:
                    edge_buffer.append((
                        "Gene", "gene_id", primary_gene_id,
                        "Protein", "uniprot_id", uniprot_id,
                        "ENCODES", {},
                    ))
                    registry.encodes.add(encodes_key)
                    encodes_created += 1

            # ------ 3f/3g: Disease nodes + ASSOCIATED_WITH edges --------
            diseases = _parse_diseases(disease_text)
            for disease_name in diseases:
                disease_key = disease_name.lower()
                if disease_key not in registry.diseases:
                    disease_props = {
                        "name": disease_name,
                        "source": "UniProt",
                    }
                    disease_node_buffer.append(("Disease", disease_props))
                    registry.diseases.add(disease_key)
                    diseases_created += 1

                # ASSOCIATED_WITH edge (Protein -> Disease)
                assoc_key = f"{uniprot_id}|{disease_key}"
                edge_buffer.append((
                    "Protein", "uniprot_id", uniprot_id,
                    "Disease", "name", disease_name,
                    "ASSOCIATED_WITH", {},
                ))
                associated_created += 1

            # ------ 3h/3i/3j: Drug nodes + TARGETS edges ----------------
            drugbank_ids = _parse_drugbank_ids(drugbank_text)
            for db_id in drugbank_ids:
                if db_id not in registry.drugs:
                    drug_props = {
                        "drugbank_id": db_id,
                        "source": "DrugBank",
                    }
                    drug_node_buffer.append(("Drug", drug_props))
                    registry.drugs.add(db_id)
                    drugs_created += 1

                # TARGETS edge (Drug -> Protein)
                edge_buffer.append((
                    "Drug", "drugbank_id", db_id,
                    "Protein", "uniprot_id", uniprot_id,
                    "TARGETS", {},
                ))
                targets_created += 1

            # ------ Flush buffers periodically --------------------------
            total_nodes = (
                len(protein_node_buffer)
                + len(gene_node_buffer)
                + len(disease_node_buffer)
                + len(drug_node_buffer)
            )
            if total_nodes >= NODE_BATCH_SIZE or len(edge_buffer) >= EDGE_BATCH_SIZE:
                _flush_buffers(
                    client, tenant,
                    protein_node_buffer, gene_node_buffer,
                    disease_node_buffer, drug_node_buffer,
                    edge_buffer,
                )

    # ---- Step 4: Flush remaining buffers -------------------------------
    _flush_buffers(
        client, tenant,
        protein_node_buffer, gene_node_buffer,
        disease_node_buffer, drug_node_buffer,
        edge_buffer,
    )

    # ---- Step 5: Summary -----------------------------------------------
    summary = progress.summary()
    counts = {
        "proteins_enriched": proteins_enriched,
        "proteins_created": proteins_created,
        "genes_created": genes_created,
        "diseases_created": diseases_created,
        "drugs_created": drugs_created,
        "encodes_edges": encodes_created,
        "associated_with_edges": associated_created,
        "targets_edges": targets_created,
        "errors": summary["errors"],
        "elapsed_s": summary["elapsed_s"],
    }
    print(f"  UniProt complete:")
    print(f"    Proteins enriched: {proteins_enriched}")
    print(f"    Proteins created:  {proteins_created}")
    print(f"    Genes created:     {genes_created}")
    print(f"    Diseases created:  {diseases_created}")
    print(f"    Drugs created:     {drugs_created}")
    print(f"    ENCODES edges:     {encodes_created}")
    print(f"    ASSOCIATED_WITH:   {associated_created}")
    print(f"    TARGETS edges:     {targets_created}")
    print(f"    Elapsed:           {summary['elapsed_s']}s")
    return counts


# ---------------------------------------------------------------------------
# Buffer flush helper
# ---------------------------------------------------------------------------

def _flush_buffers(
    client,
    tenant: str,
    protein_buf: list,
    gene_buf: list,
    disease_buf: list,
    drug_buf: list,
    edge_buf: list,
) -> None:
    """Flush all node buffers first, then edge buffer.

    Nodes must be created before edges that reference them.
    Buffers are cleared in place after flushing.
    """
    # Flush nodes (order matters: proteins/genes/diseases/drugs before edges)
    for buf in (protein_buf, gene_buf, disease_buf, drug_buf):
        if buf:
            batch_create_nodes(client, buf, tenant)
            buf.clear()

    # Flush edges
    if edge_buf:
        batch_create_edges_fast(client, edge_buf, tenant, chunk_size=EDGE_BATCH_SIZE)
        edge_buf.clear()
