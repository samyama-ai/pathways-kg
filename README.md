# Pathways Knowledge Graph

**119K nodes. 835K edges. Every human biological pathway, protein interaction, and GO annotation in one graph.**

![Pathways KG terminal demo](demo/pathways.gif)

> Part of the **Samyama** ecosystem — loaded into and queried via the graph engine at [samyama-ai/samyama-graph](https://github.com/samyama-ai/samyama-graph).
> This repo holds the loader and source-data specifics for the KG.

<a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-blue" alt="License"></a>

---

We loaded Reactome pathways, STRING protein interactions, Gene Ontology, WikiPathways, and UniProt, then asked:

> *"Which protein has the most interaction partners?"*

```cypher
MATCH (p:Protein)-[:INTERACTS_WITH]-(other:Protein)
RETURN p.name AS protein, count(DISTINCT other) AS partners
ORDER BY partners DESC LIMIT 5
```

| Protein | Partners |
|---------|----------|
| **TP53** | **571** |
| UBC | 524 |
| EGFR | 441 |
| APP | 395 |
| ESR1 | 384 |

**TP53 -- the most connected hub in the human interactome.** Powered by [Samyama Graph](https://github.com/samyama-ai/samyama-graph).

[See all 100 benchmark queries →](https://samyama-ai.github.io/samyama-graph-book/biomedical_benchmark.html)

---

## Demo

A narrated terminal walkthrough — loads a real Reactome subset and answers four
pathway-biology questions in plain Cypher (hierarchy, protein hub-centrality,
protein-dense pathways).

The demo loads a fast, representative subset of REAL Reactome data: all 2,848
human pathways and their CHILD_OF hierarchy, plus the first 40,000 human
protein-participation rows from UniProt2Reactome (2,745 proteins, 35,160
PARTICIPATES_IN edges). Edges are created one-by-one, so this caps the
~900K-row participation file to keep the demo under a minute. Load the full KG
with `python -m etl.loader --data-dir data`.

```bash
# Run
source ~/projects/venv/bin/activate
PYTHONUNBUFFERED=1 python -m demo.demo

# Re-record
asciinema rec --overwrite --cols 92 --rows 32 --idle-time-limit 2.0 \
  -c "bash -c 'source ~/projects/venv/bin/activate && PYTHONUNBUFFERED=1 python -m demo.demo'" \
  demo/pathways.cast
agg demo/pathways.cast demo/pathways.gif
aws s3 cp demo/pathways.gif s3://samyama-data/demos/pathways.gif
```

---

## Schema

**5 node labels** -- Protein (37,990), GOTerm (51,897), Complex (15,963), Reaction (9,988), Pathway (2,848)

**9 edge types** -- ANNOTATED_WITH (265K), INTERACTS_WITH (228K), PARTICIPATES_IN (140K), CATALYZES (121K), IS_A (59K), COMPONENT_OF (8K), PART_OF (7K), REGULATES (3K), CHILD_OF (3K)

**5 data sources** -- Reactome, STRING v12.0, Gene Ontology, WikiPathways, UniProt (all human, organism 9606)

## Quick Start

### Load from snapshot (recommended)

```bash
# Download (9.6 MB)
curl -LO https://github.com/samyama-ai/samyama-graph/releases/download/kg-snapshots-v3/pathways.sgsnap

# Start Samyama and import
./target/release/samyama
curl -X POST http://localhost:8080/api/tenants \
  -H 'Content-Type: application/json' \
  -d '{"id":"pathways","name":"Biological Pathways KG"}'
curl -X POST http://localhost:8080/api/tenants/pathways/snapshot/import \
  -F "file=@pathways.sgsnap"
```

### Build from source

```bash
git clone https://github.com/samyama-ai/pathways-kg.git && cd pathways-kg
pip install -e .
python -m etl.download_data --data-dir data        # ~1.9 GB
python -m etl.loader --data-dir data --url http://localhost:8080
```

## Example Queries

```cypher
-- Pathway crosstalk: shared proteins between pathways
MATCH (p1:Pathway)<-[:PARTICIPATES_IN]-(prot:Protein)-[:PARTICIPATES_IN]->(p2:Pathway)
WHERE p1.name < p2.name
WITH p1, p2, count(prot) AS shared WHERE shared >= 100
RETURN p1.name, p2.name, shared ORDER BY shared DESC LIMIT 10

-- TP53 two-hop neighborhood
MATCH (tp53:Protein {name: 'TP53'})-[:INTERACTS_WITH]-(hop1:Protein)-[:INTERACTS_WITH]-(hop2:Protein)
WHERE hop2 <> tp53
RETURN DISTINCT hop2.name AS protein LIMIT 15
```

## Part of the Biomedical Trifecta

This KG is one of three biomedical knowledge graphs that together form Samyama's billion-edge benchmark: [Clinical Trials](https://github.com/samyama-ai/clinicaltrials-kg) (27M edges) + **Pathways** (835K edges) + [Drug Interactions](https://github.com/samyama-ai/druginteractions-kg) (388K edges), federated with [PubMed](https://github.com/samyama-ai/pubmed-kg) (1.04B edges).

## Links

| | |
|---|---|
| Samyama Graph | [github.com/samyama-ai/samyama-graph](https://github.com/samyama-ai/samyama-graph) |
| The Book | [samyama-ai.github.io/samyama-graph-book](https://samyama-ai.github.io/samyama-graph-book/) |
| Benchmark (100 queries) | [Biomedical Benchmark](https://samyama-ai.github.io/samyama-graph-book/biomedical_benchmark.html) |
| Contact | [samyama.dev/contact](https://samyama.dev/contact) |

## License

Apache 2.0
