"""Tests for STRING protein-protein interaction loader."""

import os
import tempfile
import pytest


SAMPLE_LINKS = """protein1 protein2 combined_score
9606.ENSP00000269305 9606.ENSP00000418915 942
9606.ENSP00000269305 9606.ENSP00000344456 756
9606.ENSP00000269305 9606.ENSP00000000233 450
9606.ENSP00000418915 9606.ENSP00000344456 812
"""

SAMPLE_INFO = """#string_protein_id\tpreferred_name\tprotein_size\tannotation
9606.ENSP00000269305\tTP53\t393\tCellular tumor antigen p53
9606.ENSP00000418915\tSMAD4\t552\tMothers against DPP homolog 4
9606.ENSP00000344456\tMDM2\t491\tE3 ubiquitin-protein ligase Mdm2
9606.ENSP00000000233\tARF5\t180\tADP-ribosylation factor 5
"""

SAMPLE_ALIASES = """#string_protein_id\talias\tsource
9606.ENSP00000269305\tP04637\tUniProt_AC
9606.ENSP00000418915\tQ13485\tUniProt_AC
9606.ENSP00000344456\tQ00987\tUniProt_AC
9606.ENSP00000000233\tP84085\tUniProt_AC
"""


def _write(tmpdir, subdir, filename, content):
    d = os.path.join(tmpdir, subdir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


@pytest.fixture(scope="module")
def string_data():
    """Load STRING interaction data into embedded graph with pre-existing proteins."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(tmpdir, "", "9606.protein.links.v12.0.txt", SAMPLE_LINKS)
        _write(tmpdir, "", "9606.protein.info.v12.0.txt", SAMPLE_INFO)
        _write(tmpdir, "", "9606.protein.aliases.v12.0.txt", SAMPLE_ALIASES)

        try:
            from samyama import SamyamaClient
            from etl.helpers import Registry, create_index
            from etl.string_loader import load_string

            client = SamyamaClient.embedded()

            # Pre-create some proteins (as Reactome would)
            create_index(client, "Protein", "uniprot_id")
            client.query(
                "CREATE (p:Protein {uniprot_id: 'P04637', name: 'TP53', gene_name: 'TP53'})",
                "default",
            )

            registry = Registry()
            registry.proteins.add("P04637")

            stats = load_string(client, tmpdir, registry, threshold=700)
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


class TestScoreFiltering:
    def test_high_confidence_kept(self, string_data):
        client, stats, _ = string_data
        rows = _q(client, "MATCH ()-[i:INTERACTS_WITH]->() RETURN i.combined_score")
        # Score >= 700: (269305,418915)=942, (269305,344456)=756, (418915,344456)=812
        # Score < 700 filtered: (269305,000233)=450
        assert len(rows) >= 3

    def test_low_confidence_filtered(self, string_data):
        client, _, _ = string_data
        # ARF5 (P84085) had score 450 with TP53 — should be filtered
        rows = _q(client, """
            MATCH (p:Protein {uniprot_id: 'P84085'})-[:INTERACTS_WITH]-()
            RETURN p.uniprot_id
        """)
        assert len(rows) == 0


class TestProteinCreation:
    def test_new_proteins_created(self, string_data):
        client, _, registry = string_data
        # Q13485 (SMAD4) and Q00987 (MDM2) should be created by STRING
        assert "Q13485" in registry.proteins
        assert "Q00987" in registry.proteins

    def test_existing_protein_not_duplicated(self, string_data):
        client, _, _ = string_data
        rows = _q(client, "MATCH (p:Protein {uniprot_id: 'P04637'}) RETURN count(*) AS c")
        assert rows[0]["c"] == 1


class TestInteractionEdges:
    def test_interaction_has_score(self, string_data):
        client, _, _ = string_data
        rows = _q(client, """
            MATCH (a:Protein {uniprot_id: 'P04637'})-[i:INTERACTS_WITH]-(b:Protein {uniprot_id: 'Q13485'})
            RETURN i.combined_score
        """)
        assert len(rows) >= 1
        assert rows[0]["i.combined_score"] == 942

    def test_interaction_dedup(self, string_data):
        _, _, registry = string_data
        # Sorted pair key
        assert "P04637|Q13485" in registry.interacts_with or "Q13485|P04637" in registry.interacts_with
