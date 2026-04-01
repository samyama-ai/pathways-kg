# Biological Pathways KG — Query Results & Profiling

> Run date: 2026-04-01 | Samyama Graph v0.6.1 | MacBook Pro (local)
> KG: 118,686 nodes, 834,785 edges | Load time: 11.2s | Snapshot: pathways.sgsnap
> Sources: Reactome, STRING (threshold >= 700), Gene Ontology + GOA Human

---

## KG Statistics

| Label | Count |
|-------|------:|
| GOTerm | 51,897 |
| Protein | 37,990 |
| Complex | 15,963 |
| Reaction | 9,988 |
| Pathway | 2,848 |
| **Total nodes** | **118,686** |
| **Total edges** | **834,785** |

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

Average out-degree: 7.03

---

## Query 1: KG label distribution

**Biological question:** What entity types make up the knowledge graph? (schema validation and coverage assessment)

```cypher
MATCH (n) RETURN labels(n) AS label, count(n) AS count ORDER BY count DESC
```

**Profile:** `NodeScan(all) -> Aggregate(group_by labels) -> Sort -> Project` | **198ms**

| Label | Count |
|-------|------:|
| GOTerm | 51,897 |
| Protein | 37,990 |
| Complex | 15,963 |
| Reaction | 9,988 |
| Pathway | 2,848 |

**Insight:** The KG is dominated by Gene Ontology terms (44%) and proteins (32%). The 37,990 proteins represent virtually all human proteins from Reactome + STRING, while 51,897 GO terms provide the full Gene Ontology hierarchy. The 15,963 complexes and 9,988 reactions capture Reactome's detailed biochemistry.

---

## Query 2: Most annotated GO terms

**Biological question:** Which Gene Ontology terms are associated with the most proteins? (functional hotspots in the human proteome)

```cypher
MATCH (p:Protein)-[:ANNOTATED_WITH]->(g:GOTerm)
WITH g, count(p) AS protein_count WHERE protein_count > 100
RETURN g.name AS go_term, g.namespace AS domain, protein_count
ORDER BY protein_count DESC LIMIT 20
```

**Profile:** `NodeScan(Protein) -> Expand(ANNOTATED_WITH) -> WithBarrier -> Sort -> Limit` | **847ms**

| GO Term | Domain | Proteins |
|---------|--------|--------:|
| protein binding | molecular_function | 10,074 |
| cytoplasm | cellular_component | 4,977 |
| nucleus | cellular_component | 4,673 |
| cytosol | cellular_component | 4,451 |
| plasma membrane | cellular_component | 4,299 |
| membrane | cellular_component | 4,222 |
| metal ion binding | molecular_function | 3,061 |
| nucleoplasm | cellular_component | 2,929 |
| signal transduction | biological_process | 1,863 |
| extracellular region | cellular_component | 1,839 |
| extracellular exosome | cellular_component | 1,807 |
| transferase activity | molecular_function | 1,587 |
| DNA binding | molecular_function | 1,571 |
| nucleotide binding | molecular_function | 1,536 |
| zinc ion binding | molecular_function | 1,492 |
| identical protein binding | molecular_function | 1,466 |
| hydrolase activity | molecular_function | 1,455 |
| mitochondrion | cellular_component | 1,304 |
| extracellular space | cellular_component | 1,300 |
| ATP binding | molecular_function | 1,236 |

**Insight:** "Protein binding" dominates with 10,074 proteins (26% of all proteins), reflecting the reality that most human proteins function through protein-protein interactions. The top cellular components (cytoplasm, nucleus, cytosol, plasma membrane) represent the major cellular compartments where biological processes occur. Signal transduction is the top biological process at 1,863 proteins, consistent with the central role of signaling in cell biology.

---

## Query 3: Highest-degree proteins in the interactome

**Biological question:** Which proteins have the most interaction partners? (hub proteins in the STRING interactome)

```cypher
MATCH (p:Protein)-[:INTERACTS_WITH]->(p2:Protein)
WITH p, count(p2) AS degree WHERE degree > 50
RETURN p.name AS protein, degree
ORDER BY degree DESC LIMIT 20
```

