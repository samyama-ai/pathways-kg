"""Pathways Knowledge Graph — Main ETL Orchestrator.

Ties together all phase loaders (Reactome, STRING, GO, WikiPathways, UniProt)
into a single load_pathways() entry point with phase selection, timing, and
summary reporting.

Usage:
    python -m etl.loader --data-dir data --phases reactome string go
    python -m etl.loader --data-dir data  # All phases
    python -m etl.loader --data-dir data --string-threshold 900
"""

from __future__ import annotations

import argparse
import sys
import time

from etl.helpers import Registry


# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------

ALL_PHASES = ["reactome", "string", "go", "wikipathways", "uniprot"]


def _run_phase(
    phase: str,
    client,
    data_dir: str,
    registry: Registry,
    *,
    organism: str = "human",
    string_threshold: int = 700,
    go_exclude_iea: bool = False,
    tenant: str = "default",
) -> dict:
    """Dispatch to the appropriate phase loader.

    Returns the stats dict from the phase loader.
    """
    if phase == "reactome":
        from etl.reactome_loader import load_reactome

        return load_reactome(
            client,
            data_dir=data_dir,
            registry=registry,
            organism=organism,
            tenant=tenant,
        )

    elif phase == "string":
        from etl.string_loader import load_string

        return load_string(
            client,
            data_dir=data_dir,
            registry=registry,
            threshold=string_threshold,
            tenant=tenant,
        )

    elif phase == "go":
        from etl.go_loader import load_go

        return load_go(
            client,
            data_dir=data_dir,
            registry=registry,
            exclude_iea=go_exclude_iea,
            tenant=tenant,
        )

    elif phase == "wikipathways":
        from etl.wikipathways_loader import load_wikipathways

        return load_wikipathways(
            client,
            data_dir=data_dir,
            registry=registry,
            organism=organism,
            tenant=tenant,
        )

    elif phase == "uniprot":
        from etl.uniprot_loader import load_uniprot

        return load_uniprot(
            client,
            data_dir=data_dir,
            registry=registry,
            organism=organism,
            tenant=tenant,
        )

    else:
        print(f"[WARN] Unknown phase: {phase}, skipping")
        return {"source": phase, "error": "unknown phase"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_pathways(
    client,
    data_dir: str = "data",
    phases: list[str] | None = None,
    organism: str = "human",
    string_threshold: int = 700,
    go_exclude_iea: bool = False,
    tenant: str = "default",
) -> dict:
    """Load biological pathways data into the knowledge graph.

    Runs each requested phase in order, sharing a single Registry for
    cross-phase deduplication.

    Args:
        client: SamyamaClient instance (embedded or remote).
        data_dir: Root directory containing per-source subdirectories
                  (reactome/, string/, go/, wikipathways/, uniprot/).
        phases: List of phases to run. Default: all phases.
        organism: Target organism (currently only "human").
        string_threshold: Minimum STRING combined_score (default 700).
        go_exclude_iea: If True, exclude IEA (electronic) GO annotations.
        tenant: Graph tenant name.

    Returns:
        Combined statistics dict with per-phase results and totals.
    """
    if phases is None:
        phases = list(ALL_PHASES)

    # Validate phase names
    invalid = [p for p in phases if p not in ALL_PHASES]
    if invalid:
        print(f"[WARN] Unknown phases ignored: {invalid}")
        phases = [p for p in phases if p in ALL_PHASES]

    if not phases:
        print("[ERROR] No valid phases to run.")
        return {}

    print("=" * 60)
    print(f"Pathways KG — Loading {len(phases)} phase(s): {', '.join(phases)}")
    print(f"  data_dir:         {data_dir}")
    print(f"  organism:         {organism}")
    print(f"  string_threshold: {string_threshold}")
    print(f"  go_exclude_iea:   {go_exclude_iea}")
    print(f"  tenant:           {tenant}")
    print("=" * 60)

    registry = Registry()
    phase_results: list[dict] = []
    t0_total = time.time()

    for phase in phases:
        print(f"\n{'─' * 50}")
        print(f"Phase: {phase.upper()}")
        print(f"{'─' * 50}")

        t0_phase = time.time()
        try:
            stats = _run_phase(
                phase,
                client,
                data_dir,
                registry,
                organism=organism,
                string_threshold=string_threshold,
                go_exclude_iea=go_exclude_iea,
                tenant=tenant,
            )
            elapsed = time.time() - t0_phase
            stats["elapsed_s"] = round(elapsed, 1)
            stats["status"] = "ok"
        except FileNotFoundError as exc:
            elapsed = time.time() - t0_phase
            stats = {
                "source": phase,
                "status": "skipped",
                "reason": str(exc),
                "elapsed_s": round(elapsed, 1),
            }
            print(f"[SKIP] {phase}: {exc}")
        except Exception as exc:
            elapsed = time.time() - t0_phase
            stats = {
                "source": phase,
                "status": "error",
                "reason": str(exc),
                "elapsed_s": round(elapsed, 1),
            }
            print(f"[ERROR] {phase}: {exc}")

        phase_results.append(stats)
        print(f"  Phase {phase} completed in {elapsed:.1f}s")

    elapsed_total = time.time() - t0_total

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("Pathways KG — Load Summary")
    print(f"{'=' * 60}")
    print(f"{'Phase':<15s} {'Status':<10s} {'Time':>8s}  Details")
    print(f"{'─' * 55}")

    for result in phase_results:
        source = result.get("source", "?")
        status = result.get("status", "?")
        elapsed_s = result.get("elapsed_s", 0)
        # Summarize key counts
        detail_parts = []
        for k, v in result.items():
            if k in ("source", "status", "elapsed_s", "reason"):
                continue
            if isinstance(v, (int, float)) and v > 0:
                detail_parts.append(f"{k}={v}")
        detail = ", ".join(detail_parts[:5]) if detail_parts else result.get("reason", "")
        print(f"  {source:<13s} {status:<10s} {elapsed_s:>6.1f}s  {detail}")

    print(f"{'─' * 55}")
    print(f"  {'TOTAL':<13s} {'':10s} {elapsed_total:>6.1f}s")

    # Registry summary
    print(f"\nRegistry totals:")
    print(f"  Pathways:  {len(registry.pathways):>8,d}")
    print(f"  Proteins:  {len(registry.proteins):>8,d}")
    print(f"  Genes:     {len(registry.genes):>8,d}")
    print(f"  Reactions: {len(registry.reactions):>8,d}")
    print(f"  Compounds: {len(registry.compounds):>8,d}")
    print(f"  Complexes: {len(registry.complexes):>8,d}")
    print(f"  Diseases:  {len(registry.diseases):>8,d}")
    print(f"  GO Terms:  {len(registry.go_terms):>8,d}")
    print(f"  Drugs:     {len(registry.drugs):>8,d}")
    print(f"{'=' * 60}\n")

    # Build combined result
    combined: dict = {
        "phases_loaded": [r.get("source") for r in phase_results if r.get("status") == "ok"],
        "total_elapsed_s": round(elapsed_total, 1),
    }
    # Aggregate numeric counts across phases
    for result in phase_results:
        for k, v in result.items():
            if isinstance(v, int) and k not in ("elapsed_s",):
                combined[k] = combined.get(k, 0) + v

    return combined


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Load biological pathways data into Samyama graph.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root directory for data files (default: data)",
    )
    parser.add_argument(
        "--phases",
        nargs="*",
        default=None,
        help=f"Phases to load (default: all). Choices: {', '.join(ALL_PHASES)}",
    )
    parser.add_argument(
        "--organism",
        default="human",
        choices=["human"],
        help="Target organism (default: human)",
    )
    parser.add_argument(
        "--string-threshold",
        type=int,
        default=700,
        help="Minimum STRING combined_score for PPI edges (default: 700)",
    )
    parser.add_argument(
        "--go-exclude-iea",
        action="store_true",
        help="Exclude IEA (electronic annotation) evidence from GO annotations",
    )
    parser.add_argument(
        "--tenant",
        default="default",
        help="Graph tenant name (default: default)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Samyama server URL (omit for embedded mode)",
    )
    args = parser.parse_args()

    from samyama import SamyamaClient

    if args.url:
        client = SamyamaClient.connect(args.url)
    else:
        client = SamyamaClient.embedded()

    load_pathways(
        client,
        data_dir=args.data_dir,
        phases=args.phases,
        organism=args.organism,
        string_threshold=args.string_threshold,
        go_exclude_iea=args.go_exclude_iea,
        tenant=args.tenant,
    )


if __name__ == "__main__":
    main()
