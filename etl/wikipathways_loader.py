"""WikiPathways GMT loader for pathways-kg.

Loads pathway-gene associations from WikiPathways GMT (Gene Matrix Transposed)
files. Creates Pathway nodes and PARTICIPATES_IN edges linking existing Protein
nodes to pathways via gene-symbol lookup.

Input format (tab-separated GMT):
    pathway_name%source%wp_id%organism\tgene1\tgene2\t...

Usage:
    from etl.wikipathways_loader import load_wikipathways
    counts = load_wikipathways(client, "data", registry, tenant="default")
"""

from __future__ import annotations

import os
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

GMT_FILENAME = "wikipathways-Homo_sapiens.gmt"
GMT_SUBDIR = "wikipathways"

NODE_BATCH_SIZE = 100
EDGE_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_gene_to_uniprot(client, tenant: str) -> dict[str, str]:
    """Query the graph for all Protein nodes and build a gene_name -> uniprot_id map.

    Returns a dict mapping lowercase gene symbol to uniprot_id.
    Where multiple proteins share a gene name, the first one wins.
    """
    cypher = "MATCH (p:Protein) RETURN p.uniprot_id, p.gene_name"
    result = client.query(cypher, tenant)
    mapping: dict[str, str] = {}
    if result and hasattr(result, "rows"):
        for row in result.rows:
            uid = row[0] if len(row) > 0 else None
            gname = row[1] if len(row) > 1 else None
            if uid and gname:
                key = str(gname).strip().upper()
                if key and key not in mapping:
                    mapping[key] = str(uid).strip()
    return mapping


def _parse_gmt_line(line: str) -> tuple[str, str, str, list[str]] | None:
    """Parse a single GMT line.

    Returns (wp_id, pathway_name, organism, [gene_symbols]) or None on error.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    fields = line.split("\t")
    if len(fields) < 2:
        return None

    # First field: "Pathway Name%Source%WP_ID%Organism"
    meta = fields[0]
    meta_parts = meta.split("%")
    if len(meta_parts) < 3:
        return None

    pathway_name = meta_parts[0].strip()
    wp_id = meta_parts[2].strip()
    organism = meta_parts[3].strip() if len(meta_parts) > 3 else "Homo sapiens"

    # Remaining fields are gene symbols
    genes = [g.strip() for g in fields[1:] if g.strip()]

    return wp_id, pathway_name, organism, genes


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_wikipathways(
    client,
    data_dir: str,
    registry: Registry,
    tenant: str = "default",
) -> dict:
    """Load WikiPathways GMT data into the graph.

    Creates Pathway nodes (source=WikiPathways) and PARTICIPATES_IN edges
    from existing Protein nodes to those pathways. Deduplicates against
    pathways already loaded from Reactome by comparing lowercase names.

    Args:
        client: SamyamaClient instance.
        data_dir: Root data directory containing wikipathways/ subdirectory.
        registry: Shared dedup registry.
        tenant: Graph tenant name.

    Returns:
        Dict with counts: pathways_created, edges_created, genes_matched,
        genes_unmatched, pathways_skipped, errors.
    """
    gmt_path = Path(data_dir) / GMT_SUBDIR / GMT_FILENAME
    if not gmt_path.exists():
        raise FileNotFoundError(f"WikiPathways GMT file not found: {gmt_path}")

    print(f"\n=== WikiPathways Loader ===")
    print(f"  Input: {gmt_path}")

    # ---- Step 1: Create index ------------------------------------------
    create_index(client, "Pathway", "wp_id", tenant)

    # ---- Step 2: Build gene-symbol -> uniprot_id lookup ----------------
    print("  Building gene_name -> uniprot_id mapping from existing Proteins...")
    gene_to_uniprot = _build_gene_to_uniprot(client, tenant)
    print(f"  Found {len(gene_to_uniprot)} proteins with gene names")

    # ---- Step 3: Count lines for progress ------------------------------
    with open(gmt_path, "r", encoding="utf-8") as fh:
        total_lines = sum(1 for ln in fh if ln.strip() and not ln.startswith("#"))

    progress = ProgressReporter("WikiPathways", total_lines)

    # ---- Step 4: Parse and load ----------------------------------------
    pathways_created = 0
    edges_created = 0
    genes_matched = 0
    genes_unmatched = 0
    pathways_skipped = 0

    node_buffer: list[tuple[str, dict]] = []
    edge_buffer: list[tuple[str, str, str, str, str, str, str, dict]] = []

    with open(gmt_path, "r", encoding="utf-8") as fh:
        for line in fh:
            parsed = _parse_gmt_line(line)
            if parsed is None:
                continue

            wp_id, pathway_name, organism, gene_symbols = parsed
            progress.tick()

            # Dedup: skip if pathway name already loaded (e.g. from Reactome)
            name_lower = pathway_name.lower()
            if name_lower in registry.pathways:
                pathways_skipped += 1
                continue

            # Create Pathway node
            props = {
                "wp_id": wp_id,
                "name": pathway_name,
                "organism": organism,
                "source": "WikiPathways",
            }
            node_buffer.append(("Pathway", props))
            registry.pathways.add(name_lower)
            pathways_created += 1

            # Flush pathway nodes before creating edges referencing them
            if len(node_buffer) >= NODE_BATCH_SIZE:
                batch_create_nodes(client, node_buffer, tenant)
                node_buffer.clear()

            # Link existing proteins to this pathway
            for gene_sym in gene_symbols:
                gene_upper = gene_sym.upper()
                uniprot_id = gene_to_uniprot.get(gene_upper)
                if uniprot_id is None:
                    genes_unmatched += 1
                    continue

                edge_key = f"{uniprot_id}|{wp_id}"
                if edge_key in registry.protein_pathways:
                    continue

                edge_buffer.append((
                    "Protein", "uniprot_id", uniprot_id,
                    "Pathway", "wp_id", wp_id,
                    "PARTICIPATES_IN", {},
                ))
                registry.protein_pathways.add(edge_key)
                genes_matched += 1

            # Flush edges periodically
            if len(edge_buffer) >= EDGE_BATCH_SIZE:
                # Flush any pending nodes first so edge targets exist
                if node_buffer:
                    batch_create_nodes(client, node_buffer, tenant)
                    node_buffer.clear()
                created = batch_create_edges_fast(
                    client, edge_buffer, tenant, chunk_size=EDGE_BATCH_SIZE,
                )
                edges_created += created
                edge_buffer.clear()

    # ---- Step 5: Flush remaining buffers -------------------------------
    if node_buffer:
        batch_create_nodes(client, node_buffer, tenant)
        node_buffer.clear()

    if edge_buffer:
        created = batch_create_edges_fast(
            client, edge_buffer, tenant, chunk_size=EDGE_BATCH_SIZE,
        )
        edges_created += created
        edge_buffer.clear()

    # ---- Step 6: Summary -----------------------------------------------
    summary = progress.summary()
    counts = {
        "pathways_created": pathways_created,
        "pathways_skipped": pathways_skipped,
        "edges_created": edges_created,
        "genes_matched": genes_matched,
        "genes_unmatched": genes_unmatched,
        "errors": summary["errors"],
        "elapsed_s": summary["elapsed_s"],
    }
    print(f"  WikiPathways complete:")
    print(f"    Pathways created:  {pathways_created}")
    print(f"    Pathways skipped:  {pathways_skipped} (already in Reactome)")
    print(f"    Edges created:     {edges_created}")
    print(f"    Gene matches:      {genes_matched}")
    print(f"    Gene unmatched:    {genes_unmatched}")
    print(f"    Elapsed:           {summary['elapsed_s']}s")
    return counts
