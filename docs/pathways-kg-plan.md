# Pathways Knowledge Graph — Implementation Plan

**Created:** 2026-03-16
**Status:** Planning
**Template:** cricket-kg pattern (ETL loader + MCP server + tests)

---

## 1. Why a Pathways KG?

Biological pathways describe how genes, proteins, and metabolites interact to carry out cellular functions. Traditional relational databases struggle with multi-hop pathway queries (e.g., "What upstream regulators affect gene X through at most 3 intermediate reactions?"). A graph database makes these queries natural:

| Question | SQL | Cypher |
|----------|-----|--------|
| Find all proteins in a pathway | 3-table JOIN | `MATCH (p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)` |
| Upstream regulators (3 hops) | Recursive CTE or multiple self-joins | `MATCH (r)-[:REGULATES*1..3]->(p:Protein {name:'TP53'})` |
| Shared pathway membership | Subquery + GROUP BY | `MATCH (a:Protein)-[:PARTICIPATES_IN]->(pw)<-[:PARTICIPATES_IN]-(b:Protein)` |
| Drug → target → pathway → disease | 4-table JOIN | `MATCH (d:Drug)-[:TARGETS]->(p)-[:PARTICIPATES_IN]->(pw)-[:ASSOCIATED_WITH]->(dis:Disease)` |

**Target users:** Bioinformaticians, drug discovery teams, systems biologists, clinical researchers.

---

## 2. Data Sources (All Free & Open)

KEGG has restrictive licensing (no bulk download, no redistribution). We use open alternatives that collectively exceed KEGG's coverage:

| Source | License | Content | Format | Role in KG |
|--------|---------|---------|--------|------------|
| **Reactome** | CC BY 4.0 | 2,825 human pathways, 16K reactions, 32K proteins | Neo4j dump, BioPAX, TSV | Core pathways & reactions |
| **STRING** | CC BY 4.0 | 59.3M proteins, 20B+ interactions (human subset: ~20K proteins, ~6M interactions) | TSV edge-list | Protein-protein interactions |
| **Gene Ontology** | Open (OBO) | 47K GO terms, 1.1M annotations | OBO/JSON, GAF | Functional annotations |
| **WikiPathways** | CC0 (public domain) | 1,913 curated pathways, 85K interactions | GPML, JSON, GMT | Community pathways (supplement Reactome) |
| **UniProt** | CC BY 4.0 | 573K reviewed proteins, cross-refs to all above | TSV, JSON | Protein metadata & cross-linking hub |

### Download URLs

| Source | URL | Size (human-only) |
|--------|-----|-------------------|
| Reactome | `https://reactome.org/download/current/` | ~500 MB (Neo4j dump) |
| Reactome TSV | `https://reactome.org/download/current/UniProt2Reactome_All_Levels.txt` | ~50 MB |
| Reactome interactions | `https://reactome.org/download/current/interactors/reactome.homo_sapiens.interactions.tab-delimited.txt` | ~10 MB |
| STRING (human) | `https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz` | ~200 MB compressed |
| STRING info | `https://stringdb-downloads.org/download/protein.info.v12.0/9606.protein.info.v12.0.txt.gz` | ~5 MB |
| GO ontology | `https://release.geneontology.org/2026-03-01/ontology/go.json.gz` | ~30 MB |
| GO annotations (human) | `http://geneontology.org/gene-associations/goa_human.gaf.gz` | ~15 MB |
| WikiPathways (human) | `https://data.wikipathways.org/current/gmt/wikipathways-YYYYMMDD-gmt-Homo_sapiens.gmt` | ~1 MB |
| WikiPathways GPML | `https://data.wikipathways.org/current/gpml/wikipathways-YYYYMMDD-gpml-Homo_sapiens.zip` | ~50 MB |
| UniProt (human reviewed) | `https://rest.uniprot.org/uniprotkb/stream?query=(organism_id:9606)+AND+(reviewed:true)&format=tsv` | ~100 MB |

**Total download:** ~1 GB (human-only). Manageable for Mac Mini.

---

## 3. Graph Schema

### Node Labels (9)

