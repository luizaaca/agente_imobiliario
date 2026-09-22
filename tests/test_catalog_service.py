"""Testes do CatalogService: filtros estruturados e busca textual."""

import pytest

from src.db.models import Imovel
from src.services.catalog_service import (
    FINALIDADE_POR_TIPO,
    PERFIS_INDICADOS,
    TIPOS,
    ZONAS,
    CatalogService,
    FiltroInvalido,
)


@pytest.fixture
def catalog():
    return CatalogService()


# --- O vocabulário da tool bate com o do banco -------------------------------
#
# Os `Literal` da tool sao copia dos valores das colunas. Se o catalogo ganhar
# um tipo novo e a lista nao acompanhar, o modelo fica sem como pedi-lo — e
# ninguem percebe, porque a busca continua funcionando para os outros.


def test_todo_tipo_do_catalogo_esta_na_lista_da_tool(db, catalogo):
    do_banco = {t for (t,) in db.query(Imovel.tipo).distinct()}

    assert do_banco <= set(TIPOS)


def test_toda_zona_do_catalogo_esta_na_lista_da_tool(db, catalogo):
    do_banco = {z for (z,) in db.query(Imovel.zona).distinct() if z}

    assert do_banco <= set(ZONAS)


def test_todo_perfil_do_catalogo_esta_na_lista_da_tool(db, catalogo):
    do_banco = {p for (p,) in db.query(Imovel.perfil_indicado).distinct() if p}

    assert do_banco <= set(PERFIS_INDICADOS)


def test_todo_tipo_tem_finalidade_declarada():
    assert set(TIPOS) == set(FINALIDADE_POR_TIPO)


# --- Filtros estruturados ----------------------------------------------------


def test_conta_apenas_disponiveis(catalog, catalogo, db):
    assert catalog.count_available(db) == len(catalogo)


def test_filtra_por_faixa_de_preco(catalog, catalogo, db):
    resultados = catalog.search(db=db, preco_min=500000, preco_max=700000, limite=10)
    precos = [float(i.preco) for i in resultados]
    assert precos and all(500000 <= p <= 700000 for p in precos)


def test_filtra_por_bairro(catalog, catalogo, db):
    resultados = catalog.search(db=db, bairro="Bela Vista", limite=10)
    assert resultados
    assert all("bela vista" in i.bairro.lower() for i in resultados)


def test_bairro_ignora_maiusculas(catalog, catalogo, db):
    assert catalog.search(db=db, bairro="bela vista", limite=10)


def test_filtra_por_zona(catalog, catalogo, db):
    resultados = catalog.search(db=db, zona="zona_sul", limite=10)
    assert [i.bairro for i in resultados] == ["Moema"]


def test_operacao_venda_traz_apenas_venda(catalog, catalogo, db):
    resultados = catalog.search(db=db, operacao="venda", limite=10)
    assert resultados
    assert all(i.operacao == "venda" for i in resultados)


def test_operacao_aluguel_traz_apenas_aluguel(catalog, catalogo, db):
    resultados = catalog.search(db=db, operacao="aluguel", limite=10)
    assert resultados
    assert all(i.operacao == "aluguel" for i in resultados)


def test_filtra_por_tipo(catalog, catalogo, db):
    resultados = catalog.search(db=db, tipo="galpao", limite=10)

    assert [i.titulo for i in resultados] == ["Galpao Belem Logistico"]


def test_finalidade_e_filtro_estruturado(catalog, catalogo, db):
    titulos = [i.titulo for i in catalog.search(db=db, finalidade="comercial", limite=10)]

    assert sorted(titulos) == ["Galpao Belem Logistico", "Sala Comercial Paulista"]


def test_filtra_por_perfil_indicado(catalog, catalogo, db):
    resultados = catalog.search(db=db, perfil_indicado="logistica_industrial", limite=10)

    assert [i.titulo for i in resultados] == ["Galpao Belem Logistico"]


def test_respeita_o_limite_de_resultados(catalog, catalogo, db):
    assert len(catalog.search(db=db, limite=2)) == 2


def test_sem_resultados_devolve_lista_vazia(catalog, catalogo, db):
    assert catalog.search(db=db, bairro="Bairro Inexistente", limite=10) == []


