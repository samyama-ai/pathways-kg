"""STRING protein-protein interaction loader for pathways-kg.

Loads high-confidence human protein interactions from STRING v12.0,
mapping STRING (Ensembl) protein IDs to UniProt accessions.

Input files (decompressed by download_data.py):
  - 9606.protein.links.v12.0.txt   (space-separated: protein1 protein2 combined_score)
  - 9606.protein.info.v12.0.txt    (tab-separated: ENSP, preferred_name, size, annotation)
  - 9606.protein.aliases.v12.0.txt (tab-separated: ENSP, alias, source)
"""

from __future__ import annotations

import os

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
# Internal helpers
# ---------------------------------------------------------------------------

def _strip_species(ensp_id: str) -> str:
    """Strip the '9606.' species prefix from a STRING protein ID."""
    if ensp_id.startswith("9606."):
        return ensp_id[5:]
    return ensp_id


def _build_uniprot_map(aliases_path: str) -> dict[str, str]:
    """Build ENSP -> UniProt accession mapping from the aliases file.

    Only considers rows where the source column is 'UniProt_AC' or
    'Ensembl_UniProt_AC'.  When multiple UniProt IDs exist for one
    ENSP, the first encountered wins (stable ordering from STRING).
    """
    ensp_to_uniprot: dict[str, str] = {}
    valid_sources = {"UniProt_AC", "Ensembl_UniProt_AC"}

    with open(aliases_path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("string_protein_id"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            ensp_raw, alias, source = parts[0], parts[1], parts[2]
            if source not in valid_sources:
                continue
            ensp = _strip_species(ensp_raw)
            if ensp not in ensp_to_uniprot:
                ensp_to_uniprot[ensp] = alias

    return ensp_to_uniprot


def _build_info_map(info_path: str) -> dict[str, str]:
    """Build ENSP -> preferred_name mapping from the info file."""
    ensp_to_name: dict[str, str] = {}

    with open(info_path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("string_protein_id"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            ensp = _strip_species(parts[0])
            preferred_name = parts[1]
            ensp_to_name[ensp] = preferred_name

    return ensp_to_name


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_string(
    client,
    data_dir: str,
    registry: Registry,
    threshold: int = 700,
    tenant: str = "default",
) -> dict:
    """Load STRING protein-protein interactions into the knowledge graph.

    Args:
        client: SamyamaClient instance.
        data_dir: Directory containing the decompressed STRING data files.
        registry: Shared dedup registry (proteins, interacts_with sets).
        threshold: Minimum combined_score to include (default 700 = high conf).
        tenant: Graph tenant name.

    Returns:
        Dict with loading statistics.
    """
    aliases_path = os.path.join(data_dir, "9606.protein.aliases.v12.0.txt")
    info_path = os.path.join(data_dir, "9606.protein.info.v12.0.txt")
    links_path = os.path.join(data_dir, "9606.protein.links.v12.0.txt")

    # ------------------------------------------------------------------
    # Step 1: Build ID mappings
    # ------------------------------------------------------------------
    print("[STRING] Building ENSP → UniProt mapping from aliases ...")
    ensp_to_uniprot = _build_uniprot_map(aliases_path)
    print(f"  Mapped {len(ensp_to_uniprot)} ENSP IDs to UniProt accessions")

    print("[STRING] Building ENSP → preferred_name mapping from info ...")
    ensp_to_name = _build_info_map(info_path)
    print(f"  Loaded names for {len(ensp_to_name)} ENSP IDs")

    # ------------------------------------------------------------------
    # Step 2: Create index on Protein(uniprot_id) for fast MATCH
    # ------------------------------------------------------------------
    create_index(client, "Protein", "uniprot_id", tenant)

    # ------------------------------------------------------------------
    # Step 3: Read interactions, filter by threshold, map IDs
    # ------------------------------------------------------------------
    print(f"[STRING] Reading interactions (threshold >= {threshold}) ...")

    # Collect interactions as (uid1, uid2, score) after mapping + dedup
    interactions: list[tuple[str, str, int]] = []
    # Track proteins that need node creation
    new_proteins: dict[str, str] = {}  # uniprot_id -> preferred_name

    # Count lines for progress (excluding header)
    total_lines = 0
    with open(links_path, "r", encoding="utf-8") as fh:
        for _ in fh:
            total_lines += 1
    total_lines = max(total_lines - 1, 0)  # subtract header

    progress = ProgressReporter("STRING interactions", total_lines)
    skipped_below_threshold = 0
    skipped_no_uniprot = 0

    with open(links_path, "r", encoding="utf-8") as fh:
        header = fh.readline()  # skip header
        for line in fh:
            progress.tick()
            parts = line.strip().split()
            if len(parts) < 3:
                continue

            ensp1_raw, ensp2_raw, score_str = parts[0], parts[1], parts[2]
            score = int(score_str)

            # Filter by confidence threshold
            if score < threshold:
                skipped_below_threshold += 1
                continue

            # Map to UniProt
            ensp1 = _strip_species(ensp1_raw)
            ensp2 = _strip_species(ensp2_raw)

            uid1 = ensp_to_uniprot.get(ensp1)
            uid2 = ensp_to_uniprot.get(ensp2)

            if uid1 is None or uid2 is None:
                skipped_no_uniprot += 1
                continue

            # Canonical ordering: alphabetically lower UniProt ID first
            # This ensures undirected edges are stored once
            if uid1 > uid2:
                uid1, uid2 = uid2, uid1

            # Dedup via registry
            pair_key = f"{uid1}|{uid2}"
            if pair_key in registry.interacts_with:
                continue
            registry.interacts_with.add(pair_key)

            interactions.append((uid1, uid2, score))

            # Track proteins that need node creation
            for uid, ensp in [(uid1, ensp1), (uid2, ensp2)]:
                if uid not in registry.proteins:
                    name = ensp_to_name.get(ensp, uid)
                    new_proteins[uid] = name

    print(f"  {len(interactions)} high-confidence interactions after dedup")
    print(f"  Skipped: {skipped_below_threshold} below threshold, "
          f"{skipped_no_uniprot} unmapped to UniProt")
    print(progress.summary())

    # ------------------------------------------------------------------
    # Step 4: Create new Protein nodes (batch)
    # ------------------------------------------------------------------
    node_progress = ProgressReporter("STRING protein nodes", len(new_proteins))
    nodes_created = 0
    node_batch: list[tuple[str, dict]] = []
    node_batch_size = 100

    for uid, name in new_proteins.items():
        if uid in registry.proteins:
            node_progress.tick()
            continue

        registry.proteins.add(uid)
        node_batch.append(("Protein", {"uniprot_id": uid, "name": name}))
        node_progress.tick()

        if len(node_batch) >= node_batch_size:
            nodes_created += batch_create_nodes(client, node_batch, tenant)
            node_batch.clear()

    # Flush remaining
    if node_batch:
        nodes_created += batch_create_nodes(client, node_batch, tenant)
        node_batch.clear()

    print(f"  Created {nodes_created} new Protein nodes from STRING")
    print(node_progress.summary())

    # ------------------------------------------------------------------
    # Step 5: Create INTERACTS_WITH edges (batch, chunked)
    # ------------------------------------------------------------------
    edge_progress = ProgressReporter("STRING edges", len(interactions))
    edges: list[tuple[str, str, str, str, str, str, str, dict]] = []

    for uid1, uid2, score in interactions:
        edges.append((
            "Protein", "uniprot_id", uid1,
            "Protein", "uniprot_id", uid2,
            "INTERACTS_WITH",
            {"combined_score": score},
        ))
        edge_progress.tick()

    edges_created = batch_create_edges_fast(
        client, edges, tenant, chunk_size=50
    )

    print(f"  Created {edges_created} INTERACTS_WITH edges")
    print(edge_progress.summary())

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    stats = {
        "source": "STRING",
        "threshold": threshold,
        "ensp_mapped": len(ensp_to_uniprot),
        "interactions_loaded": len(interactions),
        "proteins_created": nodes_created,
        "edges_created": edges_created,
        "skipped_below_threshold": skipped_below_threshold,
        "skipped_no_uniprot": skipped_no_uniprot,
    }
    print(f"[STRING] Done. {stats}")
    return stats