| Label | Key Properties | Source | Est. Count |
|-------|---------------|--------|------------|
| **Pathway** | reactome_id (indexed), wp_id, name, organism, source, description | Reactome, WikiPathways | ~4,000 |
| **Reaction** | reactome_id (indexed), name, equation, reversible | Reactome | ~16,000 |
| **Protein** | uniprot_id (indexed), name, gene_name, organism, sequence_length | UniProt, Reactome | ~25,000 |
| **Gene** | gene_id (indexed), symbol, name, chromosome, organism | UniProt (cross-ref) | ~20,000 |
| **Compound** | chebi_id (indexed), name, formula, molecular_weight | Reactome | ~2,500 |
| **Complex** | reactome_id (indexed), name, description | Reactome | ~15,000 |
| **Disease** | disease_id, name, description, source | Reactome, UniProt | ~3,000 |
| **GOTerm** | go_id (indexed), name, namespace, definition | Gene Ontology | ~47,000 |
| **Drug** | drugbank_id, name, mechanism | UniProt (cross-ref) | ~1,500 |

**Estimated total nodes: ~134,000**

### Edge Types (15)

| Edge | From → To | Properties | Source | Est. Count |
|------|-----------|-----------|--------|------------|
| **PARTICIPATES_IN** | Protein → Pathway | role (input/output/catalyst) | Reactome | ~100,000 |
| **CATALYZES** | Protein → Reaction | | Reactome | ~20,000 |
| **INPUT_OF** | Compound/Protein → Reaction | stoichiometry | Reactome | ~40,000 |
| **OUTPUT_OF** | Reaction → Compound/Protein | stoichiometry | Reactome | ~40,000 |
| **HAS_EVENT** | Pathway → Reaction | order | Reactome | ~30,000 |
| **CHILD_OF** | Pathway → Pathway | | Reactome | ~4,000 |
| **INTERACTS_WITH** | Protein ↔ Protein | combined_score, experimental_score, textmining_score | STRING | ~600,000 |
| **IS_A** | GOTerm → GOTerm | | Gene Ontology | ~70,000 |
| **PART_OF** | GOTerm → GOTerm | | Gene Ontology | ~10,000 |
| **ANNOTATED_WITH** | Protein → GOTerm | evidence_code, qualifier | GO annotations | ~300,000 |
| **REGULATES** | GOTerm → GOTerm | direction (positive/negative) | Gene Ontology | ~8,000 |
| **ENCODES** | Gene → Protein | | UniProt | ~20,000 |
| **COMPONENT_OF** | Protein → Complex | | Reactome | ~50,000 |
| **ASSOCIATED_WITH** | Gene/Protein → Disease | evidence | Reactome, UniProt | ~15,000 |
| **TARGETS** | Drug → Protein | mechanism | UniProt | ~5,000 |

**Estimated total edges: ~1,312,000**

### Schema Diagram

```
                    ┌─────────┐
         IS_A ───→ │ GOTerm  │ ←── PART_OF / REGULATES
                    └────┬────┘
                         │ ANNOTATED_WITH
                         ▼
┌──────┐  ENCODES  ┌──────────┐  PARTICIPATES_IN  ┌──────────┐  HAS_EVENT  ┌──────────┐
│ Gene │ ────────→ │ Protein  │ ─────────────────→ │ Pathway  │ ──────────→ │ Reaction │
└──┬───┘           └──┬──┬──┬─┘                    └──┬───────┘            └──┬───┬────┘
   │                  │  │  │  INTERACTS_WITH          │ CHILD_OF             │   │
   │ ASSOCIATED_WITH  │  │  └──────────────────┐       └──→ Pathway           │   │
   │                  │  │                     ▼                              │   │
   ▼                  │  │  COMPONENT_OF   ┌─────────┐       INPUT_OF        │   │
┌─────────┐           │  └───────────────→ │ Complex │   ┌───────────────────┘   │
│ Disease │ ←─────────┘                    └─────────┘   ▼              OUTPUT_OF│
└─────────┘                                         ┌──────────┐                 │
    ▲                                                │ Compound │ ←──────────────┘
    │  TREATS                                        └──────────┘
┌───┴──┐  TARGETS
│ Drug │ ────────→ Protein
└──────┘
```

