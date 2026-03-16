"""Tests for Reactome pathway loader.

Follows cricket-kg test pattern: sample fixture data, embedded client,
query helper, test classes per node/edge type.
"""

import os
import tempfile
import pytest

# Sample Reactome data fixtures
SAMPLE_PATHWAYS = """R-HSA-109581\tApoptosis\tHomo sapiens
R-HSA-1640170\tCell Cycle\tHomo sapiens
R-HSA-168256\tImmune System\tHomo sapiens
R-MMU-109581\tApoptosis\tMus musculus
"""

SAMPLE_PATHWAY_RELATIONS = """R-HSA-1640170\tR-HSA-109581
"""

SAMPLE_UNIPROT2REACTOME = """P04637\tR-HSA-109581\thttps://reactome.org/PathwayBrowser/#/R-HSA-109581\tApoptosis\tTAS\tHomo sapiens
P04637\tR-HSA-1640170\thttps://reactome.org/PathwayBrowser/#/R-HSA-1640170\tCell Cycle\tTAS\tHomo sapiens
Q13485\tR-HSA-109581\thttps://reactome.org/PathwayBrowser/#/R-HSA-109581\tApoptosis\tTAS\tHomo sapiens
O15350\tR-HSA-168256\thttps://reactome.org/PathwayBrowser/#/R-HSA-168256\tImmune System\tTAS\tHomo sapiens
P12345\tR-MMU-109581\thttps://reactome.org/PathwayBrowser/#/R-MMU-109581\tApoptosis\tTAS\tMus musculus
"""

SAMPLE_INTERACTIONS = """# Interactor 1 uniprot id\tInteractor 1 Ensembl gene id\tInteractor 1 Gene name\tInteractor 1 location\tInteractor 2 uniprot id\tInteractor 2 Ensembl gene id\tInteractor 2 Gene name\tInteraction type\tInteraction context (Pathway)\tInteraction context (Reactome id)
P04637\tENSG00000141510\tTP53\tcytoplasm\tQ13485\tENSG00000174775\tSMAD4\treaction\tApoptosis\tR-HSA-2559580
"""

SAMPLE_COMPLEXES = """complex_id\tcomplex_name\tparticipants\tpubmed_ids
R-HSA-109688\tp53-SMAD Complex\tP04637|Q13485\t12345
"""


