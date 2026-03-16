"""Download all required data files for pathways-kg.

Fetches Reactome, STRING, Gene Ontology, WikiPathways, and UniProt datasets.
Supports resume (skips files that already exist with the expected size).

Usage:
    python -m etl.download_data --data-dir data --organism human
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Source definitions (human / organism_id 9606)
# ---------------------------------------------------------------------------

REACTOME_FILES = {
    "UniProt2Reactome_All_Levels.txt": (
        "https://reactome.org/download/current/UniProt2Reactome_All_Levels.txt"
    ),
    "ReactomePathways.txt": (
        "https://reactome.org/download/current/ReactomePathways.txt"
    ),
    "ReactomePathwaysRelation.txt": (
        "https://reactome.org/download/current/ReactomePathwaysRelation.txt"
    ),
    "reactome.homo_sapiens.interactions.tab-delimited.txt": (
        "https://reactome.org/download/current/interactors/"
        "reactome.homo_sapiens.interactions.tab-delimited.txt"
    ),
    "ComplexParticipantsPubMedIdentifiers_human.txt": (
        "https://reactome.org/download/current/"
        "ComplexParticipantsPubMedIdentifiers_human.txt"
    ),
}

STRING_FILES = {
    "9606.protein.links.v12.0.txt.gz": (
        "https://stringdb-downloads.org/download/protein.links.v12.0/"
        "9606.protein.links.v12.0.txt.gz"
    ),
    "9606.protein.info.v12.0.txt.gz": (
        "https://stringdb-downloads.org/download/protein.info.v12.0/"
        "9606.protein.info.v12.0.txt.gz"
    ),
    "9606.protein.aliases.v12.0.txt.gz": (
        "https://stringdb-downloads.org/download/protein.aliases.v12.0/"
        "9606.protein.aliases.v12.0.txt.gz"
    ),
}

GO_FILES = {
    "go.json.gz": (
        "http://release.geneontology.org/2024-06-17/ontology/go.json.gz"
    ),
    "goa_human.gaf.gz": (
        "http://geneontology.org/gene-associations/goa_human.gaf.gz"
    ),
}

WIKIPATHWAYS_FILES = {
    "wikipathways-Homo_sapiens.gmt": (
        "https://data.wikipathways.org/current/gmt/"
        "wikipathways-20240310-gmt-Homo_sapiens.gmt"
    ),
}

UNIPROT_URL = (
    "https://rest.uniprot.org/uniprotkb/stream?"
    "query=(organism_id:9606)+AND+(reviewed:true)"
    "&format=tsv"
    "&fields=accession,gene_names,protein_name,organism_name,"
    "length,cc_disease,cc_function,xref_drugbank,xref_geneid"
)

# Map source name -> (file dict, subdirectory)
SOURCES = {
    "reactome": (REACTOME_FILES, "reactome"),
    "string": (STRING_FILES, "string"),
    "go": (GO_FILES, "go"),
    "wikipathways": (WIKIPATHWAYS_FILES, "wikipathways"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_size(nbytes: int) -> str:
    """Format byte count as human-readable string."""
    if nbytes < 1024:
        return f"{nbytes} B"
    elif nbytes < 1024 ** 2:
        return f"{nbytes / 1024:.1f} KB"
    elif nbytes < 1024 ** 3:
        return f"{nbytes / 1024**2:.1f} MB"
    else:
        return f"{nbytes / 1024**3:.2f} GB"


def _should_skip(path: Path, expected_size: int | None) -> bool:
    """Return True if the file exists and matches the expected size."""
    if not path.exists():
        return False
    if expected_size is None or expected_size <= 0:
        # Cannot verify size; skip if file is non-empty
        return path.stat().st_size > 0
    return path.stat().st_size == expected_size


def _remote_size(url: str, timeout: int = 15) -> int | None:
    """HEAD request to get Content-Length, or None if unavailable."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=timeout)
        cl = resp.headers.get("Content-Length")
        if cl and cl.isdigit():
            return int(cl)
    except requests.RequestException:
        pass
    return None