---

## 4. ETL Pipeline Design

### Phase 1: Reactome Core (P0)

**File: `etl/reactome_loader.py`**

```
Download → Parse → Create Nodes → Create Edges → Index
```

**Steps:**
1. Download Reactome TSV files (UniProt2Reactome, interactions, NCBI2Reactome)
2. Parse `UniProt2Reactome_All_Levels.txt` → Pathway + Protein nodes, PARTICIPATES_IN edges
3. Parse `reactome.homo_sapiens.interactions.tab-delimited.txt` → Reaction nodes, CATALYZES/INPUT/OUTPUT edges
4. Download Reactome pathway hierarchy → CHILD_OF edges
5. Parse `ComplexParticipantsPubMedIdentifiers_human.txt` → Complex nodes, COMPONENT_OF edges
6. Create indexes on all indexed properties

**Estimated: ~50K nodes, ~280K edges**

### Phase 2: STRING Interactions (P0)

**File: `etl/string_loader.py`**

**Steps:**
1. Download `9606.protein.links.v12.0.txt.gz` (human)
2. Download `9606.protein.info.v12.0.txt.gz` (protein names/descriptions)
3. Filter interactions by `combined_score >= 700` (high confidence)
4. Map STRING protein IDs (ENSP) → UniProt IDs via `9606.protein.aliases.v12.0.txt.gz`
5. Create INTERACTS_WITH edges with score properties (combined, experimental, textmining)
6. MERGE existing Protein nodes (add STRING ID as property), CREATE new ones

**Estimated: ~20K protein nodes (MERGE), ~600K edges**

### Phase 3: Gene Ontology (P1)

**File: `etl/go_loader.py`**

**Steps:**
1. Download `go.json.gz` (ontology structure)
2. Parse JSON → GOTerm nodes with IS_A, PART_OF, REGULATES edges (DAG hierarchy)
3. Download `goa_human.gaf.gz` (human annotations)
4. Parse GAF → ANNOTATED_WITH edges (Protein → GOTerm) with evidence codes
5. Filter out IEA (Inferred from Electronic Annotation) if high-confidence mode

**Estimated: ~47K GOTerm nodes, ~380K edges**

### Phase 4: WikiPathways (P1)

**File: `etl/wikipathways_loader.py`**

**Steps:**
1. Download human GMT file (gene-pathway mapping)
2. Download GPML files (detailed pathway structure with interactions)
3. Create Pathway nodes (wp_id, name) — skip duplicates already in Reactome
4. Parse GPML for DataNodes (genes/proteins/metabolites) and Interactions
5. Create PARTICIPATES_IN edges linking existing proteins to WikiPathways pathways
6. Parse Interaction elements for regulatory/conversion/binding edges

**Estimated: ~1K new Pathway nodes, ~40K edges**

### Phase 5: UniProt Enrichment (P2)

**File: `etl/uniprot_loader.py`**

**Steps:**
1. Stream human reviewed proteins from UniProt REST API (TSV format)
2. Enrich existing Protein nodes with: gene_name, organism, sequence_length, function_description
3. Create Gene nodes from gene_id cross-references → ENCODES edges
4. Extract disease annotations → Disease nodes + ASSOCIATED_WITH edges
5. Extract drug target annotations → Drug nodes + TARGETS edges

**Estimated: ~25K enriched proteins, ~20K Gene nodes, ~20K new edges**

### Main Loader (`etl/loader.py`)

Orchestrates all phases with flags:

```python
load_pathways(
    client: SamyamaClient,
    data_dir: str = "data",
    phases: list[str] = ["reactome", "string", "go", "wikipathways", "uniprot"],
    organism: str = "human",          # Filter organism
    string_threshold: int = 700,      # Min STRING confidence score
    go_exclude_iea: bool = False,     # Exclude electronic annotations
    max_proteins: int = 0,            # 0 = all
) → dict
```

CLI:
```bash
python -m etl.loader --data-dir data --phases reactome string go
python -m etl.loader --data-dir data --organism human --string-threshold 900
python -m etl.loader --data-dir data  # All phases, all data
```

