"""Testes do CatalogService: filtros estruturados e busca textual."""

import pytest

from src.db.models import Imovel
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


# --- Busca textual (Full-Text Search) ----------------------------------------
#
# Ate a Fase 6 `search_vector` era uma coluna Text nunca preenchida e a busca
# caia em ILIKE ordenado por preco. Agora e coluna gerada pelo PostgreSQL com
# indice GIN, e a camada textual filtra por OU e ordena por ts_rank.


def test_coluna_gerada_e_preenchida_pelo_banco(db):
    """Nenhum codigo da aplicacao escreve em search_vector: quem preenche e o PG."""
    imovel = Imovel(
        titulo="Cobertura Duplex com Piscina",
        tipo="cobertura", finalidade="residencial", operacao="venda",
        bairro="Perdizes", cidade="Sao Paulo", estado="SP",
        preco=2000000, quartos=4, area_m2=200, tags="piscina, churrasqueira",
    )
    db.add(imovel)
    db.commit()
    db.refresh(imovel)

    assert imovel.search_vector is not None
    assert "piscin" in imovel.search_vector


def test_termos_sao_combinados_com_ou(catalog, catalogo, db):
    """Com E entre as palavras (padrao do tsquery) isso devolveria zero."""
    titulos = [i.titulo for i in catalog.search(db=db, termos_livres="piscina metro", limite=10)]

    assert "Cobertura Moema Alto Padrao" in titulos      # so 'piscina'
    assert "Apartamento Bela Vista Compacto" in titulos  # so 'metro'


def test_mais_termos_casados_vem_primeiro(catalog, catalogo, db):
    """O ranking e o que separa relevancia, ja que o filtro e por OU."""
    titulos = [i.titulo for i in catalog.search(db=db, termos_livres="metro investidor", limite=10)]

    # O Studio casa 'metro' e 'investidor'; os demais casam so 'metro'.
    assert titulos[0] == "Studio Pinheiros Investidor"
    assert len(titulos) > 1


def test_so_stopwords_nao_zera_a_busca(catalog, catalogo, db):
    """'de a e' vira uma tsquery vazia, que nao casaria nada."""
    resultados = catalog.search(db=db, termos_livres="de a e", bairro_interesse="Moema", limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


def test_busca_textual_respeita_os_filtros_estruturados(catalog, catalogo, db):
    resultados = catalog.search(db=db, termos_livres="metro", intencao="aluguel", limite=10)

    assert [i.titulo for i in resultados] == ["Apartamento Tatuape Aluguel"]


# --- Busca que se afrouxa sozinha --------------------------------------------
#
# Sem isso o agente devolvia o problema para o lead ("me diga uma faixa de
# orcamento") ou, pior, afirmava ter ampliado a busca sem ter ampliado.


def test_busca_exata_nao_relaxa_nada(catalog, catalogo, db):
    resultado = catalog.search_relaxando(db, bairro_interesse="Moema", limite=10)

    assert resultado.exata
    assert resultado.relaxamentos == []
    assert [i.titulo for i in resultado.imoveis] == ["Cobertura Moema Alto Padrao"]


def test_afrouxa_o_teto_de_preco_quando_nao_ha_nada(catalog, catalogo, db):
    """A cobertura de Moema custa 1.8M; com teto de 1.5M a busca exata da zero."""
    resultado = catalog.search_relaxando(
        db, bairro_interesse="Moema", orcamento_max=1_500_000, limite=10
    )

    assert resultado.relaxamentos == ["com o teto de preço 30% maior"]
    assert [i.titulo for i in resultado.imoveis] == ["Cobertura Moema Alto Padrao"]


def test_abre_do_bairro_para_qualquer_regiao(catalog, catalogo, db):
    resultado = catalog.search_relaxando(
        db, bairro_interesse="Bairro Inexistente", limite=10
    )

    assert "olhando a região toda, não só o bairro" in resultado.relaxamentos
    assert resultado.imoveis


def test_nao_inventa_relaxamento_de_filtro_que_nao_foi_usado(catalog, catalogo, db):
    """Sem quartos e sem termos na entrada, esses passos nao podem ser citados."""
    resultado = catalog.search_relaxando(
        db, bairro_interesse="Bairro Inexistente", limite=10
    )

    assert "sem fixar o número de quartos" not in resultado.relaxamentos
    assert "sem exigir os termos da descrição" not in resultado.relaxamentos


def test_sem_resultado_algum_devolve_o_que_foi_tentado(catalog, catalogo, db):
    resultado = catalog.search_relaxando(
        db, bairro_interesse="Nenhum", orcamento_max=1, limite=10
    )

    assert resultado.imoveis == []
    assert resultado.relaxamentos  # precisa dizer o que tentou


def test_finalidade_e_filtro_estruturado(catalog, catalogo, db):
    resultados = catalog.search(db=db, finalidade="comercial", limite=10)

    assert [i.titulo for i in resultados] == ["Sala Comercial Paulista"]


def test_zona_escrita_com_espaco_casa_a_coluna_com_underscore(catalog, catalogo, db):
    """A coluna guarda 'zona_oeste'; "zona oeste" e a forma natural de dizer."""
    com_espaco = catalog.search(db=db, regiao_interesse="zona oeste", limite=10)
    com_underscore = catalog.search(db=db, regiao_interesse="zona_oeste", limite=10)

    assert [i.titulo for i in com_espaco] == ["Studio Pinheiros Investidor"]
    assert [i.titulo for i in com_underscore] == [i.titulo for i in com_espaco]


def test_zona_ignora_maiusculas_e_hifen(catalog, catalogo, db):
    resultados = catalog.search(db=db, regiao_interesse="Zona-Sul", limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


def test_regiao_ainda_casa_nome_de_bairro(catalog, catalogo, db):
    resultados = catalog.search(db=db, regiao_interesse="Moema", limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]