def download_file(url: str, dest: Path, label: str = "") -> Path:
    """Stream-download a single file with progress.

    Returns the path of the downloaded file.
    Raises on HTTP errors.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    display = label or dest.name

    # Check remote size for resume logic
    remote_sz = _remote_size(url)
    if _should_skip(dest, remote_sz):
        size_str = _fmt_size(dest.stat().st_size)
        print(f"  [skip] {display} ({size_str}, already exists)")
        return dest

    print(f"  [download] {display} ...", end="", flush=True)
    t0 = time.time()

    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()

    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    last_pct = -1

    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=256 * 1024):
            if chunk:
                fh.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    if pct >= last_pct + 10:
                        print(f" {pct}%", end="", flush=True)
                        last_pct = pct

    elapsed = time.time() - t0
    final_size = dest.stat().st_size
    rate = final_size / elapsed if elapsed > 0 else 0
    print(f" done ({_fmt_size(final_size)}, {elapsed:.1f}s, {_fmt_size(int(rate))}/s)")
    return dest


def decompress_gzip(gz_path: Path) -> Path:
    """Decompress a .gz file in place, returning path of decompressed file.

    Removes the .gz suffix. Skips if already decompressed.
    """
    if not gz_path.name.endswith(".gz"):
        return gz_path

    out_path = gz_path.with_suffix("")  # strip .gz
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [skip] decompress {gz_path.name} (already done)")
        return out_path

    print(f"  [decompress] {gz_path.name} -> {out_path.name} ...", end="", flush=True)
    t0 = time.time()
    with gzip.open(gz_path, "rb") as fin, open(out_path, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    elapsed = time.time() - t0
    size = out_path.stat().st_size
    print(f" done ({_fmt_size(size)}, {elapsed:.1f}s)")
    return out_path


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def download_source(
    source_name: str,
    files: dict[str, str],
    data_dir: Path,
) -> dict[str, Path]:
    """Download all files for a single source.

    Returns dict mapping filename (without .gz) to local path.
    """
    subdir = data_dir / source_name
    subdir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}

    print(f"\n=== {source_name.upper()} ===")
    for fname, url in files.items():
        try:
            dest = subdir / fname
            download_file(url, dest, label=fname)

            # Decompress gzipped files
            if fname.endswith(".gz"):
                decompressed = decompress_gzip(dest)
                result[decompressed.name] = decompressed
            else:
                result[fname] = dest
        except requests.RequestException as exc:
            print(f"  [ERROR] {fname}: {exc}")
        except OSError as exc:
            print(f"  [ERROR] {fname} (I/O): {exc}")

    return result


def download_uniprot(data_dir: Path) -> dict[str, Path]:
    """Download UniProt reviewed human proteome TSV."""
    subdir = data_dir / "uniprot"
    subdir.mkdir(parents=True, exist_ok=True)
    fname = "uniprot_human_reviewed.tsv"

    print("\n=== UNIPROT ===")
    try:
        dest = subdir / fname
        download_file(UNIPROT_URL, dest, label=fname)
        return {fname: dest}
    except requests.RequestException as exc:
        print(f"  [ERROR] {fname}: {exc}")
        return {}


def download_all(
    data_dir: str | Path,
    phases: list[str] | None = None,
) -> dict[str, Path]:
    """Download all data files.

    Args:
        data_dir: Root data directory (subdirs created automatically).
        phases: Optional list of source names to download.
                Defaults to all: ["reactome", "string", "go", "wikipathways", "uniprot"].

    Returns:
        Dict mapping filename to local file path.
    """
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    if phases is None:
        phases = list(SOURCES.keys()) + ["uniprot"]

    all_files: dict[str, Path] = {}
    t0 = time.time()

    for phase in phases:
        if phase == "uniprot":
            result = download_uniprot(data_path)
        elif phase in SOURCES:
            file_dict, _subdir = SOURCES[phase]
            result = download_source(phase, file_dict, data_path)
        else:
            print(f"\n[WARN] Unknown source: {phase}, skipping")
            continue
        all_files.update(result)

    elapsed = time.time() - t0
    print(f"\n--- Download complete: {len(all_files)} files in {elapsed:.0f}s ---")
    for name, path in sorted(all_files.items()):
        size = path.stat().st_size if path.exists() else 0
        print(f"  {name}: {_fmt_size(size)} -> {path}")

    return all_files


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download datasets for pathways-kg.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root directory for downloaded data (default: data)",
    )
    parser.add_argument(
        "--organism",
        default="human",
        choices=["human"],
        help="Organism to download data for (currently only human)",
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help="Specific sources to download (e.g. reactome string). Default: all",
    )
    args = parser.parse_args()

    if args.organism != "human":
        print(f"Unsupported organism: {args.organism}. Only 'human' is supported.")
        sys.exit(1)

    download_all(args.data_dir, phases=args.sources)


if __name__ == "__main__":
    main()
