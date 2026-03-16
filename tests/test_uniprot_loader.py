"""Tests for UniProt enrichment loader."""

import os
import tempfile
import pytest


SAMPLE_UNIPROT_TSV = """Entry\tGene Names\tProtein names\tOrganism\tLength\tInvolvement in disease\tFunction [CC]\tCross-reference (DrugBank)\tCross-reference (GeneID)
P04637\tTP53 P53\tCellular tumor antigen p53\tHomo sapiens (Human)\t393\tDISEASE: Li-Fraumeni syndrome (LFS) [MIM:151623]: An autosomal dominant disorder.;DISEASE: Colorectal cancer (CRC) [MIM:114500]\tFUNCTION: Acts as a tumor suppressor in many tumor types.\tDB00997;DB01169\t7157
Q13485\tSMAD4 DPC4 MADH4\tMothers against decapentaplegic homolog 4\tHomo sapiens (Human)\t552\tDISEASE: Juvenile polyposis syndrome (JPS) [MIM:174900]\tFUNCTION: Transcriptional modulator.\t\t4089
Q00987\tMDM2 HDM2\tE3 ubiquitin-protein ligase Mdm2\tHomo sapiens (Human)\t491\t\tFUNCTION: E3 ubiquitin-protein ligase.\tDB12345\t4193
"""


def _write(tmpdir, subdir, filename, content):
    d = os.path.join(tmpdir, subdir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


@pytest.fixture(scope="module")
def uniprot_data():
    """Load UniProt data to enrich pre-existing proteins."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write(tmpdir, "uniprot", "uniprot_human_reviewed.tsv", SAMPLE_UNIPROT_TSV)

        try:
            from samyama import SamyamaClient
            from etl.helpers import Registry, create_index
            from etl.uniprot_loader import load_uniprot

            client = SamyamaClient.embedded()
            create_index(client, "Protein", "uniprot_id")
            # Pre-create proteins (as Reactome would)
            client.query(
                "CREATE (p:Protein {uniprot_id: 'P04637', name: 'TP53'})", "default"
            )
            client.query(
                "CREATE (p:Protein {uniprot_id: 'Q13485', name: 'SMAD4'})", "default"
            )

            registry = Registry()
            registry.proteins.add("P04637")
            registry.proteins.add("Q13485")

            stats = load_uniprot(client, tmpdir, registry)
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


class TestProteinEnrichment:
    def test_gene_name_set(self, uniprot_data):
        client, _, _ = uniprot_data
        rows = _q(client, "MATCH (p:Protein {uniprot_id: 'P04637'}) RETURN p.gene_name")
        assert rows[0]["p.gene_name"] == "TP53"

    def test_sequence_length_set(self, uniprot_data):
        client, _, _ = uniprot_data
        rows = _q(client, "MATCH (p:Protein {uniprot_id: 'P04637'}) RETURN p.sequence_length")
        assert rows[0]["p.sequence_length"] == 393


class TestGeneNodes:
    def test_genes_created(self, uniprot_data):
        client, _, registry = uniprot_data
        rows = _q(client, "MATCH (g:Gene) RETURN g.gene_id, g.symbol ORDER BY g.symbol")
        symbols = [r["g.symbol"] for r in rows]
        assert "TP53" in symbols
        assert "SMAD4" in symbols

    def test_encodes_edge(self, uniprot_data):
        client, _, _ = uniprot_data
        rows = _q(client, """
            MATCH (g:Gene {symbol: 'TP53'})-[:ENCODES]->(p:Protein)
            RETURN p.uniprot_id
        """)
        assert len(rows) == 1
        assert rows[0]["p.uniprot_id"] == "P04637"


class TestDiseaseNodes:
    def test_diseases_created(self, uniprot_data):
        client, _, _ = uniprot_data
        rows = _q(client, "MATCH (d:Disease) RETURN d.name ORDER BY d.name")
        names = [r["d.name"] for r in rows]
        assert any("Li-Fraumeni" in n for n in names)
        assert any("Juvenile polyposis" in n for n in names)

    def test_associated_with_edge(self, uniprot_data):
        client, _, _ = uniprot_data
        rows = _q(client, """
            MATCH (p:Protein {uniprot_id: 'P04637'})-[:ASSOCIATED_WITH]->(d:Disease)
            RETURN d.name ORDER BY d.name
        """)
        assert len(rows) >= 2  # Li-Fraumeni + Colorectal cancer


class TestDrugNodes:
    def test_drugs_created(self, uniprot_data):
        client, _, _ = uniprot_data
        rows = _q(client, "MATCH (d:Drug) RETURN d.drugbank_id ORDER BY d.drugbank_id")
        ids = [r["d.drugbank_id"] for r in rows]
        assert "DB00997" in ids
        assert "DB01169" in ids

    def test_targets_edge(self, uniprot_data):
        client, _, _ = uniprot_data
        rows = _q(client, """
            MATCH (d:Drug {drugbank_id: 'DB00997'})-[:TARGETS]->(p:Protein)
            RETURN p.uniprot_id
        """)
        assert len(rows) >= 1
        assert rows[0]["p.uniprot_id"] == "P04637"

    def test_no_drugs_for_empty_xref(self, uniprot_data):
        client, _, _ = uniprot_data
        # Q13485 has no DrugBank cross-refs
        rows = _q(client, """
            MATCH (d:Drug)-[:TARGETS]->(p:Protein {uniprot_id: 'Q13485'})
            RETURN d.drugbank_id
        """)
        assert len(rows) == 0


class TestRegistryState:
    def test_genes_tracked(self, uniprot_data):
        _, _, registry = uniprot_data
        assert "7157" in registry.genes  # TP53 gene ID

    def test_encodes_tracked(self, uniprot_data):
        _, _, registry = uniprot_data
        assert "7157|P04637" in registry.encodes
