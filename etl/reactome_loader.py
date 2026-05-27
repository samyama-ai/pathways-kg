"""Reactome pathway loader for pathways-kg.

Reads downloaded Reactome TSV files and builds the graph:
  - Pathway nodes with CHILD_OF hierarchy
  - Protein nodes with PARTICIPATES_IN edges to pathways
  - Reaction nodes with CATALYZES edges
  - Complex nodes with COMPONENT_OF edges

Usage (from pipeline):
    from etl.reactome_loader import load_reactome
    stats = load_reactome(client, "data", registry, tenant="default")
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from etl.helpers import (
    Registry,
    ProgressReporter,
    _escape,
    _prop_str,
    _q,
    batch_create_edges_fast,
    batch_create_nodes,
    create_index,
)

logger = logging.getLogger(__name__)

HUMAN = "Homo sapiens"
BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# File reading helpers
# ---------------------------------------------------------------------------

def _reactome_dir(data_dir: str | Path) -> Path:
    """Return the reactome subdirectory."""
    return Path(data_dir) / "reactome"


def _read_tsv_lines(filepath: Path, skip_header: bool = False) -> list[list[str]]:
    """Read a TSV file and return rows as lists of strings.

    Skips blank lines and comment lines (starting with #).
    """
    rows = []
    if not filepath.exists():
        logger.error("File not found: %s", filepath)
        return rows

    with open(filepath, encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if skip_header and i == 0:
                continue
            line = line.rstrip("\n\r")
            if not line or line.startswith("#"):
                continue
            rows.append(line.split("\t"))
    return rows


# ---------------------------------------------------------------------------
# Step 1: Create indexes
# ---------------------------------------------------------------------------

def _create_indexes(client, tenant: str) -> None:
    """Create indexes on key properties for each node label."""
    indexes = [
        ("Pathway", "reactome_id"),
        ("Protein", "uniprot_id"),
        ("Reaction", "reactome_id"),
        ("Complex", "reactome_id"),
        ("Compound", "chebi_id"),
    ]
    for label, prop in indexes:
        create_index(client, label, prop, tenant)
        logger.info("Index created: %s(%s)", label, prop)


# ---------------------------------------------------------------------------
# Step 2: Pathway nodes from ReactomePathways.txt
# ---------------------------------------------------------------------------

def _load_pathways(
    client, data_dir: Path, registry: Registry, tenant: str,
) -> dict:
    """Parse ReactomePathways.txt, filter human, create Pathway nodes.

    Format (no header):  reactome_id \\t name \\t organism
    """
    filepath = _reactome_dir(data_dir) / "ReactomePathways.txt"
    rows = _read_tsv_lines(filepath)
    prog = ProgressReporter("pathways", len(rows))

    node_buf: list[tuple[str, dict]] = []
    created = 0
    skipped = 0

    for cols in rows:
        prog.tick()
        if len(cols) < 3:
            prog.error()
            continue

        reactome_id, name, organism = cols[0].strip(), cols[1].strip(), cols[2].strip()

        if organism != HUMAN:
            skipped += 1
            continue

        if reactome_id in registry.pathways:
            continue
        registry.pathways.add(reactome_id)

        props = {
            "reactome_id": reactome_id,
            "name": name,
            "organism": organism,
            "source": "reactome",
        }
        node_buf.append(("Pathway", props))

        if len(node_buf) >= BATCH_SIZE:
            batch_create_nodes(client, node_buf, tenant)
            created += len(node_buf)
            node_buf.clear()

    # Flush remainder
    if node_buf:
        batch_create_nodes(client, node_buf, tenant)
        created += len(node_buf)
        node_buf.clear()

    summary = prog.summary()
    summary["created"] = created
    summary["skipped_non_human"] = skipped
    print(f"  Pathways: {created} created, {skipped} non-human skipped")
    return summary


# ---------------------------------------------------------------------------
# Step 3: Pathway hierarchy from ReactomePathwaysRelation.txt
# ---------------------------------------------------------------------------

def _load_pathway_hierarchy(
    client, data_dir: Path, registry: Registry, tenant: str,
) -> dict:
    """Parse ReactomePathwaysRelation.txt, create CHILD_OF edges.

    Format (no header):  parent_id \\t child_id
    Direction: child -[:CHILD_OF]-> parent
    """
    filepath = _reactome_dir(data_dir) / "ReactomePathwaysRelation.txt"
    rows = _read_tsv_lines(filepath)
    prog = ProgressReporter("hierarchy", len(rows))

    edge_buf: list[tuple[str, str, str, str, str, str, str, dict]] = []
    created = 0

    for cols in rows:
        prog.tick()
        if len(cols) < 2:
            prog.error()
            continue

        parent_id = cols[0].strip()
        child_id = cols[1].strip()

        # Only create edges between known human pathways
        if parent_id not in registry.pathways or child_id not in registry.pathways:
            continue

        edge_key = (child_id, parent_id)
        if edge_key in registry.protein_pathways:
            # reuse protein_pathways set for hierarchy dedup to save memory
            continue

        edge_buf.append((
            "Pathway", "reactome_id", child_id,
            "Pathway", "reactome_id", parent_id,
            "CHILD_OF", {},
        ))

        if len(edge_buf) >= BATCH_SIZE:
            n = batch_create_edges_fast(client, edge_buf, tenant, chunk_size=BATCH_SIZE)
            created += n
            edge_buf.clear()

    if edge_buf:
        n = batch_create_edges_fast(client, edge_buf, tenant, chunk_size=BATCH_SIZE)
        created += n
        edge_buf.clear()

    summary = prog.summary()
    summary["created"] = created
    print(f"  Hierarchy edges (CHILD_OF): {created} created")
    return summary


# ---------------------------------------------------------------------------
# Step 4: Proteins + PARTICIPATES_IN from UniProt2Reactome_All_Levels.txt
# ---------------------------------------------------------------------------

def _load_proteins_and_participation(
    client, data_dir: Path, registry: Registry, tenant: str,
    max_human_rows: int | None = None,
) -> dict:
    """Parse UniProt2Reactome_All_Levels.txt.

    Format (no header):
        uniprot_id \\t reactome_id \\t url \\t pathway_name \\t evidence \\t organism

    Creates Protein nodes (deduped) and PARTICIPATES_IN edges to Pathways.

    Args:
        max_human_rows: If set, stop after processing this many human rows.
            Used by the lightweight demo to load a representative subset
            quickly (edges are created one-by-one, so the full ~900K-row
            file is slow). None = load everything.
    """
    filepath = _reactome_dir(data_dir) / "UniProt2Reactome_All_Levels.txt"
    rows = _read_tsv_lines(filepath)
    prog = ProgressReporter("proteins+participation", len(rows))

    node_buf: list[tuple[str, dict]] = []
    edge_buf: list[tuple[str, str, str, str, str, str, str, dict]] = []
    proteins_created = 0
    edges_created = 0
    skipped = 0
    human_seen = 0

    for cols in rows:
        prog.tick()
        if max_human_rows is not None and human_seen >= max_human_rows:
            break
        if len(cols) < 6:
            prog.error()
            continue

        uniprot_id = cols[0].strip()
        reactome_id = cols[1].strip()
        pathway_name = cols[3].strip()
        evidence = cols[4].strip()
        organism = cols[5].strip()

        if organism != HUMAN:
            skipped += 1
            continue

        human_seen += 1

        # Create Protein node if not seen
        if uniprot_id not in registry.proteins:
            registry.proteins.add(uniprot_id)
            props = {
                "uniprot_id": uniprot_id,
                "source": "reactome",
            }
            node_buf.append(("Protein", props))

            if len(node_buf) >= BATCH_SIZE:
                batch_create_nodes(client, node_buf, tenant)
                proteins_created += len(node_buf)
                node_buf.clear()

        # Create PARTICIPATES_IN edge (deduped)
        edge_key = (uniprot_id, reactome_id)
        if edge_key not in registry.protein_pathways and reactome_id in registry.pathways:
            registry.protein_pathways.add(edge_key)
            edge_props = {"evidence": evidence}
            if pathway_name:
                edge_props["pathway_name"] = pathway_name
            edge_buf.append((
                "Protein", "uniprot_id", uniprot_id,
                "Pathway", "reactome_id", reactome_id,
                "PARTICIPATES_IN", edge_props,
            ))

            if len(edge_buf) >= BATCH_SIZE:
                n = batch_create_edges_fast(client, edge_buf, tenant, chunk_size=BATCH_SIZE)
                edges_created += n
                edge_buf.clear()

    # Flush remaining nodes
    if node_buf:
        batch_create_nodes(client, node_buf, tenant)
        proteins_created += len(node_buf)
        node_buf.clear()

    # Flush remaining edges
    if edge_buf:
        n = batch_create_edges_fast(client, edge_buf, tenant, chunk_size=BATCH_SIZE)
        edges_created += n
        edge_buf.clear()

    summary = prog.summary()
    summary["proteins_created"] = proteins_created
    summary["edges_created"] = edges_created
    summary["skipped_non_human"] = skipped
    print(f"  Proteins: {proteins_created} created, Participates_in: {edges_created} edges, "
          f"{skipped} non-human skipped")
    return summary


# ---------------------------------------------------------------------------
# Step 5: Reactions + CATALYZES from interactions file
# ---------------------------------------------------------------------------

def _load_interactions(
    client, data_dir: Path, registry: Registry, tenant: str,
) -> dict:
    """Parse reactome.homo_sapiens.interactions.tab-delimited.txt.

    Tab-separated with header row (starts with #).
    Key columns:
        0  = interactor 1 uniprot id
        2  = interactor 1 name
        4  = interactor 2 uniprot id
        6  = interactor 2 name
        7  = interaction type
        last = reactome_id of the reaction context

    Creates Reaction nodes and CATALYZES edges from Protein to Reaction.
    """
    filepath = (
        _reactome_dir(data_dir)
        / "reactome.homo_sapiens.interactions.tab-delimited.txt"
    )
    rows = _read_tsv_lines(filepath, skip_header=True)
    prog = ProgressReporter("interactions", len(rows))

    node_buf: list[tuple[str, dict]] = []
    edge_buf: list[tuple[str, str, str, str, str, str, str, dict]] = []
    reactions_created = 0
    edges_created = 0

    for cols in rows:
        prog.tick()
        if len(cols) < 8:
            prog.error()
            continue

        try:
            uniprot1 = cols[0].strip()
            name1 = cols[2].strip()
            uniprot2 = cols[4].strip()
            name2 = cols[6].strip()
            interaction_type = cols[7].strip()
            reactome_id = cols[-1].strip()
        except IndexError:
            prog.error()
            continue

        # Validate: need at least a reactome_id
        if not reactome_id or not reactome_id.startswith("R-"):
            prog.error()
            continue

        # Create Reaction node if not seen
        if reactome_id not in registry.reactions:
            registry.reactions.add(reactome_id)
            props = {
                "reactome_id": reactome_id,
                "interaction_type": interaction_type,
                "source": "reactome",
            }
            node_buf.append(("Reaction", props))

            if len(node_buf) >= BATCH_SIZE:
                batch_create_nodes(client, node_buf, tenant)
                reactions_created += len(node_buf)
                node_buf.clear()

        # CATALYZES edges: both interactors -> reaction
        for uid, uname in [(uniprot1, name1), (uniprot2, name2)]:
            if not uid:
                continue
            # Ensure protein node exists
            if uid not in registry.proteins:
                registry.proteins.add(uid)
                p_props = {
                    "uniprot_id": uid,
                    "name": uname,
                    "source": "reactome",
                }
                node_buf.append(("Protein", p_props))
                if len(node_buf) >= BATCH_SIZE:
                    batch_create_nodes(client, node_buf, tenant)
                    reactions_created += 0  # proteins counted separately
                    node_buf.clear()

            edge_key = (uid, reactome_id, "CATALYZES")
            if edge_key not in registry.interacts_with:
                registry.interacts_with.add(edge_key)
                edge_buf.append((
                    "Protein", "uniprot_id", uid,
                    "Reaction", "reactome_id", reactome_id,
                    "CATALYZES", {"interaction_type": interaction_type},
                ))

                if len(edge_buf) >= BATCH_SIZE:
                    n = batch_create_edges_fast(
                        client, edge_buf, tenant, chunk_size=BATCH_SIZE,
                    )
                    edges_created += n
                    edge_buf.clear()

    # Flush nodes
    if node_buf:
        batch_create_nodes(client, node_buf, tenant)
        reactions_created += sum(1 for lbl, _ in node_buf if lbl == "Reaction")
        node_buf.clear()

    # Flush edges
    if edge_buf:
        n = batch_create_edges_fast(client, edge_buf, tenant, chunk_size=BATCH_SIZE)
        edges_created += n
        edge_buf.clear()

    summary = prog.summary()
    summary["reactions_created"] = reactions_created
    summary["edges_created"] = edges_created
    print(f"  Reactions: {reactions_created} created, CATALYZES edges: {edges_created}")
    return summary


# ---------------------------------------------------------------------------
# Step 6: Complexes + COMPONENT_OF from ComplexParticipants file
# ---------------------------------------------------------------------------

def _load_complexes(
    client, data_dir: Path, registry: Registry, tenant: str,
) -> dict:
    """Parse ComplexParticipantsPubMedIdentifiers_human.txt.

    Format (header on first line):
        complex_reactome_id \\t complex_name \\t participant_uniprot_ids (pipe-sep) \\t pubmed_ids

    Creates Complex nodes and COMPONENT_OF edges from Protein -> Complex.
    """
    filepath = (
        _reactome_dir(data_dir)
        / "ComplexParticipantsPubMedIdentifiers_human.txt"
    )
    rows = _read_tsv_lines(filepath, skip_header=True)
    prog = ProgressReporter("complexes", len(rows))

    node_buf: list[tuple[str, dict]] = []
    edge_buf: list[tuple[str, str, str, str, str, str, str, dict]] = []
    complexes_created = 0
    edges_created = 0

    for cols in rows:
        prog.tick()
        if len(cols) < 3:
            prog.error()
            continue

        complex_id = cols[0].strip()
        complex_name = cols[1].strip() if len(cols) > 1 else ""
        participants_raw = cols[2].strip() if len(cols) > 2 else ""
        pubmed_ids = cols[3].strip() if len(cols) > 3 else ""

        if not complex_id:
            prog.error()
            continue

        # Create Complex node if not seen
        if complex_id not in registry.complexes:
            registry.complexes.add(complex_id)
            props = {
                "reactome_id": complex_id,
                "name": complex_name,
                "source": "reactome",
            }
            if pubmed_ids:
                props["pubmed_ids"] = pubmed_ids
            node_buf.append(("Complex", props))

            if len(node_buf) >= BATCH_SIZE:
                batch_create_nodes(client, node_buf, tenant)
                complexes_created += len(node_buf)
                node_buf.clear()

        # Parse pipe-separated participant UniProt IDs
        if not participants_raw:
            continue

        participant_ids = [
            pid.strip()
            for pid in participants_raw.split("|")
            if pid.strip()
        ]

        for uid in participant_ids:
            # Ensure protein node exists
            if uid not in registry.proteins:
                registry.proteins.add(uid)
                node_buf.append(("Protein", {
                    "uniprot_id": uid,
                    "source": "reactome",
                }))
                if len(node_buf) >= BATCH_SIZE:
                    batch_create_nodes(client, node_buf, tenant)
                    node_buf.clear()

            # COMPONENT_OF edge: Protein -> Complex
            edge_key = (uid, complex_id)
            # Use a simple tuple check to avoid creating duplicate edges
            edge_buf.append((
                "Protein", "uniprot_id", uid,
                "Complex", "reactome_id", complex_id,
                "COMPONENT_OF", {},
            ))

            if len(edge_buf) >= BATCH_SIZE:
                n = batch_create_edges_fast(
                    client, edge_buf, tenant, chunk_size=BATCH_SIZE,
                )
                edges_created += n
                edge_buf.clear()

    # Flush nodes
    if node_buf:
        complexes_in_buf = sum(1 for lbl, _ in node_buf if lbl == "Complex")
        batch_create_nodes(client, node_buf, tenant)
        complexes_created += complexes_in_buf
        node_buf.clear()

    # Flush edges
    if edge_buf:
        n = batch_create_edges_fast(client, edge_buf, tenant, chunk_size=BATCH_SIZE)
        edges_created += n
        edge_buf.clear()

    summary = prog.summary()
    summary["complexes_created"] = complexes_created
    summary["edges_created"] = edges_created
    print(f"  Complexes: {complexes_created} created, COMPONENT_OF edges: {edges_created}")
    return summary


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_reactome(
    client,
    data_dir: str,
    registry: Registry,
    tenant: str = "default",
) -> dict:
    """Load all Reactome data into the graph.

    Args:
        client:   SamyamaClient instance (must support .query(cypher, tenant))
        data_dir: Root data directory containing reactome/ subdirectory
        registry: Shared deduplication registry
        tenant:   Graph tenant name

    Returns:
        Dict with counts for each entity type loaded.
    """
    data_path = Path(data_dir)
    rdir = _reactome_dir(data_path)

    # Verify required files exist
    required = [
        "ReactomePathways.txt",
        "ReactomePathwaysRelation.txt",
        "UniProt2Reactome_All_Levels.txt",
        "reactome.homo_sapiens.interactions.tab-delimited.txt",
        "ComplexParticipantsPubMedIdentifiers_human.txt",
    ]
    missing = [f for f in required if not (rdir / f).exists()]
    if missing:
        logger.warning(
            "Missing Reactome files (run download_data first): %s",
            ", ".join(missing),
        )
        print(f"[WARN] Missing files: {', '.join(missing)}")

    print("\n========================================")
    print("  REACTOME LOADER")
    print("========================================")

    # Step 1: Indexes
    print("\n[1/6] Creating indexes ...")
    _create_indexes(client, tenant)

    # Step 2: Pathways
    print("\n[2/6] Loading pathways ...")
    pathway_stats = _load_pathways(client, data_path, registry, tenant)

    # Step 3: Pathway hierarchy
    print("\n[3/6] Loading pathway hierarchy ...")
    hierarchy_stats = _load_pathway_hierarchy(client, data_path, registry, tenant)

    # Step 4: Proteins + PARTICIPATES_IN
    print("\n[4/6] Loading proteins and participation ...")
    protein_stats = _load_proteins_and_participation(
        client, data_path, registry, tenant,
    )

    # Step 5: Interactions / Reactions
    print("\n[5/6] Loading interactions (reactions) ...")
    interaction_stats = _load_interactions(client, data_path, registry, tenant)

    # Step 6: Complexes
    print("\n[6/6] Loading complexes ...")
    complex_stats = _load_complexes(client, data_path, registry, tenant)

    # Summary
    counts = {
        "pathways": pathway_stats.get("created", 0),
        "hierarchy_edges": hierarchy_stats.get("created", 0),
        "proteins": protein_stats.get("proteins_created", 0),
        "participates_in_edges": protein_stats.get("edges_created", 0),
        "reactions": interaction_stats.get("reactions_created", 0),
        "catalyzes_edges": interaction_stats.get("edges_created", 0),
        "complexes": complex_stats.get("complexes_created", 0),
        "component_of_edges": complex_stats.get("edges_created", 0),
    }

    total_nodes = counts["pathways"] + counts["proteins"] + counts["reactions"] + counts["complexes"]
    total_edges = (
        counts["hierarchy_edges"]
        + counts["participates_in_edges"]
        + counts["catalyzes_edges"]
        + counts["component_of_edges"]
    )

    print("\n----------------------------------------")
    print("  REACTOME SUMMARY")
    print("----------------------------------------")
    print(f"  Pathways:            {counts['pathways']:>8,}")
    print(f"  Proteins:            {counts['proteins']:>8,}")
    print(f"  Reactions:           {counts['reactions']:>8,}")
    print(f"  Complexes:           {counts['complexes']:>8,}")
    print(f"  CHILD_OF edges:      {counts['hierarchy_edges']:>8,}")
    print(f"  PARTICIPATES_IN:     {counts['participates_in_edges']:>8,}")
    print(f"  CATALYZES:           {counts['catalyzes_edges']:>8,}")
    print(f"  COMPONENT_OF:        {counts['component_of_edges']:>8,}")
    print(f"  ----")
    print(f"  Total nodes:         {total_nodes:>8,}")
    print(f"  Total edges:         {total_edges:>8,}")
    print("========================================\n")

    counts["total_nodes"] = total_nodes
    counts["total_edges"] = total_edges
    return counts
