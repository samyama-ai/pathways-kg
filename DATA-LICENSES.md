# Data licences

`LICENSE` in this repository covers the **loader code**. It says nothing about the
upstream data this repository reads and, where a snapshot is published, redistributes.
That gap is what this file closes (samyama-cloud#97).

Each row records what the source's **own terms page** says, with the URL and the date it
was read. Where a source could not be re-verified it says so rather than guessing: an
unverified licence written down as fact is worse than the silence it replaces.

| Source | What we load | What its terms page says | Checked |
|---|---|---|---|
| [Reactome](https://reactome.org/license) | Pathways, reactions, participants | CC0 — *All data in the Reactome database and files derived from that data are licensed under the Creative Commons Public Domain Dedication (CC0)*. Attribution encouraged, not required. | 2026-09-18 |
| [STRING v12.0](https://string-db.org/cgi/access) | Protein–protein associations | CC BY 4.0. Credit required, and users must be informed of changes or additions made to the data. Commercial use permitted. | 2026-09-18 |
| [Gene Ontology](https://geneontology.org/docs/go-citation-policy/) | Ontology terms and annotations | CC BY 4.0. The GO asks that the release date and DOI be cited so a result can be reproduced. | 2026-09-18 |
| [WikiPathways](https://www.wikipathways.org/terms.html) | Community pathways | CC0 waiver on pathway content. | 2026-09-18 |
| [UniProt](https://www.uniprot.org/help/license) | Protein entries | CC BY 4.0, attribution to the UniProt Consortium. | 2026-09-18 |

**The derived graph is redistributable under CC BY 4.0**, which is the strictest term
among the five: two sources are CC0 and three are CC BY 4.0. No source here is
non-commercial and none is share-alike, so a published snapshot needs attribution and
nothing more.

Attribution to carry with it: **Reactome**, **STRING v12.0**, **Gene Ontology** (with its
release date and DOI), **WikiPathways**, **UniProt Consortium**.

## How to read the "derived graph" line

A graph built from several sources carries **all** of their terms at once. The
restrictive ones win: one non-commercial source makes the join non-commercial, one
share-alike source makes the join share-alike. That is why the derived licence below is
not simply the most permissive source in the table.

## If you redistribute

- Keep the attributions named above with the data.
- State which snapshot version you took, so a reader can check it against the source.
- Re-read the terms pages: licences change, and the dates in this table are when we last
  looked.
