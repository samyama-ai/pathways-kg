#!/bin/bash
# Run curated real-world queries against the Biological Pathways KG
# Usage: ./benchmarks/run_queries.sh [--data-dir PATH]
#
# Loads data from --data-dir (default: ../data), runs 10 PROFILE queries,
# captures results to benchmarks/query_results.txt

set -euo pipefail
export PATH="$HOME/.cargo/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SG_DIR="$(dirname "$REPO_DIR")/samyama-graph"
DATA_DIR="${1:-$REPO_DIR/data}"
OUTPUT="$SCRIPT_DIR/query_results.txt"

echo "=== Biological Pathways KG — Query Benchmark ==="
echo "Data dir:   $DATA_DIR"
echo "Output:     $OUTPUT"
echo "Samyama:    $SG_DIR"
echo ""

cd "$SG_DIR"

cargo run --release --example pathways_loader -- \
  --data-dir "$DATA_DIR" \
  --query << 'QUERIES' 2>&1 | tee "$OUTPUT"
PROFILE MATCH (n) RETURN labels(n) AS label, count(n) AS count ORDER BY count DESC
PROFILE MATCH (p:Protein)-[:ANNOTATED_WITH]->(g:GOTerm) WITH g, count(p) AS protein_count WHERE protein_count > 100 RETURN g.name AS go_term, g.namespace AS domain, protein_count ORDER BY protein_count DESC LIMIT 20
PROFILE MATCH (p:Protein)-[:INTERACTS_WITH]->(p2:Protein) WITH p, count(p2) AS degree WHERE degree > 50 RETURN p.name AS protein, degree ORDER BY degree DESC LIMIT 20
PROFILE MATCH (pw:Pathway)<-[:CHILD_OF]-(child:Pathway) WITH pw, count(child) AS children WHERE children > 5 RETURN pw.name AS pathway, children ORDER BY children DESC LIMIT 15
PROFILE MATCH (p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway) WITH pw, count(p) AS protein_count WHERE protein_count > 50 RETURN pw.name AS pathway, protein_count ORDER BY protein_count DESC LIMIT 20
PROFILE MATCH (p:Protein)-[:CATALYZES]->(r:Reaction) WITH p, count(r) AS reactions WHERE reactions > 10 RETURN p.name AS enzyme, reactions ORDER BY reactions DESC LIMIT 20
PROFILE MATCH (p:Protein)-[:COMPONENT_OF]->(c:Complex) WITH c, count(p) AS subunits WHERE subunits > 10 RETURN c.name AS complex, subunits ORDER BY subunits DESC LIMIT 15
PROFILE MATCH (p:Protein)-[:INTERACTS_WITH]->(p2:Protein)-[:ANNOTATED_WITH]->(g:GOTerm) WHERE p.name = 'TP53' AND g.namespace = 'biological_process' WITH g, count(p2) AS partners RETURN g.name AS process, partners ORDER BY partners DESC LIMIT 15
PROFILE MATCH (p:Protein)-[:INTERACTS_WITH]->(p2:Protein) WHERE p.name = 'BRCA1' RETURN p2.name AS interactor ORDER BY p2.name LIMIT 30
PROFILE MATCH (g:GOTerm)-[:IS_A]->(parent:GOTerm) WITH parent, count(g) AS children WHERE children > 20 RETURN parent.name AS go_term, parent.namespace AS domain, children ORDER BY children DESC LIMIT 20
exit
QUERIES

echo ""
echo "Results saved to $OUTPUT"
