"""Testes do CatalogService: filtros estruturados e busca textual."""

import pytest

from src.services.catalog_service import CatalogService


@pytest.fixture
def catalog():
    return CatalogService()


def test_conta_apenas_disponiveis(catalog, catalogo, db):
    assert catalog.count_available(db) == len(catalogo)


def test_filtra_por_faixa_de_preco(catalog, catalogo, db):
    resultados = catalog.search(db=db, orcamento_min=500000, orcamento_max=700000, limite=10)
    precos = [float(i.preco) for i in resultados]
    assert precos and all(500000 <= p <= 700000 for p in precos)


def test_filtra_por_bairro(catalog, catalogo, db):
    resultados = catalog.search(db=db, bairro_interesse="Bela Vista", limite=10)
    assert resultados
    assert all("bela vista" in i.bairro.lower() for i in resultados)


def test_bairro_ignora_maiusculas(catalog, catalogo, db):
    assert catalog.search(db=db, bairro_interesse="bela vista", limite=10)


def test_filtra_por_regiao_cobrindo_zona_e_bairro(catalog, catalogo, db):
    resultados = catalog.search(db=db, regiao_interesse="Sul", limite=10)
    assert [i.bairro for i in resultados] == ["Moema"]


def test_quartos_e_minimo_e_nao_exato(catalog, catalogo, db):
    resultados = catalog.search(db=db, quartos=2, limite=10)
    assert resultados
    assert all(i.quartos >= 2 for i in resultados)


def test_intencao_compra_traz_apenas_venda(catalog, catalogo, db):
    resultados = catalog.search(db=db, intencao="compra", limite=10)
    assert resultados
    assert all(i.operacao == "venda" for i in resultados)


def test_intencao_investimento_tambem_busca_venda(catalog, catalogo, db):
    resultados = catalog.search(db=db, intencao="investimento", limite=10)
    assert all(i.operacao == "venda" for i in resultados)


def test_intencao_aluguel_traz_apenas_aluguel(catalog, catalogo, db):
    resultados = catalog.search(db=db, intencao="aluguel", limite=10)
    assert resultados
    assert all(i.operacao == "aluguel" for i in resultados)


def test_busca_textual_encontra_por_tag(catalog, catalogo, db):
    titulos = [i.titulo for i in catalog.search(db=db, termos_livres="varanda gourmet", limite=10)]
    assert "Cobertura Moema Alto Padrao" in titulos


def test_busca_textual_encontra_por_titulo(catalog, catalogo, db):
    resultados = catalog.search(db=db, termos_livres="Studio", limite=10)
    assert [i.titulo for i in resultados] == ["Studio Pinheiros Investidor"]


def test_resultados_vem_ordenados_por_preco(catalog, catalogo, db):
    precos = [float(i.preco) for i in catalog.search(db=db, intencao="compra", limite=10)]
    assert precos == sorted(precos)


def test_respeita_o_limite_de_resultados(catalog, catalogo, db):
    assert len(catalog.search(db=db, limite=2)) == 2


def test_sem_resultados_devolve_lista_vazia(catalog, catalogo, db):
    assert catalog.search(db=db, bairro_interesse="Bairro Inexistente", limite=10) == []


def test_filtros_combinados(catalog, catalogo, db):
    resultados = catalog.search(
        db=db, intencao="compra", bairro_interesse="Bela Vista",
        orcamento_max=550000, quartos=2, limite=10,
    )
    assert [i.titulo for i in resultados] == ["Apartamento Bela Vista Compacto"]


def test_indisponivel_fica_fora_da_busca(catalog, catalogo, db):
    from src.db.models import Imovel

    db.query(Imovel).filter(Imovel.bairro == "Moema").update({"disponivel": False})
    db.commit()

    bairros = [i.bairro for i in catalog.search(db=db, limite=20)]
    assert "Moema" not in bairros


def test_get_by_id(catalog, catalogo, db):
    assert catalog.get_by_id(1, db).titulo == "Apartamento Bela Vista Compacto"


def test_get_by_id_inexistente(catalog, catalogo, db):
    assert catalog.get_by_id(9999, db) is None
