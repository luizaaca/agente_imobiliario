"""Busca livre e ordenação da tabela de leads.

Duas regras sustentam esta tela: a busca varre exatamente os campos que a
tabela mostra — todo resultado se explica olhando a linha — e a ordenação
manda para o fim quem não tem o valor, sempre desempatando por número para a
ordem não dançar entre recargas.
"""

from decimal import Decimal

import pytest

from src.db.models import Lead
from src.services.lead_service import LeadService
from src.ui.tabela import ORDENS, aplicar_ordem, filtro_de_busca, rotulo_do_lead


@pytest.fixture
def leads(db):
    servico = LeadService()
    # Só o segundo tem a palavra "compra" no texto livre; os dois têm a
    # intenção. É o caso que a tela expôs.
    servico.criar_lead_manual(
        {
            "intencao": "compra",
            "bairro_interesse": "Paulista",
            "perfil_narrativo": "Interesse em imóveis comerciais.",
            "score": None,
        },
        db,
    )
    servico.criar_lead_manual(
        {
            "intencao": "compra",
            "bairro_interesse": "Pinheiros",
            "perfil_narrativo": "Cliente quer comprar apartamento.",
        },
        db,
    )
    servico.criar_lead_manual(
        {"intencao": "aluguel", "bairro_interesse": "Tatuapé"}, db
    )
    return db.query(Lead).order_by(Lead.id).all()


def _buscar(db, termo):
    return db.query(Lead).filter(filtro_de_busca(termo)).all()


def test_busca_por_intencao_acha_os_dois(leads, db):
    """O bug: só voltava quem citasse a palavra no perfil narrativo."""
    achados = _buscar(db, "compra")

    assert {lead.id for lead in achados} == {leads[0].id, leads[1].id}


def test_busca_por_bairro(leads, db):
    assert [lead.id for lead in _buscar(db, "pinheiros")] == [leads[1].id]


def test_busca_ignora_caixa_e_espacos_nas_pontas(leads, db):
    assert len(_buscar(db, "  ALUGUEL  ")) == 1


def test_busca_nao_olha_o_perfil_narrativo(leads, db):
    """A busca varre só o que a tabela mostra.

    O perfil narrativo é texto longo e invisível na lista: procurar "lead"
    devolvia os leads cujo texto por acaso começava com a palavra, sem nada
    na linha que explicasse por que eles estavam ali.
    """
    assert _buscar(db, "apartamento") == []


def test_busca_pelo_numero_do_lead(leads, db):
    """O número é o identificador visível, então tem de ser procurável."""
    alvo = leads[1]

    assert [lead.id for lead in _buscar(db, str(alvo.id))] == [alvo.id]


def test_busca_por_status(leads, db):
    assert len(_buscar(db, "novo")) == len(leads)


def test_busca_sem_correspondencia_devolve_vazio(leads, db):
    assert _buscar(db, "helicóptero") == []


# --- Ordenação ---------------------------------------------------------------


def _ordenar(db, rotulo):
    expressao, decrescente = ORDENS[rotulo]
    return aplicar_ordem(db.query(Lead), expressao, decrescente).all()


def test_nome_ordena_pelos_nomeados_e_joga_o_resto_para_o_fim(db):
    servico = LeadService()
    sem_nome = servico.criar_lead_manual({}, db)
    com_nome = servico.criar_lead_manual({"nome": "Ana Brandão"}, db)

    ordenados = _ordenar(db, "Nome (A-Z)")

    assert ordenados[0].id == com_nome.id
    assert ordenados[-1].id == sem_nome.id


def test_lead_sem_nome_aparece_pelo_numero(db):
    """`Lead 29` era um rótulo inventado; o número existe no banco."""
    sem_nome = LeadService().criar_lead_manual({}, db)

    assert rotulo_do_lead(sem_nome) == f"#{sem_nome.id}"


def test_nome_vazio_conta_como_sem_nome(db):
    """Espaço em branco não pode ordenar antes de todo mundo."""
    servico = LeadService()
    branco = servico.criar_lead_manual({"nome": "   "}, db)
    servico.criar_lead_manual({"nome": "Ana"}, db)

    ordenados = _ordenar(db, "Nome (A-Z)")

    assert rotulo_do_lead(ordenados[0]) == "Ana"
    assert ordenados[-1].id == branco.id


def test_score_maior_primeiro(db):
    servico = LeadService()
    baixo = servico.criar_lead_manual({}, db)
    alto = servico.criar_lead_manual({}, db)
    servico.editar_lead(alto.id, {}, db)
    db.query(Lead).filter(Lead.id == alto.id).update({"score": Decimal("9.0")})
    db.query(Lead).filter(Lead.id == baixo.id).update({"score": Decimal("1.0")})
    db.commit()

    ordenados = _ordenar(db, "Score (maior primeiro)")

    assert [lead.id for lead in ordenados] == [alto.id, baixo.id]


def test_score_nulo_vai_para_o_fim_nos_dois_sentidos(db):
    servico = LeadService()
    com_score = servico.criar_lead_manual({}, db)
    sem_score = servico.criar_lead_manual({}, db)
    db.query(Lead).filter(Lead.id == com_score.id).update({"score": Decimal("5.0")})
    db.query(Lead).filter(Lead.id == sem_score.id).update({"score": None})
    db.commit()

    for rotulo in ("Score (maior primeiro)", "Score (menor primeiro)"):
        assert _ordenar(db, rotulo)[-1].id == sem_score.id, rotulo


def test_empate_no_score_nao_danca_entre_recargas(db):
    """Sem desempate por id, a ordem de leads com o mesmo score é arbitrária."""
    servico = LeadService()
    ids = [servico.criar_lead_manual({}, db).id for _ in range(4)]
    db.query(Lead).filter(Lead.id.in_(ids)).update(
        {"score": Decimal("4.0")}, synchronize_session=False
    )
    db.commit()

    primeira = [lead.id for lead in _ordenar(db, "Score (maior primeiro)")]
    segunda = [lead.id for lead in _ordenar(db, "Score (maior primeiro)")]

    assert primeira == segunda == sorted(ids)
