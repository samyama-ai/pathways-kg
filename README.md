# Pathways Knowledge Graph

> Biological pathways knowledge graph built on [Samyama Graph](https://github.com/samyama-ai/samyama-graph) — Reactome, STRING, Gene Ontology, WikiPathways, UniProt

[![Pathways KG Demo](https://github.com/samyama-ai/samyama-graph/releases/download/kg-snapshots-v3/pathways-preview.gif)](https://github.com/samyama-ai/samyama-graph/releases/download/kg-snapshots-v3/samyama-pathways-demo.mp4)

*Click for full demo (2:06) — Dashboard, Cypher Queries, and Graph Simulation*

## Graph Stats

| Label | Count | Source |
|-------|------:|--------|
| GOTerm | 51,897 | Gene Ontology |
| Protein | 37,990 | Reactome, STRING, UniProt |
| Complex | 15,963 | Reactome |
| Reaction | 9,988 | Reactome |
| Pathway | 2,848 | Reactome, WikiPathways |
| **Total** | **118,686 nodes** | |

| Edge Type | Count |
|-----------|------:|
| ANNOTATED_WITH | 265,492 |
| INTERACTS_WITH | 227,818 |
| PARTICIPATES_IN | 140,153 |
| CATALYZES | 121,365 |
| IS_A | 58,799 |
| COMPONENT_OF | 8,186 |
| PART_OF | 7,122 |
| REGULATES | 2,986 |
| CHILD_OF | 2,864 |
| **Total** | **834,785 edges** |

## Data Sources

All open-license, human-only (organism 9606):

| Source | License | Content |
|--------|---------|---------|
| [Reactome](https://reactome.org/) | CC BY 4.0 | 2,848 pathways, 9,988 reactions, protein complexes |
| [STRING v12.0](https://string-db.org/) | CC BY 4.0 | 227K high-confidence protein-protein interactions |
| [Gene Ontology](http://geneontology.org/) | OBO | 51K GO terms with IS_A/PART_OF/REGULATES hierarchy |
| [WikiPathways](https://www.wikipathways.org/) | CC0 | Community-curated pathway annotations |
| [UniProt](https://www.uniprot.org/) | CC BY 4.0 | Protein metadata, gene mappings, disease/drug associations |

## Quick Start

### Option 1: Load pre-built snapshot

```bash
# Download snapshot from release
curl -LO https://github.com/samyama-ai/samyama-graph/releases/download/kg-snapshots-v3/pathways.sgsnap

# Start Samyama Graph (v0.6.1+)
./target/release/samyama

# Create tenant and import
curl -X POST http://localhost:8080/api/tenants \
  -H 'Content-Type: application/json' \
  -d '{"id":"pathways","name":"Biological Pathways KG"}'

curl -X POST http://localhost:8080/api/tenants/pathways/snapshot/import \
  -F "file=@pathways.sgsnap"
```

### Option 2: Build from source data

```bash
# Install
pip install -e .

# Download all data sources (~1.9 GB)
python -m etl.download_data --data-dir data

# Load into Samyama (all 5 phases)
python -m etl.loader --data-dir data --url http://localhost:8080

# Or selectively
python -m etl.loader --data-dir data --phases reactome string go
```

## Example Queries

```cypher
-- Top pathways by protein count
MATCH (prot:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)
RETURN pw.name AS pathway, count(prot) AS proteins
ORDER BY proteins DESC LIMIT 10

-- PPI hub proteins (most interaction partners)
MATCH (p:Protein)-[:INTERACTS_WITH]-(other:Protein)
RETURN p.name AS protein, count(DISTINCT other) AS partners
ORDER BY partners DESC LIMIT 10

-- TP53 two-hop neighborhood
MATCH (tp53:Protein {name: 'TP53'})-[:INTERACTS_WITH]-(hop1:Protein)-[:INTERACTS_WITH]-(hop2:Protein)
WHERE hop2 <> tp53
RETURN DISTINCT hop2.name AS protein LIMIT 15

-- Pathway crosstalk (shared proteins)
MATCH (p1:Pathway)<-[:PARTICIPATES_IN]-(prot:Protein)-[:PARTICIPATES_IN]->(p2:Pathway)
WHERE p1.name < p2.name
WITH p1, p2, count(prot) AS shared WHERE shared >= 100
RETURN p1.name, p2.name, shared ORDER BY shared DESC LIMIT 10

-- Immune system sub-pathways
MATCH (child:Pathway)-[:CHILD_OF]->(parent:Pathway {name: 'Immune System'})
RETURN child.name AS sub_pathway ORDER BY child.name
```

## MCP Server (AI Agent Integration)

```bash
# Auto-generate MCP tools from the pathways schema
python -m mcp_server.server --url http://localhost:8080

# 12 domain-specific tools: pathway_members, interaction_partners,
# upstream_regulators, drug_pathway_impact, disease_pathways, etc.
```

## ETL Pipeline

Five phases, ordered by dependency:

1. **Reactome Core** — Pathways, proteins, reactions, complexes, hierarchy
2. **STRING Interactions** — High-confidence PPI network (score >= 700)
3. **Gene Ontology** — GO terms, IS_A/PART_OF/REGULATES hierarchy, annotations
4. **WikiPathways** — Community-curated pathways (deduplicated vs Reactome)
5. **UniProt Enrichment** — Gene mappings, disease/drug associations

## Tests

```bash
pip install -e ".[dev]"
pytest tests/
```

## License

Apache License 2.0
