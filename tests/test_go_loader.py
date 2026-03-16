"""Tests for Gene Ontology loader."""

import json
import os
import tempfile
import pytest


SAMPLE_GO_JSON = {
    "graphs": [
        {
            "nodes": [
                {
                    "id": "http://purl.obolibrary.org/obo/GO_0008150",
                    "lbl": "biological_process",
                    "meta": {
                        "definition": {"val": "A biological process is a recognized series of events."},
                        "basicPropertyValues": [
                            {
                                "pred": "http://www.geneontology.org/formats/oboInOwl#hasOBONamespace",
                                "val": "biological_process",
                            }
                        ],
                    },
                },
                {
                    "id": "http://purl.obolibrary.org/obo/GO_0006915",
                    "lbl": "apoptotic process",
                    "meta": {
                        "definition": {"val": "A programmed cell death process."},
                        "basicPropertyValues": [
                            {
                                "pred": "http://www.geneontology.org/formats/oboInOwl#hasOBONamespace",
                                "val": "biological_process",
                            }
                        ],
                    },
                },
                {
                    "id": "http://purl.obolibrary.org/obo/GO_0003677",
                    "lbl": "DNA binding",
                    "meta": {
                        "definition": {"val": "Binding to DNA."},
                        "basicPropertyValues": [
                            {
                                "pred": "http://www.geneontology.org/formats/oboInOwl#hasOBONamespace",
                                "val": "molecular_function",
                            }
                        ],
                    },
                },
                {
                    "id": "http://purl.obolibrary.org/obo/GO_0005634",
                    "lbl": "nucleus",
                    "meta": {
                        "definition": {"val": "A membrane-bounded organelle."},
                        "basicPropertyValues": [
                            {
                                "pred": "http://www.geneontology.org/formats/oboInOwl#hasOBONamespace",
                                "val": "cellular_component",
                            }
                        ],
                    },
                },
            ],
            "edges": [
                {
                    "sub": "http://purl.obolibrary.org/obo/GO_0006915",
                    "pred": "is_a",
                    "obj": "http://purl.obolibrary.org/obo/GO_0008150",
                },
            ],
        }
    ]
}

SAMPLE_GAF = """!gpa-version: 1.1
!generated-by: GOA
UniProtKB\tP04637\tTP53\tenables\tGO:0003677\tPMID:8875929\tIDA\t\tF\tCellular tumor antigen p53\t\tprotein\ttaxon:9606\t20170928\tUniProt
UniProtKB\tP04637\tTP53\tinvolved_in\tGO:0006915\tPMID:1234567\tIMP\t\tP\tCellular tumor antigen p53\t\tprotein\ttaxon:9606\t20200101\tUniProt
UniProtKB\tP04637\tTP53\tlocated_in\tGO:0005634\tPMID:9999999\tIEA\t\tC\tCellular tumor antigen p53\t\tprotein\ttaxon:9606\t20210501\tUniProt
"""


