---
license: cc-by-4.0
pretty_name: Pathways Knowledge Graph
tags:
  - knowledge-graph
  - samyama
  - property-graph
  - biology
language:
  - en
size_categories:
  - 100K<n<1M
---

# Dataset Card for `pathways-kg`

**119K nodes. 835K edges. Every human biological pathway, protein interaction, and GO annotation in one graph.**

> Part of the **Samyama** ecosystem. This card describes the dataset; the repository
> holds the loader and source-data specifics.

## Structure

**5 node labels** -- Protein (37,990), GOTerm (51,897), Complex (15,963), Reaction (9,988), Pathway (2,848)

**9 edge types** -- ANNOTATED_WITH (265K), INTERACTS_WITH (228K), PARTICIPATES_IN (140K), CATALYZES (121K), IS_A (59K), COMPONENT_OF (8K), PART_OF (7K), REGULATES (3K), CHILD_OF (3K)

**5 data sources** -- Reactome, STRING v12.0, Gene Ontology, WikiPathways, UniProt (all human, organism 9606)

## Provenance and licence

Apache 2.0 covers the loader. The five sources are CC0 (Reactome, WikiPathways) and
CC BY 4.0 (STRING v12.0, Gene Ontology, UniProt), so **the derived graph is redistributable
under CC BY 4.0** with attribution to all five. See [`DATA-LICENSES.md`](DATA-LICENSES.md).


## Reproducing

The loader in this repository rebuilds the graph from the upstream source. See the
README's Quick Start for the snapshot download and the from-source build.

## Known limitations

- Counts here are those stated by the repository README at the time this card was
  written; they are not re-measured by the card.
- Where a field above says *not recorded*, that is a gap in this repository rather
  than a property of the data.

## Links

| | |
|---|---|
| Samyama Graph | [github.com/samyama-ai/samyama-graph](https://github.com/samyama-ai/samyama-graph) |
| The Book | [samyama-ai.github.io/samyama-graph-book](https://samyama-ai.github.io/samyama-graph-book/) |
| Benchmark (100 queries) | [Biomedical Benchmark](https://samyama-ai.github.io/samyama-graph-book/biomedical_benchmark.html) |
| Contact | [samyama.dev/contact](https://samyama.dev/contact) |
