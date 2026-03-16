"""Gene Ontology loader for pathways-kg.

Loads GO term hierarchy (IS_A, PART_OF, REGULATES) from go.json and
protein annotations (ANNOTATED_WITH) from goa_human.gaf.

Input files (decompressed by download_data.py):
  - go.json         (OBO Graph JSON with nodes and edges)
  - goa_human.gaf   (GAF 2.2 tab-separated annotations, '!' comment lines)
"""

from __future__ import annotations

import json
import os
import re

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

_GO_URI_PREFIX = "http://purl.obolibrary.org/obo/GO_"
_GO_ID_RE = re.compile(r"GO_(\d+)")

# Edge predicate mapping: OBO predicate -> (edge_type, extra_props)
_PRED_MAP: dict[str, tuple[str, dict]] = {
    "is_a": ("IS_A", {}),
    "http://purl.obolibrary.org/obo/BFO_0000050": ("PART_OF", {}),
    "BFO:0000050": ("PART_OF", {}),
    "http://purl.obolibrary.org/obo/RO_0002211": ("REGULATES", {}),
    "RO:0002211": ("REGULATES", {}),
    "http://purl.obolibrary.org/obo/RO_0002212": ("REGULATES", {"direction": "negative"}),
    "RO:0002212": ("REGULATES", {"direction": "negative"}),
    "http://purl.obolibrary.org/obo/RO_0002213": ("REGULATES", {"direction": "positive"}),
    "RO:0002213": ("REGULATES", {"direction": "positive"}),
}

_NAMESPACE_PRED = "http://www.geneontology.org/formats/oboInOwl#hasOBONamespace"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uri_to_go_id(uri: str) -> str | None:
    """Convert an OBO URI to a GO:NNNNNNN identifier.

    Example: 'http://purl.obolibrary.org/obo/GO_0008150' -> 'GO:0008150'
    """
    m = _GO_ID_RE.search(uri)
    if m:
        return f"GO:{m.group(1)}"
    return None


def _extract_namespace(meta: dict | None) -> str:
    """Extract the namespace from a GO node's meta.basicPropertyValues."""
    if not meta:
        return ""
    for bpv in meta.get("basicPropertyValues", []):
        if bpv.get("pred") == _NAMESPACE_PRED:
            return bpv.get("val", "")
    return ""


def _extract_definition(meta: dict | None) -> str:
    """Extract the definition text from a GO node's meta.definition."""
    if not meta:
        return ""
    defn = meta.get("definition")
    if defn and isinstance(defn, dict):
        return defn.get("val", "")
    return ""


# ---------------------------------------------------------------------------
# Phase parsers
# ---------------------------------------------------------------------------

def _parse_go_terms(graph_data: dict) -> list[dict]:
    """Parse GO term nodes from the OBO graph JSON.

    Returns a list of dicts with keys: go_id, name, namespace, definition.
    Only includes nodes whose URI starts with the GO prefix.
    """
    terms = []
    for node in graph_data.get("nodes", []):
        node_id = node.get("id", "")
        if not node_id.startswith(_GO_URI_PREFIX):
            continue

        go_id = _uri_to_go_id(node_id)
        if go_id is None:
            continue

        meta = node.get("meta")
        # Skip obsolete terms
        if meta and meta.get("deprecated", False):
            continue

        terms.append({
            "go_id": go_id,
            "name": node.get("lbl", ""),
            "namespace": _extract_namespace(meta),
            "definition": _extract_definition(meta),
        })

    return terms


def _parse_go_edges(graph_data: dict) -> list[tuple[str, str, str, dict]]:
    """Parse GO ontology edges from the OBO graph JSON.

    Returns list of (src_go_id, tgt_go_id, edge_type, props).
    Only includes edges where both endpoints are GO terms and the
    predicate is in our mapping.
    """
    edges = []
    for edge in graph_data.get("edges", []):
        sub_uri = edge.get("sub", "")
        obj_uri = edge.get("obj", "")
        pred = edge.get("pred", "")

        # Both endpoints must be GO terms
        src_id = _uri_to_go_id(sub_uri)
        tgt_id = _uri_to_go_id(obj_uri)
        if src_id is None or tgt_id is None:
            continue

        # Map predicate to edge type
        mapping = _PRED_MAP.get(pred)
        if mapping is None:
            continue

        edge_type, extra_props = mapping
        edges.append((src_id, tgt_id, edge_type, dict(extra_props)))

    return edges