### Download Script (`etl/download_data.py`)

Separate script to fetch all data files:

```bash
python -m etl.download_data --data-dir data --organism human
```

Downloads all files listed in §2 with progress bars, checksums, and resume support.

---

## 5. MCP Server Configuration

### Auto-Generated Tools (from schema)
- 9 node query tools (one per label)
- 30 edge query tools (2 per edge type: find by source, find by target)
- Algorithm tools: PageRank, WCC, SCC, BFS, Dijkstra
- Vector tools (if embeddings added later)

### Custom Tools (12 domain-specific)

```yaml
custom_tools:
  - name: pathway_members
    description: "All proteins participating in a pathway"
    cypher_template: >
      MATCH (p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)
      WHERE pw.name CONTAINS '{pathway_name}'
      RETURN p.uniprot_id, p.name, p.gene_name
      ORDER BY p.gene_name LIMIT {limit}

  - name: protein_pathways
    description: "All pathways a protein participates in"
    cypher_template: >
      MATCH (p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)
      WHERE p.gene_name = '{gene_name}' OR p.name CONTAINS '{gene_name}'
      RETURN pw.name, pw.source, pw.reactome_id

  - name: interaction_partners
    description: "Protein-protein interaction partners above confidence threshold"
    cypher_template: >
      MATCH (p1:Protein)-[i:INTERACTS_WITH]-(p2:Protein)
      WHERE p1.gene_name = '{gene_name}' AND i.combined_score >= {min_score}
      RETURN p2.gene_name, p2.name, i.combined_score
      ORDER BY i.combined_score DESC LIMIT {limit}

  - name: shared_pathways
    description: "Pathways shared between two proteins"
    cypher_template: >
      MATCH (a:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)<-[:PARTICIPATES_IN]-(b:Protein)
      WHERE a.gene_name = '{gene1}' AND b.gene_name = '{gene2}'
      RETURN pw.name, pw.source

  - name: upstream_regulators
    description: "Upstream regulators of a protein within N hops"
    cypher_template: >
      MATCH path = (r:Protein)-[:REGULATES|INTERACTS_WITH*1..{max_hops}]->(p:Protein)
      WHERE p.gene_name = '{gene_name}'
      RETURN DISTINCT r.gene_name, r.name, length(path) AS hops
      ORDER BY hops LIMIT {limit}

  - name: pathway_crosstalk
    description: "Find pathways connected through shared proteins"
    cypher_template: >
      MATCH (pw1:Pathway)<-[:PARTICIPATES_IN]-(p:Protein)-[:PARTICIPATES_IN]->(pw2:Pathway)
      WHERE pw1.name CONTAINS '{pathway1}' AND pw2.name <> pw1.name
      RETURN pw2.name AS connected_pathway, count(p) AS shared_proteins
      ORDER BY shared_proteins DESC LIMIT {limit}

  - name: drug_pathway_impact
    description: "Pathways impacted by a drug through its protein targets"
    cypher_template: >
      MATCH (d:Drug)-[:TARGETS]->(p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)
      WHERE d.name CONTAINS '{drug_name}'
      RETURN pw.name, collect(p.gene_name) AS targeted_genes
      ORDER BY size(collect(p.gene_name)) DESC

  - name: disease_pathways
    description: "Pathways associated with a disease"
    cypher_template: >
      MATCH (dis:Disease)<-[:ASSOCIATED_WITH]-(g)-[:ENCODES|PARTICIPATES_IN*1..2]->(pw:Pathway)
      WHERE dis.name CONTAINS '{disease_name}'
      RETURN DISTINCT pw.name, count(*) AS gene_count
      ORDER BY gene_count DESC LIMIT {limit}

  - name: go_enrichment
    description: "GO terms enriched for proteins in a pathway"
    cypher_template: >
      MATCH (p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)
      WHERE pw.name CONTAINS '{pathway_name}'
      MATCH (p)-[:ANNOTATED_WITH]->(go:GOTerm)
      WHERE go.namespace = '{namespace}'
      RETURN go.go_id, go.name, count(p) AS protein_count
      ORDER BY protein_count DESC LIMIT {limit}

  - name: reaction_details
    description: "Inputs, outputs, and catalysts of a reaction"
    cypher_template: >
      MATCH (r:Reaction) WHERE r.name CONTAINS '{reaction_name}'
      OPTIONAL MATCH (inp)-[:INPUT_OF]->(r)
      OPTIONAL MATCH (r)-[:OUTPUT_OF]->(outp)
      OPTIONAL MATCH (cat)-[:CATALYZES]->(r)
      RETURN r.name, collect(DISTINCT inp.name) AS inputs,
             collect(DISTINCT outp.name) AS outputs,
             collect(DISTINCT cat.gene_name) AS catalysts

  - name: protein_function_summary
    description: "Complete functional profile of a protein: GO terms, pathways, interactions, diseases"
    cypher_template: >
      MATCH (p:Protein) WHERE p.gene_name = '{gene_name}'
      OPTIONAL MATCH (p)-[:PARTICIPATES_IN]->(pw:Pathway)
      OPTIONAL MATCH (p)-[:ANNOTATED_WITH]->(go:GOTerm {namespace: 'biological_process'})
      OPTIONAL MATCH (p)-[:ASSOCIATED_WITH]->(dis:Disease)
      RETURN p.name, p.gene_name,
             collect(DISTINCT pw.name)[0..5] AS top_pathways,
             collect(DISTINCT go.name)[0..5] AS top_processes,
             collect(DISTINCT dis.name) AS diseases

  - name: pathway_hierarchy
    description: "Sub-pathways and parent pathways in the hierarchy"
    cypher_template: >
      MATCH (pw:Pathway) WHERE pw.name CONTAINS '{pathway_name}'
      OPTIONAL MATCH (pw)-[:CHILD_OF]->(parent:Pathway)
      OPTIONAL MATCH (child:Pathway)-[:CHILD_OF]->(pw)
      RETURN pw.name,
             collect(DISTINCT parent.name) AS parent_pathways,
             collect(DISTINCT child.name) AS sub_pathways
```

