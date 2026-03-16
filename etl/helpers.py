"""Shared Cypher helpers for pathways-kg ETL loaders.

Follows cricket-kg pattern: batch CREATE, Registry dedup, index-first.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


def _escape(value: str) -> str:
    """Sanitize a string for embedding in Cypher literals."""
    if not isinstance(value, str):
        return str(value)
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


def _q(val) -> str:
    """Quote a value for Cypher: strings get single quotes, numbers/bools pass through."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    return f"'{_escape(str(val))}'"


def _prop_str(props: dict) -> str:
    """Convert a dict to Cypher property map string: {key1: val1, key2: val2}."""
    if not props:
        return "{}"
    parts = []
    for k, v in props.items():
        if v is not None:
            parts.append(f"{k}: {_q(v)}")
    return "{" + ", ".join(parts) + "}"


def batch_create_nodes(client, nodes: list[tuple[str, dict]], tenant: str = "default") -> int:
    """Create multiple nodes in a single CREATE statement.

    Args:
        client: SamyamaClient instance
        nodes: list of (label, properties_dict)
        tenant: tenant/graph name

    Returns:
        Number of nodes created
    """
    if not nodes:
        return 0
    parts = []
    for i, (label, props) in enumerate(nodes):
        parts.append(f"(n{i}:{label} {_prop_str(props)})")
    cypher = "CREATE " + ", ".join(parts)
    client.query(cypher, tenant)
    return len(nodes)


def batch_create_edges(
    client,
    edges: list[tuple[str, str, str, str, str, str, str, dict]],
    tenant: str = "default",
) -> int:
    """Create multiple edges in a single MATCH...CREATE statement.

    Args:
        client: SamyamaClient instance
        edges: list of (src_label, src_key_prop, src_key_val,
                        tgt_label, tgt_key_prop, tgt_key_val,
                        edge_type, edge_props)
        tenant: tenant/graph name

    Returns:
        Number of edges created
    """
    if not edges:
        return 0

    created = 0
    # Process edges one at a time to avoid variable name collisions
    # in complex MATCH patterns (batch MATCH is unreliable for distinct pairs)
    for src_label, src_kp, src_kv, tgt_label, tgt_kp, tgt_kv, etype, eprops in edges:
        prop_part = f" {_prop_str(eprops)}" if eprops else ""
        cypher = (
            f"MATCH (a:{src_label} {{{src_kp}: {_q(src_kv)}}}), "
            f"(b:{tgt_label} {{{tgt_kp}: {_q(tgt_kv)}}}) "
            f"CREATE (a)-[:{etype}{prop_part}]->(b)"
        )
        try:
            client.query(cypher, tenant)
            created += 1
        except Exception:
            # Edge creation may fail if source/target not found; skip
            pass
    return created


def batch_create_edges_fast(
    client,
    edges: list[tuple[str, str, str, str, str, str, str, dict]],
    tenant: str = "default",
    chunk_size: int = 50,
) -> int:
    """Create edges using UNWIND for better performance with large batches.

    Groups edges by (src_label, tgt_label, edge_type) and uses UNWIND
    to create many edges of the same type in one query.
    """
    if not edges:
        return 0

    # Group by (src_label, tgt_label, edge_type)
    groups: dict[tuple, list] = {}
    for src_label, src_kp, src_kv, tgt_label, tgt_kp, tgt_kv, etype, eprops in edges:
        key = (src_label, src_kp, tgt_label, tgt_kp, etype)
        groups.setdefault(key, []).append((src_kv, tgt_kv, eprops))

    created = 0
    for (src_label, src_kp, tgt_label, tgt_kp, etype), items in groups.items():
        for i in range(0, len(items), chunk_size):
            chunk = items[i : i + chunk_size]
            # Build individual MATCH...CREATE per chunk item
            parts = []
            match_parts = []
            create_parts = []
            for j, (src_kv, tgt_kv, eprops) in enumerate(chunk):
                prop_part = f" {_prop_str(eprops)}" if eprops else ""
                match_parts.append(
                    f"(a{j}:{src_label} {{{src_kp}: {_q(src_kv)}}}), "
                    f"(b{j}:{tgt_label} {{{tgt_kp}: {_q(tgt_kv)}}})"
                )
                create_parts.append(f"(a{j})-[:{etype}{prop_part}]->(b{j})")
            cypher = "MATCH " + ", ".join(match_parts) + " CREATE " + ", ".join(create_parts)
            try:
                client.query(cypher, tenant)
                created += len(chunk)
            except Exception:
                # Fall back to one-by-one if batch fails
                for src_kv, tgt_kv, eprops in chunk:
                    prop_part = f" {_prop_str(eprops)}" if eprops else ""
                    cy = (
                        f"MATCH (a:{src_label} {{{src_kp}: {_q(src_kv)}}}), "
                        f"(b:{tgt_label} {{{tgt_kp}: {_q(tgt_kv)}}}) "
                        f"CREATE (a)-[:{etype}{prop_part}]->(b)"
                    )
                    try:
                        client.query(cy, tenant)
                        created += 1
                    except Exception:
                        pass
    return created


def create_index(client, label: str, prop: str, tenant: str = "default"):
    """Create an index if it doesn't already exist."""
    cypher = f"CREATE INDEX ON :{label}({prop})"
    try:
        client.query(cypher, tenant)
    except Exception:
        pass  # Index may already exist


@dataclass
class Registry:
    """Memory-based deduplication registry to avoid redundant MERGE queries.

    Tracks which entities have already been created by their key property.
    """

    pathways: set = field(default_factory=set)
    proteins: set = field(default_factory=set)
    genes: set = field(default_factory=set)
    reactions: set = field(default_factory=set)
    compounds: set = field(default_factory=set)
    complexes: set = field(default_factory=set)
    diseases: set = field(default_factory=set)
    go_terms: set = field(default_factory=set)
    drugs: set = field(default_factory=set)
    # Edge dedup
    protein_pathways: set = field(default_factory=set)
    interacts_with: set = field(default_factory=set)
    annotated_with: set = field(default_factory=set)
    encodes: set = field(default_factory=set)


class ProgressReporter:
    """Report loading progress with rate tracking."""

    def __init__(self, phase: str, total: int = 0):
        self.phase = phase
        self.total = total
        self.count = 0
        self.errors = 0
        self.t0 = time.time()

    def tick(self, n: int = 1):
        self.count += n
        if self.count % 500 == 0 or (self.count < 500 and self.count % 100 == 0):
            elapsed = time.time() - self.t0
            rate = self.count / elapsed if elapsed > 0 else 0
            total_str = f"/{self.total}" if self.total else ""
            print(f"  [{self.phase}] {self.count}{total_str} ({rate:.0f}/s, {elapsed:.0f}s)")

    def error(self):
        self.errors += 1

    def summary(self) -> dict:
        elapsed = time.time() - self.t0
        return {
            "phase": self.phase,
            "processed": self.count,
            "errors": self.errors,
            "elapsed_s": round(elapsed, 1),
            "rate": round(self.count / elapsed, 1) if elapsed > 0 else 0,
        }