def test_filtros_combinados(catalog, catalogo, db):
    resultados = catalog.search(
        db=db, operacao="venda", bairro="Bela Vista",
        preco_max=550000, quartos_min=2, limite=10,
    )
    assert [i.titulo for i in resultados] == ["Apartamento Bela Vista Compacto"]


def test_indisponivel_fica_fora_da_busca(catalog, catalogo, db):
    db.query(Imovel).filter(Imovel.bairro == "Moema").update({"disponivel": False})
    db.commit()

    bairros = [i.bairro for i in catalog.search(db=db, limite=20)]
    assert "Moema" not in bairros


def test_get_by_id(catalog, catalogo, db):
    assert catalog.get_by_id(1, db).titulo == "Apartamento Bela Vista Compacto"


def test_get_by_id_inexistente(catalog, catalogo, db):
    assert catalog.get_by_id(9999, db) is None


# --- Faixa de quartos --------------------------------------------------------
#
# So minimo obrigava quem quer dois quartos a receber os de quatro. A faixa
# deixa o modelo dizer as tres leituras: exato, "pelo menos" e "entre".


def test_quartos_min_e_minimo(catalog, catalogo, db):
    resultados = catalog.search(db=db, quartos_min=2, limite=10)
    assert resultados
    assert all(i.quartos >= 2 for i in resultados)


def test_quartos_max_corta_os_maiores(catalog, catalogo, db):
    resultados = catalog.search(db=db, operacao="venda", quartos_max=2, limite=10)

    assert "Cobertura Moema Alto Padrao" not in [i.titulo for i in resultados]


def test_faixa_igual_nos_dois_lados_e_numero_exato(catalog, catalogo, db):
    resultados = catalog.search(db=db, quartos_min=2, quartos_max=2, limite=10)

    assert resultados
    assert all(i.quartos == 2 for i in resultados)


def test_faixa_de_quartos_invertida_e_recusada(catalog, catalogo, db):
    with pytest.raises(FiltroInvalido, match="invertida"):
        catalog.search_relaxando(db, quartos_min=4, quartos_max=2, limite=10)


# --- Metragem, vagas, suítes e banheiros -------------------------------------


def test_filtra_por_area_minima(catalog, catalogo, db):
    """No comercial e a metragem que decide; quartos nao diz nada."""
    resultados = catalog.search(db=db, finalidade="comercial", area_min=500, limite=10)

    assert [i.titulo for i in resultados] == ["Galpao Belem Logistico"]


def test_filtra_por_area_maxima(catalog, catalogo, db):
    resultados = catalog.search(db=db, area_max=30, limite=10)

    assert [i.titulo for i in resultados] == ["Studio Pinheiros Investidor"]