---

## 6. Test Plan

**File: `tests/test_reactome_loader.py`** (per-phase test files)

Follow cricket-kg pattern: fixture with sample data, query helper, test classes per node/edge type.

### Fixtures
- `SAMPLE_PATHWAY_TSV` — 5 pathway entries from UniProt2Reactome
- `SAMPLE_INTERACTION_TSV` — 10 protein-protein interactions
- `SAMPLE_GO_JSON` — 20 GO terms with hierarchy
- `SAMPLE_GAF` — 30 annotations

### Test Classes (~30 tests total)
- `TestPathwayLoading` — Pathway nodes created, properties correct
- `TestProteinLoading` — Protein nodes with uniprot_id, gene_name
- `TestReactionLoading` — Reaction nodes, INPUT_OF/OUTPUT_OF edges
- `TestComplexLoading` — Complex nodes, COMPONENT_OF edges
- `TestStringInteractions` — INTERACTS_WITH edges with scores, threshold filter
- `TestGOLoading` — GOTerm nodes, IS_A/PART_OF hierarchy
- `TestAnnotations` — ANNOTATED_WITH edges with evidence codes
- `TestWikiPathways` — WikiPathways nodes, dedup against Reactome
- `TestUniProtEnrichment` — Gene nodes, ENCODES edges, Disease associations
- `TestMultiHop` — Cross-source traversals (protein → pathway → disease)
- `TestMCPTools` — All 12 custom tools return valid results

---

## 7. Project Structure

