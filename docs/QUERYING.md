# Querying the Pathways KG

Three ways to ask the graph questions, once it's loaded into the `pathways` tenant on a running engine
(see [GETTING_STARTED.md](../GETTING_STARTED.md)). All examples below were run live and return real results.

---

## 1. Claude, over MCP (natural language)

```bash
# register this KG's MCP server with Claude Code (once), pointed at the running engine:
claude mcp add pathways -- python -m mcp_server.server --url http://localhost:8080 --graph pathways

# start a new Claude Code session (MCP servers load at session start), then just ask:
#   "which protein has the most interaction partners?"    → TP53 (739)
#   "which top-level pathways contain the most proteins?"  → Signal Transduction (2614)
```

*(No engine? `python -m mcp_server.server --data-dir data` loads a graph in-memory and serves it.)*

## 2. HTTP API (`POST /api/query`)

```bash
curl -s -X POST http://localhost:8080/api/query -H 'Content-Type: application/json' -d '{
  "graph": "pathways",
  "query": "MATCH (p:Protein)-[:PARTICIPATES_IN]->(pw:Pathway) RETURN pw.name AS pathway, count(p) AS proteins ORDER BY proteins DESC LIMIT 3"
}'
```
```json
{"columns":["pathway","proteins"],
 "records":[["Signal Transduction",2614],["Disease",2575],["Immune System",2330]]}
```

## 3. Samyama CLI (Redis wire protocol, `:6379`)

```bash
redis-cli -p 6379 GRAPH.QUERY pathways \
  "MATCH (p:Protein)-[:ANNOTATED_WITH]->(go:GOTerm) RETURN go.name, count(p) AS proteins ORDER BY proteins DESC LIMIT 3"
# 1) "protein binding" 10074
# 2) "cytoplasm"        4977
# 3) "nucleus"          4673
```

---

## More queries
See the [Biomedical Benchmark](https://samyama-ai.github.io/samyama-graph-book/biomedical_benchmark.html)
for 100 example queries, and the [schema](../README.md#schema) for the node/edge model.
