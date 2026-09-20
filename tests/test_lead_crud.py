"""Edição manual de lead: o que o corretor faz pela ficha.

Caminho diferente do da LLM. Lá o `None` significa "o modelo não falou disso"
e é ignorado; aqui significa "o corretor apagou este campo" e é gravado.
"""

from decimal import Decimal

import pytest

from src.db.models import Lead, LeadChannelIdentity
from src.services.lead_service import LeadService


@pytest.fixture
def servico():
    return LeadService()


@pytest.fixture
def lead(servico, db):
    return servico.criar_lead_manual(
        {
            "nome": "Rita Alves",
            "intencao": "compra",
            "orcamento_max": Decimal("700000"),
            "bairro_interesse": "Bela Vista",
            "quartos": 2,
        },
        db,
    )


def test_lead_criado_a_mao_nasce_novo_e_com_score_zero(lead):
    assert lead.status == "novo"
    assert lead.score == Decimal("0.0")
    assert lead.nome == "Rita Alves"


def test_edicao_grava_o_que_o_corretor_deixou(servico, lead, db):
    servico.editar_lead(lead.id, {"nome": "Rita A. Alves", "quartos": 3}, db)

    atual = servico.get_lead(lead.id, db)
    assert atual.nome == "Rita A. Alves"
    assert atual.quartos == 3


def test_campo_apagado_pelo_corretor_e_gravado_como_nulo(servico, lead, db):
    """A LLM ignoraria este `None`; a ficha não pode ignorar.

    Sem isso não haveria como limpar um dado que o agente entendeu errado.
    """
    servico.editar_lead(lead.id, {"bairro_interesse": None}, db)

    assert servico.get_lead(lead.id, db).bairro_interesse is None


def test_edicao_nao_recalcula_o_status(servico, lead, db):
    """Se o corretor moveu o lead no funil, foi de propósito."""
    servico.editar_lead(lead.id, {"status": "agendado"}, db)

    assert servico.get_lead(lead.id, db).status == "agendado"


def test_campo_fora_da_lista_editavel_e_ignorado(servico, lead, db):
    """Score é calculado e resumo é gerado: nenhum dos dois vem da ficha."""
    servico.editar_lead(lead.id, {"score": Decimal("9.9"), "resumo": "forjado"}, db)

    atual = servico.get_lead(lead.id, db)
    assert atual.score == Decimal("0.0")
    assert atual.resumo is None


def test_editar_lead_inexistente_devolve_none(servico, db):
    assert servico.editar_lead(999999, {"nome": "ninguém"}, db) is None


# --- Canal de conversa -------------------------------------------------------


def test_lead_criado_a_mao_nasce_sem_canal(servico, lead, db):
    """É o que o impede de receber follow-up até ser vinculado."""
    assert servico.get_primary_identity(lead.id, db) is None


def test_vincular_canal_torna_o_lead_alcancavel(servico, lead, db):
    servico.definir_identidade(lead.id, "telegram", "123456", db)

    identidade = servico.get_primary_identity(lead.id, db)
    assert (identidade.channel, identidade.external_chat_id) == ("telegram", "123456")
    assert identidade.is_primary


def test_vincular_preenche_o_canal_de_origem_vazio(servico, lead, db):
    servico.definir_identidade(lead.id, "telegram", "123456", db)

    assert servico.get_lead(lead.id, db).canal_origem == "telegram"


def test_revincular_o_mesmo_canal_corrige_o_identificador(servico, lead, db):
    """Chat_id digitado errado se conserta sem criar identidade duplicada."""
    servico.definir_identidade(lead.id, "telegram", "123456", db)
    servico.definir_identidade(lead.id, "telegram", "999888", db)

    identidades = (
        db.query(LeadChannelIdentity)
        .filter(LeadChannelIdentity.lead_id == lead.id)
        .all()
    )
    assert len(identidades) == 1
    assert identidades[0].external_chat_id == "999888"


def test_canal_novo_assume_a_preferencia(servico, lead, db):
    """O corretor acabou de dizer por onde falar com este lead."""
    servico.definir_identidade(lead.id, "streamlit", "abc", db)
    servico.definir_identidade(lead.id, "telegram", "123456", db)

    preferencial = servico.get_primary_identity(lead.id, db)
    assert preferencial.channel == "telegram"

    primarias = (
        db.query(LeadChannelIdentity)
        .filter(
            LeadChannelIdentity.lead_id == lead.id,
            LeadChannelIdentity.is_primary.is_(True),
        )
        .count()
    )
    assert primarias == 1


def test_vincular_canal_de_lead_inexistente_devolve_none(servico, db):
    assert servico.definir_identidade(999999, "telegram", "1", db) is None


def test_lead_manual_vinculado_recebe_followup(servico, db):
    """O ciclo alcança um lead que nasceu na ficha, não numa conversa."""
    lead = servico.criar_lead_manual({"nome": "Rita", "intencao": "compra"}, db)
    servico.editar_lead(lead.id, {"status": "em_qualificacao"}, db)
    servico.definir_identidade(lead.id, "telegram", "555000", db)

    from src.scheduler.followup_runner import FollowUpService

    assert FollowUpService().regua_do_status("em_qualificacao") is not None
    identidade = servico.get_primary_identity(lead.id, db)
    assert identidade.external_chat_id == "555000"


def test_criar_lead_ignora_campo_nao_editavel(servico, db):
    lead = servico.criar_lead_manual({"nome": "Rita", "score": Decimal("10")}, db)

    assert db.query(Lead).filter(Lead.id == lead.id).one().score == Decimal("0.0")