```
pathways-kg/
├── etl/
│   ├── __init__.py
│   ├── loader.py              # Main orchestrator (~200 lines)
│   ├── download_data.py       # Data downloader with checksums (~250 lines)
│   ├── reactome_loader.py     # Phase 1: Reactome (~400 lines)
│   ├── string_loader.py       # Phase 2: STRING (~250 lines)
│   ├── go_loader.py           # Phase 3: Gene Ontology (~300 lines)
│   ├── wikipathways_loader.py # Phase 4: WikiPathways (~200 lines)
│   └── uniprot_loader.py      # Phase 5: UniProt (~250 lines)
│
├── mcp_server/
│   ├── __init__.py
│   ├── config.yaml            # 12 custom tools + auto-gen flags
│   └── server.py              # MCP server entry point
│
├── tests/
│   ├── __init__.py
│   ├── test_reactome_loader.py
│   ├── test_string_loader.py
│   ├── test_go_loader.py
│   ├── test_wikipathways_loader.py
│   ├── test_uniprot_loader.py
│   └── test_mcp_server.py
│
├── scripts/
│   ├── run_queries.py         # Showcase queries
│   └── validate_schema.py     # Schema consistency checks
│
├── docs/
│   ├── pathways-kg-plan.md    # This document
│   └── 100-queries.md         # Progressive query guide
│
├── data/                      # Downloaded data (gitignored)
│   ├── reactome/
│   ├── string/
│   ├── go/
│   ├── wikipathways/
│   └── uniprot/
│
├── schema/                    # Schema documentation
│   └── graph-schema.md
│
├── pyproject.toml
├── README.md
└── .gitignore
```

---

## 8. Implementation Timeline

| Phase | What | Effort | Depends On |
|-------|------|--------|------------|
| **P0** | Download script + Reactome loader + tests | L (5 days) | — |
| **P0** | STRING loader + tests | M (2 days) | P0a (protein nodes exist) |
| **P1** | GO loader + tests | M (2 days) | P0a (protein nodes for annotations) |
| **P1** | WikiPathways loader + tests | M (2 days) | P0a (dedup against Reactome) |
| **P2** | UniProt enrichment + tests | M (2 days) | P0a (protein nodes to enrich) |
| **P1** | MCP config + server + tests | M (2 days) | P0a+b (graph loaded) |
| **P1** | README + 100 queries + docs | M (2 days) | All phases |
| **P2** | Snapshot + registry publish | S (1 day) | SK-18, SK-19 |

**Total estimated effort: ~3 weeks**

---

## 9. Backlog Items (for BACKLOG.md §16)

```
KG-05 | pathways-kg: Download script + Reactome core loader | P1 | ⚪ | L
KG-06 | pathways-kg: STRING interaction loader              | P1 | ⚪ | M
KG-07 | pathways-kg: Gene Ontology loader                   | P1 | ⚪ | M
KG-08 | pathways-kg: WikiPathways loader                    | P2 | ⚪ | M
KG-09 | pathways-kg: UniProt enrichment loader              | P2 | ⚪ | M
KG-10 | pathways-kg: MCP server + custom tools              | P1 | ⚪ | M
KG-11 | pathways-kg: README + 100-queries doc               | P2 | ⚪ | M
KG-12 | pathways-kg: Snapshot + registry publish             | P2 | ⚪ | S
```

---

## 10. Key Design Decisions

1. **No KEGG dependency** — KEGG licensing prohibits bulk download and redistribution. Reactome + WikiPathways + STRING provide equivalent or better coverage with open licenses.

2. **Human-only first** — Start with Homo sapiens (organism ID 9606) to keep scope manageable. Multi-organism support (mouse, rat, zebrafish) as Phase 2.

3. **STRING threshold 700** — STRING scores range 0–999. Score ≥ 700 = "high confidence." This filters ~6M raw edges to ~600K, keeping the graph focused. Configurable via CLI.

4. **UniProt as the identity hub** — All protein nodes keyed by UniProt accession (e.g., P04637 for TP53). STRING IDs, Reactome IDs, and gene symbols cross-reference into UniProt. This prevents duplicate protein nodes across sources.

5. **Phase-ordered loading** — Reactome first (creates protein backbone), then STRING (adds interaction edges to existing proteins), then GO (annotations), WikiPathways (supplementary pathways), UniProt (enrichment). Later phases MERGE onto existing nodes rather than creating duplicates.

6. **Follow cricket-kg patterns exactly** — Registry-based dedup, batch Cypher, index-first, error resilience, progress reporting. This ensures consistency across KG projects and compatibility with samyama-mcp-serve.
