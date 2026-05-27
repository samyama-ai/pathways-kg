"""Narrated terminal demo: Biological pathways on Samyama.

Record with asciinema:
    asciinema rec --overwrite --cols 92 --rows 32 --idle-time-limit 2.0 \
      -c "bash -c 'source ~/projects/venv/bin/activate && \
      PYTHONUNBUFFERED=1 python -m demo.demo'" demo/pathways.cast

Loads a representative SUBSET of the Reactome human pathway data — every human
pathway (2,848) and its CHILD_OF hierarchy, plus the first 40,000 human
protein-participation rows from UniProt2Reactome — into a Samyama graph and
walks the question every systems-biologist asks: "how do proteins, reactions
and pathways connect?"

Subset rationale: edges are created one-by-one, so the full ~900K-row
participation file is slow. The demo caps it (load_demo_subset) so it finishes
in well under a minute while still using REAL Reactome data (no mocks).
Load everything with: python -m etl.loader --data-dir data
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from samyama import SamyamaClient

from etl.helpers import Registry
from etl.reactome_loader import (
    _load_pathways,
    _load_pathway_hierarchy,
    _load_proteins_and_participation,
)

console = Console()
G = "default"
DATA = "data"
MAX_UNIPROT_ROWS = 40_000


def pause(s: float = 1.4) -> None:
    time.sleep(s)


def step(title: str) -> None:
    console.print()
    console.rule(f"[bold cyan]{title}")
    pause(0.6)


def run(client, q, label):
    console.print(f"  [dim]cypher>[/dim] [yellow]{q}[/yellow]")
    rows = client.query(q, G).records
    one = len(rows) == 1 and len(rows[0]) == 1
    console.print(f"  [green]→[/green] {label}: [bold]{rows[0][0] if one else rows}[/bold]")
    pause()
    return rows


def load_demo_subset(client) -> dict:
    """Load a fast, real Reactome subset: all human pathways + hierarchy,
    plus a capped slice of protein participation."""
    reg = Registry()
    p = _load_pathways(client, Path(DATA), reg, G)
    h = _load_pathway_hierarchy(client, Path(DATA), reg, G)
    pr = _load_proteins_and_participation(
        client, Path(DATA), reg, G, max_human_rows=MAX_UNIPROT_ROWS
    )
    return {
        "pathways": p.get("created", 0),
        "hierarchy": h.get("created", 0),
        "proteins": pr.get("proteins_created", 0),
        "participates_in": pr.get("edges_created", 0),
    }


def main() -> None:
    console.print(Panel.fit(
        "[bold]Samyama · Biological Pathways Knowledge Graph[/bold]\n"
        "\"How do proteins, reactions and pathways connect?\"\n"
        "[dim]data: Reactome human pathways (subset) · reactome.org[/dim]",
        border_style="cyan",
    ))
    pause(1.2)

    step("1 · Load Reactome human pathways into Samyama")
    console.print(f"  [dim]all human pathways + hierarchy + first {MAX_UNIPROT_ROWS:,} "
                  "protein-participation rows…[/dim]")
    stats = load_demo_subset(client := SamyamaClient.embedded())
    console.print(f"  [green]loaded[/green] {stats['pathways']} pathways, "
                  f"{stats['proteins']} proteins, "
                  f"{stats['hierarchy']} CHILD_OF + {stats['participates_in']} PARTICIPATES_IN edges")
    run(client, "MATCH (p:Pathway) RETURN count(p) AS pathways", "human pathways")

    step("2 · Which top-level pathways have the most sub-pathways?")
    run(
        client,
        "MATCH (child:Pathway)-[:CHILD_OF]->(parent:Pathway) "
        "RETURN parent.name AS pathway, count(child) AS subpathways "
        "ORDER BY subpathways DESC LIMIT 5",
        "broadest pathway hierarchies",
    )

    step("3 · Which proteins participate in the most pathways? (hubs)")
    run(
        client,
        "MATCH (pr:Protein)-[:PARTICIPATES_IN]->(pw:Pathway) "
        "RETURN pr.uniprot_id AS protein, count(DISTINCT pw) AS pathways "
        "ORDER BY pathways DESC LIMIT 5",
        "most pleiotropic proteins",
    )

    step("4 · Which pathways recruit the most distinct proteins?")
    console.print("  [dim]rank pathways by their distinct participating proteins…[/dim]")
    pause()
    run(
        client,
        "MATCH (pr:Protein)-[:PARTICIPATES_IN]->(pw:Pathway) "
        "WITH pw, count(DISTINCT pr) AS proteins "
        "WHERE proteins > 5 "
        "RETURN pw.name AS pathway, proteins "
        "ORDER BY proteins DESC LIMIT 5",
        "most protein-dense pathways",
    )

    console.print()
    console.print(Panel.fit(
        "[bold green]Reactions, proteins, pathways — one graph engine[/bold green]\n"
        "hierarchy, hub-centrality and protein density answered in plain Cypher.\n"
        "[dim]scale to 119K nodes / 835K edges: python -m etl.loader --data-dir data[/dim]",
        border_style="green",
    ))
    pause(1.5)


if __name__ == "__main__":
    main()