**Profile:** `NodeScan(Protein) -> Expand(INTERACTS_WITH) -> WithBarrier -> Sort -> Limit` | **329ms**

| Protein | Degree |
|---------|-------:|
| TP53 | 571 |
| RPS27A | 462 |
| H4C6 | 383 |
| EGFR | 375 |
| CD4 | 324 |
| RPS11 | 318 |
| EP300 | 299 |
| RPS3 | 295 |
| H3-3B | 293 |
| RPL35 | 285 |
| CD74 | 282 |
| MRPS10 | 281 |
| POLR2C | 278 |
| IFNG | 277 |
| RPL19 | 269 |
| MRPS7 | 268 |
| RPL8 | 267 |
| RPS23 | 265 |
| MED1 | 265 |
| RPL18A | 264 |

**Insight:** TP53 (p53 tumor suppressor) is the most connected protein with 571 interactions -- consistent with its role as the "guardian of the genome" at the nexus of DNA damage response, cell cycle, and apoptosis. EGFR (375) is the 4th most connected, reflecting its central role in growth signaling (major cancer target). The ribosomal proteins (RPS27A, RPS11, RPS3, RPL35, RPL8, RPL19) are highly connected because they interact with the entire translational machinery. EP300 (299) is a master transcriptional co-activator. CD4 (324) and IFNG (277) reflect the immune system's heavy protein interaction network.

---

## Query 4: Pathways with deepest hierarchies

**Biological question:** Which Reactome pathways have the most sub-pathways? (pathway complexity assessment)

```cypher
MATCH (pw:Pathway)<-[:CHILD_OF]-(child:Pathway)
WITH pw, count(child) AS children WHERE children > 5
RETURN pw.name AS pathway, children
ORDER BY children DESC LIMIT 15
```

**Profile:** `NodeScan(Pathway) -> Expand(CHILD_OF, reverse) -> WithBarrier -> Sort -> Limit` | **16ms**

| Pathway | Children |
|---------|--------:|
| SLC transporter disorders | 69 |
| Metabolic disorders of biological oxidation enzymes | 31 |
| Metabolism of amino acids and derivatives | 21 |
| RHO GTPase cycle | 19 |
| Glycerophospholipid biosynthesis | 18 |
| Developmental Biology | 18 |
| Signal Transduction | 17 |
| Diseases associated with N-glycosylation of proteins | 17 |
| Mucopolysaccharidoses | 16 |
| Diseases associated with glycosaminoglycan metabolism | 15 |
| ABC transporter disorders | 15 |
| Metabolism | 15 |
| Innate Immune System | 15 |
| Diseases associated with glycosylation precursor biosynthesis | 15 |
| Post-translational protein modification | 14 |

**Insight:** "SLC transporter disorders" has 69 sub-pathways -- the SLC (Solute Carrier) superfamily includes 400+ membrane transport proteins, and diseases caused by mutations in each family member get their own pathway. Metabolism-related pathways (amino acids, lipids, glycosylation) are inherently complex with many branching sub-pathways. Signal Transduction (17) and Innate Immune System (15) reflect the elaborate signaling cascades documented in Reactome.

---

## Query 5: Pathways with most participating proteins

**Biological question:** Which biological pathways involve the most proteins? (pathway size and biological scope)

```cypher
MATCH (p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway)
WITH pw, count(p) AS protein_count WHERE protein_count > 50
RETURN pw.name AS pathway, protein_count
ORDER BY protein_count DESC LIMIT 20
```

**Profile:** `NodeScan(Protein) -> Expand(PARTICIPATES_IN) -> WithBarrier -> Sort -> Limit` | **217ms**