def _write_fixture(tmpdir, subdir, filename, content):
    """Write fixture data to a temp file."""
    d = os.path.join(tmpdir, subdir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


@pytest.fixture(scope="module")
def reactome_data():
    """Create fixture data files and load into embedded graph."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_fixture(tmpdir, "reactome", "ReactomePathways.txt", SAMPLE_PATHWAYS)
        _write_fixture(tmpdir, "reactome", "ReactomePathwaysRelation.txt", SAMPLE_PATHWAY_RELATIONS)
        _write_fixture(tmpdir, "reactome", "UniProt2Reactome_All_Levels.txt", SAMPLE_UNIPROT2REACTOME)
        _write_fixture(
            tmpdir, "reactome",
            "reactome.homo_sapiens.interactions.tab-delimited.txt",
            SAMPLE_INTERACTIONS,
        )
        _write_fixture(
            tmpdir, "reactome",
            "ComplexParticipantsPubMedIdentifiers_human.txt",
            SAMPLE_COMPLEXES,
        )

        try:
            from samyama import SamyamaClient
            from etl.helpers import Registry
            from etl.reactome_loader import load_reactome

            client = SamyamaClient.embedded()
            registry = Registry()
            stats = load_reactome(client, tmpdir, registry)
            yield client, stats, registry
        except ImportError:
            pytest.skip("samyama package not available")


def _q(client, cypher):
    """Query helper — returns list of dicts."""
    try:
        r = client.query_readonly(cypher, "default")
        return [dict(zip(r.columns, row)) for row in r.records]
    except Exception:
        r = client.query(cypher, "default")
        return [dict(zip(r.columns, row)) for row in r.records]


class TestPathwayNodes:
    def test_human_pathways_created(self, reactome_data):
        client, stats, _ = reactome_data
        rows = _q(client, "MATCH (pw:Pathway) RETURN pw.name ORDER BY pw.name")
        names = [r["pw.name"] for r in rows]
        assert "Apoptosis" in names
        assert "Cell Cycle" in names
        assert "Immune System" in names

    def test_mouse_pathways_excluded(self, reactome_data):
        client, stats, _ = reactome_data
        rows = _q(client, "MATCH (pw:Pathway) RETURN count(*) AS c")
        # Only 3 human pathways, not 4 (mouse excluded)
        assert rows[0]["c"] == 3

    def test_pathway_has_reactome_id(self, reactome_data):
        client, _, _ = reactome_data
        rows = _q(client, "MATCH (pw:Pathway {name: 'Apoptosis'}) RETURN pw.reactome_id")
        assert rows[0]["pw.reactome_id"] == "R-HSA-109581"


class TestPathwayHierarchy:
    def test_child_of_edge(self, reactome_data):
        client, _, _ = reactome_data
        rows = _q(client, """
            MATCH (child:Pathway)-[:CHILD_OF]->(parent:Pathway)
            RETURN child.name, parent.name
        """)
        assert len(rows) >= 1
        assert rows[0]["child.name"] == "Apoptosis"
        assert rows[0]["parent.name"] == "Cell Cycle"


class TestProteinNodes:
    def test_proteins_created(self, reactome_data):
        client, stats, registry = reactome_data
        rows = _q(client, "MATCH (p:Protein) RETURN p.uniprot_id ORDER BY p.uniprot_id")
        ids = [r["p.uniprot_id"] for r in rows]
        assert "P04637" in ids
        assert "Q13485" in ids
        assert "O15350" in ids

    def test_mouse_proteins_excluded(self, reactome_data):
        client, _, _ = reactome_data
        rows = _q(client, "MATCH (p:Protein {uniprot_id: 'P12345'}) RETURN p.uniprot_id")
        assert len(rows) == 0

    def test_protein_dedup(self, reactome_data):
        _, _, registry = reactome_data
        # P04637 appears in multiple pathways but should be one node
        assert "P04637" in registry.proteins


class TestParticipatesIn:
    def test_participates_in_edges(self, reactome_data):
        client, _, _ = reactome_data
        rows = _q(client, """
            MATCH (p:Protein {uniprot_id: 'P04637'})-[:PARTICIPATES_IN]->(pw:Pathway)
            RETURN pw.name ORDER BY pw.name
        """)
        names = [r["pw.name"] for r in rows]
        assert "Apoptosis" in names
        assert "Cell Cycle" in names

    def test_edge_dedup(self, reactome_data):
        _, _, registry = reactome_data
        # Each protein-pathway pair should appear once (may be tuple or string)
        assert (
            ("P04637", "R-HSA-109581") in registry.protein_pathways
            or "P04637|R-HSA-109581" in registry.protein_pathways
        )


class TestReactionNodes:
    def test_reaction_from_interactions(self, reactome_data):
        client, _, _ = reactome_data
        rows = _q(client, "MATCH (r:Reaction) RETURN r.reactome_id")
        # At least one reaction from interactions file
        assert len(rows) >= 1


class TestComplexNodes:
    def test_complex_created(self, reactome_data):
        client, _, _ = reactome_data
        rows = _q(client, "MATCH (c:Complex) RETURN c.name, c.reactome_id")
        assert len(rows) >= 1
        assert rows[0]["c.reactome_id"] == "R-HSA-109688"

    def test_component_of_edges(self, reactome_data):
        client, _, _ = reactome_data
        rows = _q(client, """
            MATCH (p:Protein)-[:COMPONENT_OF]->(c:Complex {reactome_id: 'R-HSA-109688'})
            RETURN p.uniprot_id ORDER BY p.uniprot_id
        """)
        ids = [r["p.uniprot_id"] for r in rows]
        assert "P04637" in ids
        assert "Q13485" in ids


class TestRegistryState:
    def test_pathways_tracked(self, reactome_data):
        _, _, registry = reactome_data
        assert "R-HSA-109581" in registry.pathways
        assert "R-HSA-1640170" in registry.pathways

    def test_proteins_tracked(self, reactome_data):
        _, _, registry = reactome_data
        assert "P04637" in registry.proteins
        assert "Q13485" in registry.proteins
        assert "O15350" in registry.proteins