def _parse_gaf(
    gaf_path: str,
    exclude_iea: bool = False,
) -> list[dict]:
    """Parse a GAF annotation file.

    Returns list of dicts with keys: uniprot_id, symbol, qualifier, go_id,
    evidence_code.

    GAF columns (0-indexed, tab-separated):
      0=DB, 1=DB_Object_ID, 2=DB_Object_Symbol, 3=Qualifier,
      4=GO_ID, 5=DB_Reference, 6=Evidence_Code, ...
    """
    annotations = []

    with open(gaf_path, "r", encoding="utf-8") as fh:
        for line in fh:
            # Skip comment lines
            if line.startswith("!"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue

            evidence_code = parts[6]
            if exclude_iea and evidence_code == "IEA":
                continue

            annotations.append({
                "uniprot_id": parts[1],
                "symbol": parts[2],
                "qualifier": parts[3],
                "go_id": parts[4],
                "evidence_code": evidence_code,
            })

    return annotations


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_go(
    client,
    data_dir: str,
    registry: Registry,
    exclude_iea: bool = False,
    tenant: str = "default",
) -> dict:
    """Load Gene Ontology terms and annotations into the knowledge graph.

    Args:
        client: SamyamaClient instance.
        data_dir: Directory containing go.json and goa_human.gaf.
        registry: Shared dedup registry (go_terms, annotated_with, proteins).
        exclude_iea: If True, skip IEA (electronic) annotations.
        tenant: Graph tenant name.

    Returns:
        Dict with loading statistics.
    """
    go_json_path = os.path.join(data_dir, "go.json")
    gaf_path = os.path.join(data_dir, "goa_human.gaf")

    # ------------------------------------------------------------------
    # Step 1: Create index on GOTerm(go_id)
    # ------------------------------------------------------------------
    create_index(client, "GOTerm", "go_id", tenant)

    # ------------------------------------------------------------------
    # Step 2: Parse go.json
    # ------------------------------------------------------------------
    print("[GO] Parsing go.json ...")
    with open(go_json_path, "r", encoding="utf-8") as fh:
        go_data = json.load(fh)

    # go.json has a "graphs" array; use the first (and typically only) graph
    graphs = go_data.get("graphs", [])
    if not graphs:
        print("[GO] ERROR: No graphs found in go.json")
        return {"source": "GO", "error": "no graphs in go.json"}

    graph_data = graphs[0]

    # ------------------------------------------------------------------
    # Step 3: Create GOTerm nodes
    # ------------------------------------------------------------------
    go_terms = _parse_go_terms(graph_data)
    print(f"[GO] Parsed {len(go_terms)} GO terms")

    node_progress = ProgressReporter("GO term nodes", len(go_terms))
    nodes_created = 0
    node_batch: list[tuple[str, dict]] = []
    node_batch_size = 100

    for term in go_terms:
        go_id = term["go_id"]
        node_progress.tick()

        if go_id in registry.go_terms:
            continue
        registry.go_terms.add(go_id)

        props: dict = {"go_id": go_id, "name": term["name"]}
        if term["namespace"]:
            props["namespace"] = term["namespace"]
        if term["definition"]:
            # Truncate very long definitions to avoid oversized Cypher
            defn = term["definition"]
            if len(defn) > 500:
                defn = defn[:497] + "..."
            props["definition"] = defn

        node_batch.append(("GOTerm", props))

        if len(node_batch) >= node_batch_size:
            nodes_created += batch_create_nodes(client, node_batch, tenant)
            node_batch.clear()

    if node_batch:
        nodes_created += batch_create_nodes(client, node_batch, tenant)
        node_batch.clear()

    print(f"  Created {nodes_created} GOTerm nodes")
    print(node_progress.summary())

    # ------------------------------------------------------------------
    # Step 4: Create GO hierarchy edges (IS_A, PART_OF, REGULATES)
    # ------------------------------------------------------------------
    raw_edges = _parse_go_edges(graph_data)
    print(f"[GO] Parsed {len(raw_edges)} GO hierarchy edges")

    hierarchy_progress = ProgressReporter("GO hierarchy edges", len(raw_edges))
    hierarchy_edge_list: list[tuple[str, str, str, str, str, str, str, dict]] = []

    for src_id, tgt_id, edge_type, edge_props in raw_edges:
        hierarchy_progress.tick()

        # Only create edges between terms we actually loaded
        if src_id not in registry.go_terms or tgt_id not in registry.go_terms:
            continue

        hierarchy_edge_list.append((
            "GOTerm", "go_id", src_id,
            "GOTerm", "go_id", tgt_id,
            edge_type,
            edge_props,
        ))

    hierarchy_created = batch_create_edges_fast(
        client, hierarchy_edge_list, tenant, chunk_size=50
    )

    print(f"  Created {hierarchy_created} GO hierarchy edges")
    print(hierarchy_progress.summary())

    # ------------------------------------------------------------------
    # Step 5: Parse GAF annotations
    # ------------------------------------------------------------------
    print(f"[GO] Parsing goa_human.gaf (exclude_iea={exclude_iea}) ...")
    annotations = _parse_gaf(gaf_path, exclude_iea=exclude_iea)
    print(f"  Parsed {len(annotations)} annotations")

    # ------------------------------------------------------------------
    # Step 6: Create ANNOTATED_WITH edges (Protein -> GOTerm)
    # ------------------------------------------------------------------
    annot_progress = ProgressReporter("GO annotations", len(annotations))
    annot_edge_list: list[tuple[str, str, str, str, str, str, str, dict]] = []
    skipped_no_protein = 0
    skipped_no_goterm = 0
    skipped_dup = 0

    for annot in annotations:
        annot_progress.tick()
        uid = annot["uniprot_id"]
        go_id = annot["go_id"]

        # Dedup: one edge per (uniprot_id, go_id) pair
        pair_key = f"{uid}|{go_id}"
        if pair_key in registry.annotated_with:
            skipped_dup += 1
            continue
        registry.annotated_with.add(pair_key)

        # The protein must exist in the registry (created by earlier loaders)
        if uid not in registry.proteins:
            skipped_no_protein += 1
            continue

        # The GO term must exist
        if go_id not in registry.go_terms:
            skipped_no_goterm += 1
            continue

        edge_props: dict = {"evidence_code": annot["evidence_code"]}
        if annot["qualifier"]:
            edge_props["qualifier"] = annot["qualifier"]

        annot_edge_list.append((
            "Protein", "uniprot_id", uid,
            "GOTerm", "go_id", go_id,
            "ANNOTATED_WITH",
            edge_props,
        ))

    annot_created = batch_create_edges_fast(
        client, annot_edge_list, tenant, chunk_size=50
    )

    print(f"  Created {annot_created} ANNOTATED_WITH edges")
    print(f"  Skipped: {skipped_no_protein} no protein, "
          f"{skipped_no_goterm} no GO term, {skipped_dup} duplicates")
    print(annot_progress.summary())

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    stats = {
        "source": "GO",
        "go_terms_created": nodes_created,
        "hierarchy_edges_created": hierarchy_created,
        "annotations_created": annot_created,
        "annotations_total_parsed": len(annotations),
        "skipped_no_protein": skipped_no_protein,
        "skipped_no_goterm": skipped_no_goterm,
        "skipped_duplicate": skipped_dup,
        "exclude_iea": exclude_iea,
    }
    print(f"[GO] Done. {stats}")
    return stats