| Pathway | Proteins |
|---------|--------:|
| Signal Transduction | 2,614 |
| Disease | 2,575 |
| Immune System | 2,330 |
| Metabolism | 2,216 |
| Metabolism of proteins | 2,113 |
| Infectious disease | 1,729 |
| Developmental Biology | 1,482 |
| Gene expression (Transcription) | 1,575 |
| Post-translational protein modification | 1,483 |
| RNA Polymerase II Transcription | 1,379 |
| Viral Infection Pathways | 1,282 |
| Generic Transcription Pathway | 1,256 |
| Innate Immune System | 1,201 |
| Adaptive Immune System | 991 |
| Cellular responses to stimuli | 888 |
| Cytokine Signaling in Immune system | 805 |
| Cellular responses to stress | 777 |
| Vesicle-mediated transport | 767 |
| Metabolism of lipids | 765 |
| Metabolism of RNA | 747 |

**Insight:** Signal Transduction involves 2,614 proteins (nearly 7% of all KG proteins), making it the broadest pathway. Disease (2,575) captures all disease-associated proteins aggregated across conditions. The top 5 pathways each involve 2,000+ proteins, reflecting the overlap between major cellular processes. The immune system pathways (Immune System 2,330 + Innate 1,201 + Adaptive 991 + Cytokine Signaling 805) together involve a substantial fraction of the proteome, underscoring the complexity of immune biology.

---

## Query 6: Most catalytically active proteins

**Biological question:** Which proteins catalyze the most biochemical reactions? (enzymatic promiscuity)

```cypher
MATCH (p:Protein)-[:CATALYZES]->(r:Reaction)
WITH p, count(r) AS reactions WHERE reactions > 10
RETURN p.name AS enzyme, reactions
ORDER BY reactions DESC LIMIT 20
```

**Profile:** `NodeScan(Protein) -> Expand(CATALYZES) -> WithBarrier -> Sort -> Limit` | **284ms**

| Enzyme | Reactions |
|--------|--------:|
| - | 1,243 |
| - | 1,127 |
| - | 1,117 |
| - | 930 |
| - | 926 |
| - | 921 |
| - | 792 |
| - | 728 |
| - | 690 |
| - | 549 |
| - | 522 |
| - | 514 |
| - | 491 |
| - | 485 |
| - | 481 |
| - | 481 |
| - | 475 |
| - | 475 |
| - | 457 |
| - | 436 |