def _write(tmpdir, subdir, filename, content):
    d = os.path.join(tmpdir, subdir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


@pytest.fixture(scope="module")
def go_data():
    """Load GO data into embedded graph with pre-existing protein."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(tmpdir, "", "go.json", json.dumps(SAMPLE_GO_JSON))
        _write(tmpdir, "", "goa_human.gaf", SAMPLE_GAF)

        try:
            from samyama import SamyamaClient
            from etl.helpers import Registry, create_index
            from etl.go_loader import load_go

            client = SamyamaClient.embedded()
            create_index(client, "Protein", "uniprot_id")
            client.query(
                "CREATE (p:Protein {uniprot_id: 'P04637', name: 'TP53', gene_name: 'TP53'})",
                "default",
            )

            registry = Registry()
            registry.proteins.add("P04637")

            stats = load_go(client, tmpdir, registry)
            yield client, stats, registry
        except ImportError:
            pytest.skip("samyama package not available")


@pytest.fixture(scope="module")
def go_data_no_iea():
    """Load GO data with IEA annotations excluded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(tmpdir, "", "go.json", json.dumps(SAMPLE_GO_JSON))
        _write(tmpdir, "", "goa_human.gaf", SAMPLE_GAF)

        try:
            from samyama import SamyamaClient
            from etl.helpers import Registry, create_index
            from etl.go_loader import load_go

            client = SamyamaClient.embedded()
            create_index(client, "Protein", "uniprot_id")
            client.query(
                "CREATE (p:Protein {uniprot_id: 'P04637', name: 'TP53', gene_name: 'TP53'})",
                "default",
            )

            registry = Registry()
            registry.proteins.add("P04637")

            stats = load_go(client, tmpdir, registry, exclude_iea=True)
            yield client, stats, registry
        except ImportError:
            pytest.skip("samyama package not available")


def _q(client, cypher):
    try:
        r = client.query_readonly(cypher, "default")
        return [dict(zip(r.columns, row)) for row in r.records]
    except Exception:
        r = client.query(cypher, "default")
        return [dict(zip(r.columns, row)) for row in r.records]


class TestGOTermNodes:
    def test_terms_created(self, go_data):
        client, _, _ = go_data
        rows = _q(client, "MATCH (g:GOTerm) RETURN count(*) AS c")
        assert rows[0]["c"] == 4

    def test_term_properties(self, go_data):
        client, _, _ = go_data
        rows = _q(client, """
            MATCH (g:GOTerm {go_id: 'GO:0006915'})
            RETURN g.name, g.namespace
        """)
        assert rows[0]["g.name"] == "apoptotic process"
        assert rows[0]["g.namespace"] == "biological_process"

    def test_all_namespaces(self, go_data):
        client, _, _ = go_data
        rows = _q(client, "MATCH (g:GOTerm) RETURN DISTINCT g.namespace ORDER BY g.namespace")
        namespaces = [r["g.namespace"] for r in rows]
        assert "biological_process" in namespaces
        assert "molecular_function" in namespaces
        assert "cellular_component" in namespaces


class TestGOHierarchy:
    def test_is_a_edge(self, go_data):
        client, _, _ = go_data
        rows = _q(client, """
            MATCH (child:GOTerm {go_id: 'GO:0006915'})-[:IS_A]->(parent:GOTerm)
            RETURN parent.go_id, parent.name
        """)
        assert len(rows) == 1
        assert rows[0]["parent.go_id"] == "GO:0008150"


class TestAnnotations:
    def test_annotated_with_edges(self, go_data):
        client, _, _ = go_data
        rows = _q(client, """
            MATCH (p:Protein {uniprot_id: 'P04637'})-[a:ANNOTATED_WITH]->(g:GOTerm)
            RETURN g.go_id, a.evidence_code ORDER BY g.go_id
        """)
        assert len(rows) == 3  # IDA + IMP + IEA
        go_ids = [r["g.go_id"] for r in rows]
        assert "GO:0003677" in go_ids
        assert "GO:0006915" in go_ids

    def test_evidence_code_preserved(self, go_data):
        client, _, _ = go_data
        rows = _q(client, """
            MATCH (p:Protein)-[a:ANNOTATED_WITH]->(g:GOTerm {go_id: 'GO:0003677'})
            RETURN a.evidence_code
        """)
        assert rows[0]["a.evidence_code"] == "IDA"


class TestIEAExclusion:
    def test_iea_excluded(self, go_data_no_iea):
        client, _, _ = go_data_no_iea
        rows = _q(client, """
            MATCH (p:Protein {uniprot_id: 'P04637'})-[a:ANNOTATED_WITH]->(g:GOTerm)
            RETURN g.go_id, a.evidence_code ORDER BY g.go_id
        """)
        # IEA annotation (GO:0005634) should be excluded
        go_ids = [r["g.go_id"] for r in rows]
        assert "GO:0005634" not in go_ids
        assert len(rows) == 2  # Only IDA + IMP


class TestRegistryState:
    def test_go_terms_tracked(self, go_data):
        _, _, registry = go_data
        assert "GO:0008150" in registry.go_terms
        assert "GO:0006915" in registry.go_terms

    def test_annotations_tracked(self, go_data):
        _, _, registry = go_data
        assert "P04637|GO:0003677" in registry.annotated_with
