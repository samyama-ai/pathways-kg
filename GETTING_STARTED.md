# Getting Started — Pathways Knowledge Graph

From `git clone` to your first answer. The **snapshot path** is the fastest (a few minutes).

---

## 1. Prerequisites

- **Python ≥ 3.10** (required by the `samyama` SDK; macOS ships 3.9 — use `python3.10`+).
- **git**
- **Docker** — to run the Samyama engine (needed for the snapshot import and for serving MCP / CLI / API).

## 2. Install

```bash
git clone https://github.com/samyama-ai/pathways-kg.git
cd pathways-kg
python3 -m venv .venv && source .venv/bin/activate     # Python >= 3.10
pip install -r requirements.txt
```

## 3. Run the engine (Docker)

```bash
docker run --rm -p 8080:8080 -p 6379:6379 public.ecr.aws/f9f6l5u4/samyama-graph:1.1.0
```

## 4. Load the graph — into the `pathways` tenant

### Option A — snapshot (recommended, ~seconds)
```bash
curl -LO https://github.com/samyama-ai/samyama-graph/releases/download/kg-snapshots-v3/pathways.sgsnap
curl -X POST http://localhost:8080/api/tenants -H 'Content-Type: application/json' \
  -d '{"id":"pathways","name":"Pathways KG"}'
curl -X POST http://localhost:8080/api/tenants/pathways/snapshot/import -F "file=@pathways.sgsnap"
```

### Option B — build from source (downloads Reactome / STRING / GO / UniProt)
```bash
python -m etl.download_data --data-dir data
python -m etl.loader --data-dir data --url http://localhost:8080                    # all phases → pathways tenant
python -m etl.loader --data-dir data --url http://localhost:8080 --phases reactome uniprot   # subset
```
*(The loader defaults to the `pathways` tenant; override with `--tenant`. Omit `--url` to build an
in-memory graph instead.)*

## 5. Ask your first question

Fastest is **Claude over MCP** — see **[docs/QUERYING.md](docs/QUERYING.md)**. Quick check over HTTP —
the most connected protein in the human interactome:

```bash
curl -s -X POST http://localhost:8080/api/query -H 'Content-Type: application/json' -d '{
  "graph": "pathways",
  "query": "MATCH (p:Protein)-[:INTERACTS_WITH]-(o:Protein) RETURN p.name AS protein, count(DISTINCT o) AS partners ORDER BY partners DESC LIMIT 5"
}'
# → TP53 (739), RPS27A (717), EGFR (502), CTNNB1 (464), AKT1 (435)
```

## 6. The ETL pipeline

- Data sources: **Reactome, STRING v12.0, Gene Ontology, WikiPathways, UniProt** (all human, organism 9606).
- `etl/download_data.py` — fetches the raw datasets into `data/`.
- `etl/loader.py` — orchestrates the phases (`reactome`, `string`, `go`, `wikipathways`, `uniprot`) into
  the graph (Protein, GOTerm, Complex, Reaction, Pathway). Run `python -m etl.loader --help`.

## Next
- **[docs/QUERYING.md](docs/QUERYING.md)** — MCP (Claude), HTTP API, and the Samyama CLI
- **[README](README.md#schema)** — schema · **[Benchmark](https://samyama-ai.github.io/samyama-graph-book/biomedical_benchmark.html)** — 100 queries