def test_filtra_por_vagas(catalog, catalogo, db):
    resultados = catalog.search(db=db, operacao="venda", vagas_min=3, limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


def test_filtra_por_suites(catalog, catalogo, db):
    resultados = catalog.search(db=db, suites_min=2, limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


def test_filtra_por_banheiros(catalog, catalogo, db):
    resultados = catalog.search(db=db, banheiros_min=4, limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


# --- Custo total do aluguel --------------------------------------------------


def test_custo_total_soma_o_condominio(catalog, catalogo, db):
    """A sala custa 4.500 + 900 de condominio: nao cabe em 5.000 no total."""
    por_preco = catalog.search(db=db, operacao="aluguel", preco_max=5000, limite=10)
    por_custo = catalog.search(db=db, operacao="aluguel", custo_total_max=5000, limite=10)

    assert "Sala Comercial Paulista" in [i.titulo for i in por_preco]
    assert "Sala Comercial Paulista" not in [i.titulo for i in por_custo]
    assert [i.titulo for i in por_custo] == ["Apartamento Tatuape Aluguel"]


# --- Ordenação ---------------------------------------------------------------


def test_ordem_padrao_e_preco_crescente(catalog, catalogo, db):
    precos = [float(i.preco) for i in catalog.search(db=db, operacao="venda", limite=10)]

    assert precos == sorted(precos)


def test_ordenar_por_preco_desc(catalog, catalogo, db):
    precos = [
        float(i.preco)
        for i in catalog.search(db=db, operacao="venda", ordenar_por="preco_desc", limite=10)
    ]

    assert precos == sorted(precos, reverse=True)


def test_ordenar_por_area_desc(catalog, catalogo, db):
    resultados = catalog.search(db=db, ordenar_por="area_desc", limite=10)

    assert resultados[0].titulo == "Galpao Belem Logistico"


def test_relevancia_sem_termos_cai_para_preco(catalog, catalogo, db):
    """Pedir ranking sem texto nao pode zerar nem explodir a busca."""
    precos = [
        float(i.preco)
        for i in catalog.search(db=db, ordenar_por="relevancia", limite=10)
    ]

    assert precos == sorted(precos)


# --- Contradições ------------------------------------------------------------
#
# Nem tipo nem finalidade sao afrouxados, entao um par contraditorio daria
# lista vazia para sempre. Recusar na entrada deixa o modelo corrigir.


def test_tipo_com_finalidade_contraditoria_e_recusado(catalog, catalogo, db):
    with pytest.raises(FiltroInvalido, match="sempre comercial"):
        catalog.search_relaxando(
            db, tipo="galpao", finalidade="residencial", limite=10
        )


def test_tipo_deduz_a_finalidade(catalog, catalogo, db):
    """O modelo nao precisa saber que galpao e comercial: a busca sabe."""
    resultado = catalog.search_relaxando(db, tipo="galpao", limite=10)

    assert [i.titulo for i in resultado.imoveis] == ["Galpao Belem Logistico"]


def test_tipo_inexistente_e_recusado(catalog, catalogo, db):
    with pytest.raises(FiltroInvalido, match="Não existe o tipo"):
        catalog.search_relaxando(db, tipo="mansao", limite=10)


# --- Busca textual (Full-Text Search) ----------------------------------------
#
# `search_vector` e coluna gerada pelo PostgreSQL com indice GIN. A camada
# textual filtra por OU e ordena por ts_rank.


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


def test_busca_textual_encontra_por_tag(catalog, catalogo, db):
    titulos = [i.titulo for i in catalog.search(db=db, termos_livres="varanda gourmet", limite=10)]
    assert "Cobertura Moema Alto Padrao" in titulos


def test_busca_textual_encontra_por_titulo(catalog, catalogo, db):
    resultados = catalog.search(db=db, termos_livres="Studio", limite=10)
    assert [i.titulo for i in resultados] == ["Studio Pinheiros Investidor"]


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


def test_aspas_no_termo_nao_viram_busca_por_frase(catalog, catalogo, db):
    """Aspas do modelo nao podem zerar a busca.

    Para o `websearch_to_tsquery` um par de aspas e frase exata. Como os
    termos sao unidos com `or`, o `or` caía dentro das aspas e a consulta
    virava a frase `varand <-> or <-> gourmet` — que nao casa imovel nenhum.
    """
    com_aspas = catalog.search(db=db, termos_livres='"varanda gourmet"', limite=10)
    sem_aspas = catalog.search(db=db, termos_livres="varanda gourmet", limite=10)

    assert [i.id for i in com_aspas] == [i.id for i in sem_aspas]
    assert "Cobertura Moema Alto Padrao" in [i.titulo for i in com_aspas]


def test_aspas_soltas_no_meio_dos_termos(catalog, catalogo, db):
    """Aspa impar, que nem par forma: nao pode derrubar a consulta."""
    resultados = catalog.search(db=db, termos_livres='piscina "metro', limite=10)
    assert "Cobertura Moema Alto Padrao" in [i.titulo for i in resultados]


def test_so_stopwords_nao_zera_a_busca(catalog, catalogo, db):
    """'de a e' vira uma tsquery vazia, que nao casaria nada."""
    resultados = catalog.search(db=db, termos_livres="de a e", bairro="Moema", limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


def test_busca_textual_respeita_os_filtros_estruturados(catalog, catalogo, db):
    resultados = catalog.search(db=db, termos_livres="metro", operacao="aluguel", limite=10)

    assert [i.titulo for i in resultados] == ["Apartamento Tatuape Aluguel"]


def test_zona_escrita_com_espaco_casa_a_coluna_com_underscore(catalog, catalogo, db):
    """A coluna guarda 'zona_oeste'; "zona oeste" e a forma natural de dizer."""
    com_espaco = catalog.search(db=db, zona="zona oeste", limite=10)
    com_underscore = catalog.search(db=db, zona="zona_oeste", limite=10)

    assert [i.titulo for i in com_espaco] == ["Studio Pinheiros Investidor"]
    assert [i.titulo for i in com_underscore] == [i.titulo for i in com_espaco]


def test_zona_ignora_maiusculas_e_hifen(catalog, catalogo, db):
    resultados = catalog.search(db=db, zona="Zona-Sul", limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


def test_zona_ainda_casa_nome_de_bairro(catalog, catalogo, db):
    """O modelo nem sempre sabe em que zona fica a Mooca; errar para brando."""
    resultados = catalog.search(db=db, zona="Moema", limite=10)

    assert [i.titulo for i in resultados] == ["Cobertura Moema Alto Padrao"]


# --- Busca que se afrouxa sozinha --------------------------------------------
#
# O alargamento acontece na tool, e nao no modelo: sem isso o agente devolve o
# problema para o lead ("me diga uma faixa de orcamento") ou afirma ter
# ampliado a busca sem ter ampliado.


def test_busca_exata_nao_relaxa_nada(catalog, catalogo, db):
    resultado = catalog.search_relaxando(db, bairro="Moema", limite=10)

    assert resultado.exata
    assert resultado.relaxamentos == []
    assert [i.titulo for i in resultado.imoveis] == ["Cobertura Moema Alto Padrao"]


def test_afrouxa_o_teto_de_preco_quando_nao_ha_nada(catalog, catalogo, db):
    """A cobertura de Moema custa 1.8M; com teto de 1.5M a busca exata da zero."""
    resultado = catalog.search_relaxando(
        db, bairro="Moema", preco_max=1_500_000, limite=10
    )

    assert resultado.relaxamentos == ["com o teto de preço 30% maior"]
    assert [i.titulo for i in resultado.imoveis] == ["Cobertura Moema Alto Padrao"]


def test_teto_de_preco_se_move_em_vez_de_sumir(catalog, catalogo, db):
    """Virar "qualquer preco" traria a cobertura de 1,8M para quem tem 520 mil."""
    resultado = catalog.search_relaxando(
        db, operacao="venda", bairro="Moema", preco_max=520_000, limite=10
    )

    assert resultado.imoveis
    assert "Cobertura Moema Alto Padrao" not in [i.titulo for i in resultado.imoveis]


def test_abre_do_bairro_para_qualquer_regiao(catalog, catalogo, db):
    resultado = catalog.search_relaxando(db, bairro="Bairro Inexistente", limite=10)

    assert "olhando a região toda, não só o bairro" in resultado.relaxamentos
    assert resultado.imoveis


def test_nao_inventa_relaxamento_de_filtro_que_nao_foi_usado(catalog, catalogo, db):
    """Sem quartos e sem termos na entrada, esses passos nao podem ser citados."""
    resultado = catalog.search_relaxando(db, bairro="Bairro Inexistente", limite=10)

    assert "sem fixar o número de quartos" not in resultado.relaxamentos
    assert "sem exigir os termos da descrição" not in resultado.relaxamentos


def test_afrouxa_o_acessorio_antes_do_essencial(catalog, catalogo, db):
    """Banheiro extra e o primeiro a cair; o bairro, um dos ultimos."""
    resultado = catalog.search_relaxando(
        db, bairro="Moema", banheiros_min=9, limite=10
    )

    assert resultado.relaxamentos == ["sem exigir o número de banheiros"]
    assert [i.titulo for i in resultado.imoveis] == ["Cobertura Moema Alto Padrao"]


# --- O que a busca nunca troca -----------------------------------------------


def test_tipo_nunca_e_afrouxado(catalog, catalogo, db):
    """Quem pede galpao na Bela Vista nao recebe a sala comercial de la.

    Foi exatamente isto que aconteceu em producao: a escada derrubou o termo
    "galpao" e devolveu salas comerciais, e o agente as apresentou como se
    fossem o que a pessoa tinha pedido.
    """
    resultado = catalog.search_relaxando(db, tipo="galpao", bairro="Bela Vista", limite=10)

    assert all(i.tipo == "galpao" for i in resultado.imoveis)
    assert "Sala Comercial Paulista" not in [i.titulo for i in resultado.imoveis]


def test_abrir_o_bairro_mantem_o_tipo(catalog, catalogo, db):
    """A flexibilidade e de lugar, nao de coisa: outro bairro, mesmo galpao."""
    resultado = catalog.search_relaxando(db, tipo="galpao", bairro="Bela Vista", limite=10)

    assert [i.titulo for i in resultado.imoveis] == ["Galpao Belem Logistico"]
    assert resultado.relaxamentos == ["olhando a região toda, não só o bairro"]


def test_operacao_nunca_e_afrouxada(catalog, catalogo, db):
    """Quem quer alugar nao recebe imovel a venda."""
    resultado = catalog.search_relaxando(
        db, operacao="aluguel", tipo="cobertura", limite=10
    )

    assert resultado.imoveis == []


# --- Diagnóstico de lista vazia ----------------------------------------------
#
# Zero resultado e resposta valida, mas so vira resposta util com os numeros
# do catalogo: sem eles o agente pede desculpa no vazio ou oferece outra coisa.


def test_sem_resultado_algum_devolve_o_que_foi_tentado(catalog, catalogo, db):
    resultado = catalog.search_relaxando(db, bairro="Nenhum", preco_max=1, limite=10)

    assert resultado.imoveis == []
    assert resultado.relaxamentos  # precisa dizer o que tentou


def test_diagnostico_diz_quantos_existem_do_que_foi_pedido(catalog, catalogo, db):
    resultado = catalog.search_relaxando(
        db, tipo="galpao", operacao="aluguel", preco_max=5000, limite=10
    )

    assert resultado.imoveis == []
    assert resultado.universo == 1
    assert any("galpao para alugar" in linha for linha in resultado.diagnostico)


def test_diagnostico_aponta_o_preco_que_faltou(catalog, catalogo, db):
    """O galpao custa 18 mil: o agente precisa poder dizer esse numero."""
    resultado = catalog.search_relaxando(
        db, tipo="galpao", operacao="aluguel", preco_max=5000, limite=10
    )

    assert any("18,000" in linha or "18.000" in linha for linha in resultado.diagnostico)


def test_diagnostico_aponta_onde_existe_o_que_ela_procura(catalog, catalogo, db):
    """"Galpão na Moema não tem; tem no Belém" é uma resposta honesta e útil."""
    resultado = catalog.search_relaxando(
        db, tipo="galpao", bairro="Moema", preco_max=5000, limite=10
    )

    assert resultado.imoveis == []
    assert any("Belem" in linha for linha in resultado.diagnostico)


def test_catalogo_sem_o_tipo_diz_isso_e_nao_um_numero(catalog, catalogo, db):
    resultado = catalog.search_relaxando(db, tipo="terreno_comercial", limite=10)

    assert resultado.universo == 0
    assert resultado.diagnostico == [
        "O catálogo não tem nenhum terreno_comercial."
    ]


def test_vocabulario_de_tags_vem_ordenado_por_frequencia(catalog, catalogo, db):
    """É o que o agente de busca lê para traduzir o pedido da pessoa.

    "Varanda gourmet" e `churrasqueira` são a mesma coisa para quem procura, e
    só a lista do que o catálogo de fato escreve permite ligar as duas.
    """
    etiquetas = catalog.vocabulario_de_tags(db)

    assert "metro (3)" == etiquetas[0]
    assert "varanda gourmet (2)" in etiquetas
    assert all("(" in e for e in etiquetas)


def test_vocabulario_de_tags_respeita_o_limite(catalog, catalogo, db):
    assert len(catalog.vocabulario_de_tags(db, limite=2)) == 2


def test_vocabulario_de_tags_ignora_indisponivel(catalog, catalogo, db):
    """Amenidade que só existe em imóvel fora do ar não é vocabulário útil."""
    from src.db.models import Imovel

    db.query(Imovel).filter(Imovel.id == 7).update(
        {Imovel.tags: "doca_exclusiva", Imovel.disponivel: False}
    )
    db.commit()

    assert not any("doca_exclusiva" in e for e in catalog.vocabulario_de_tags(db))