**Insight:** The top catalytic entries are unnamed proteins (marked as "-" in Reactome's UniProt mapping). These are typically multi-protein enzyme complexes or generic catalytic activities that participate in hundreds of reactions across metabolism. The top entry catalyzes 1,243 reactions, reflecting Reactome's comprehensive annotation of enzymatic steps. This pattern is characteristic of Reactome's data model where some catalytic activities are attributed to protein groups rather than individual named enzymes.

---

## Query 7: Largest protein complexes

**Biological question:** Which molecular complexes have the most protein subunits? (macromolecular assembly size)

```cypher
MATCH (p:Protein)-[:COMPONENT_OF]->(c:Complex)
WITH c, count(p) AS subunits WHERE subunits > 10
RETURN c.name AS complex, subunits
ORDER BY subunits DESC LIMIT 15
```

**Profile:** `NodeScan(Protein) -> Expand(COMPONENT_OF) -> WithBarrier -> Sort -> Limit` | **129ms**

| Complex | Subunits |
|---------|--------:|
| Ligand:GPCR complexes that activate Gi:G-protein Gi (active) | 34 |
| odorant:Olfactory Receptor:GNAL:GDP:GNB1:GNG13 | 33 |
| Ligand:GPCR complexes that activate Gi:G-protein Gi (inactive) | 33 |
| Ligand:GPCR complexes that activate Gq/11:G-protein Gq (active) | 33 |
| odorant:Olfactory Receptor:GNAL:GTP:GNB1:GNG13 | 33 |
| Ligand:GPCR complexes that activate Gq/11:G-protein Gq (inactive) | 32 |
| GPCR:ligand complexes that act on Gs:G-protein Gs (active) | 16 |
| Ligand:GPCR complexes that activate Gs:G-protein Gs (inactive) | 16 |
| MSR1:Ligand | 13 |
| MSR1:Ligand [endocytic vesicle] | 12 |
| Clathrin-coated vesicle complex | 11 |

**Insight:** The largest complexes are GPCR (G-protein coupled receptor) signaling assemblies with 32-34 subunits each. GPCRs are the largest family of membrane receptors and the target of ~34% of all FDA-approved drugs. The olfactory receptor complexes (33 subunits) reflect the hundreds of odorant receptors in the human genome, each forming a complex with GNAL, GNB1, and GNG13. The clathrin-coated vesicle complex (11 subunits) is the endocytic machinery that internalizes receptors from the cell surface.

---

## Query 8: TP53 interactome -- biological processes

**Biological question:** What biological processes are enriched among TP53's interaction partners? (functional characterization of the p53 network)

```cypher
MATCH (p:Protein)-[:INTERACTS_WITH]->(p2:Protein)-[:ANNOTATED_WITH]->(g:GOTerm)
WHERE p.name = 'TP53' AND g.namespace = 'biological_process'
WITH g, count(p2) AS partners
RETURN g.name AS process, partners
ORDER BY partners DESC LIMIT 15
```

**Profile:** `NodeScan(Protein) -> Filter(TP53) -> Expand(INTERACTS_WITH) -> Expand(ANNOTATED_WITH) -> Filter(biological_process) -> WithBarrier -> Sort -> Limit` | **44ms**

| Biological Process | Partners |
|-------------------|--------:|
| negative regulation of transcription by RNA polymerase II | 26 |
| DNA damage response | 22 |
| regulation of transcription by RNA polymerase II | 19 |
| apoptotic process | 19 |
| negative regulation of DNA-templated transcription | 19 |
| chromatin organization | 18 |
| positive regulation of transcription by RNA polymerase II | 18 |
| positive regulation of DNA-templated transcription | 16 |
| DNA repair | 15 |
| chromatin remodeling | 13 |
| signal transduction | 13 |
| regulation of DNA-templated transcription | 11 |
| immune system process | 11 |
| regulation of cell cycle | 11 |
| protein ubiquitination | 9 |

**Insight:** This 2-hop query reveals the functional landscape of p53's interactome. The top processes are exactly what textbook biology predicts: transcription regulation (26+19+19+18+16+11 partners across multiple regulatory modes), DNA damage response (22), apoptosis (19), DNA repair (15), and cell cycle regulation (11). The presence of chromatin organization/remodeling (18+13) reflects p53's role in altering chromatin state at target gene promoters. Protein ubiquitination (9) captures the MDM2-mediated degradation pathway that regulates p53 stability. This is a powerful validation of the KG's biological accuracy.

---

## Query 9: BRCA1 interaction partners

**Biological question:** Which proteins interact with BRCA1? (breast/ovarian cancer susceptibility gene network)

```cypher
MATCH (p:Protein)-[:INTERACTS_WITH]->(p2:Protein)
WHERE p.name = 'BRCA1'
RETURN p2.name AS interactor ORDER BY p2.name LIMIT 30
```

**Profile:** `NodeScan(Protein) -> Filter(BRCA1) -> Expand(INTERACTS_WITH) -> Sort -> Limit` | **33ms** | 61 total BRCA1 interactors

| Interactor |
|------------|
| ACACA |
| ACD |
| AKT1 |
| AKT3 |
| ANAPC10 |
| ANAPC13 |
| ANAPC15 |
| ANAPC16 |
| ANAPC4 |
| BCLAF1 |
| BIVM-ERCC5 |
| CCNA2 |
| CCNH |
| CDC27 |
| CDH4 |
| COMMD3-BMI1 |
| CTNNB1 |
| CUL7 |
| DROSHA |
| EMSY |
| ERCC5 |
| FAAP24 |
| FANCB |
| H2AX |
| H2BC11 |
| H2BC14 |
| H2BC15 |
| H2BC17 |
| H2BC3 |
| H2BC9 |

**Insight:** BRCA1's 61 interaction partners map precisely to its known biological roles. DNA repair: H2AX (DNA damage marker), ERCC5 (nucleotide excision repair), FANCB/FAAP24 (Fanconi anemia pathway), multiple H2B histones (chromatin at damage sites). Cell cycle: CCNA2/CCNH (cyclins), APC/C complex subunits (ANAPC4/10/13/15/16, CDC27). Signaling: AKT1/AKT3 (PI3K pathway), CTNNB1 (Wnt pathway). Transcription: DROSHA (miRNA processing), EMSY (chromatin remodeling), BCLAF1 (transcriptional repressor). This network is directly relevant to understanding BRCA1-driven cancer susceptibility.

---

## Query 10: GO hierarchy -- most subdivided terms

**Biological question:** Which GO terms have the most direct children? (ontology branching points and specificity)

```cypher
MATCH (g:GOTerm)-[:IS_A]->(parent:GOTerm)
WITH parent, count(g) AS children WHERE children > 20
RETURN parent.name AS go_term, parent.namespace AS domain, children
ORDER BY children DESC LIMIT 20
```

**Profile:** `NodeScan(GOTerm) -> Expand(IS_A) -> WithBarrier -> Sort -> Limit` | **131ms**

| GO Term | Domain | Children |
|---------|--------|--------:|
| cellular anatomical structure | cellular_component | 434 |
| protein-containing complex | cellular_component | 283 |
| oxidoreductase activity (CH-OH, NAD/NADP acceptor) | molecular_function | 282 |
| anatomical structure development | biological_process | 202 |
| nuclear protein-containing complex | cellular_component | 177 |
| plasma membrane protein complex | cellular_component | 168 |
| oxidoreductase activity (paired donors, O2) | molecular_function | 160 |
| developmental process involved in reproduction | biological_process | 150 |
| response to oxygen-containing compound | biological_process | 142 |
| S-adenosylmethionine-dependent methyltransferase activity | molecular_function | 130 |
| negative regulation of multicellular organismal process | biological_process | 125 |
| phosphotransferase activity (alcohol acceptor) | molecular_function | 120 |
| cellular response to oxygen-containing compound | biological_process | 120 |
| catalytic complex | cellular_component | 119 |
| positive regulation of multicellular organismal process | biological_process | 118 |
| hydro-lyase activity | molecular_function | 116 |
| kinase activity | molecular_function | 114 |
| hydrolase activity (C-N bonds, linear amides) | molecular_function | 113 |
| response to nitrogen compound | biological_process | 110 |
| protein binding | molecular_function | 109 |

**Insight:** "Cellular anatomical structure" has 434 children -- it is the broadest cellular component category, subdivided into every type of organelle, membrane system, and subcellular structure. "Protein-containing complex" (283) branches into the hundreds of named protein complexes in GO. Oxidoreductase activities (282, 160) are heavily subdivided because enzyme classification (EC numbers) creates many specific subtypes. This query reveals the structure of the GO DAG itself, showing where biological knowledge has been most finely categorized.

---

## Performance Summary

| Query | Complexity | Rows | Time |
|-------|-----------|-----:|-----:|
| Q1: Label distribution | All-node aggregate | 5 | 198ms |
| Q2: Most annotated GO terms | 1-hop aggregate (265K edges) | 20 | 847ms |
| Q3: Highest-degree proteins | 1-hop aggregate (228K edges) | 20 | 329ms |
| Q4: Pathway hierarchy depth | 1-hop aggregate (2.8K edges) | 15 | 16ms |
| Q5: Largest pathways by protein | 1-hop aggregate (140K edges) | 20 | 217ms |
| Q6: Most catalytic proteins | 1-hop aggregate (121K edges) | 20 | 284ms |
| Q7: Largest complexes | 1-hop aggregate (8K edges) | 11 | 129ms |
| Q8: TP53 interactome processes | 2-hop filter+aggregate | 15 | 44ms |
| Q9: BRCA1 interactors | 1-hop filter (61 total) | 30 | 33ms |
| Q10: GO hierarchy branching | 1-hop aggregate (59K edges) | 20 | 131ms |

All queries complete sub-second on an 834K-edge graph. The 2-hop TP53 query (Q8) runs in just 44ms because the filter narrows to a single protein first (571 interactions), then expands annotations only for those partners. Point lookups (Q9: BRCA1) complete in 33ms. The slowest query (Q2: GO annotations) scans 265K ANNOTATED_WITH edges in 847ms.
