"""Livro-caixa das chamadas ao provider.

A tabela `llm_usage` registra toda chamada, inclusive as que falharam: sem a
linha da falha, a taxa de erro do dashboard seria sempre zero. Estes testes
fixam o que entra, o que não entra e o que cada métrica responde quando ainda
não há dado nenhum.
"""

import pytest

from src.db.models import Lead
from src.services.llm_usage_service import LLMUsageService


@pytest.fixture
def servico():
    return LLMUsageService()


@pytest.fixture
def lead_id(db):
    lead = Lead(status="novo")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead.id


def test_chamada_com_sucesso_guarda_latencia(servico, lead_id, db):
    servico.record(
        lead_id=lead_id, model="gpt-4o-mini", tokens_in=10, tokens_out=5,
        operation="chat", latency_ms=1234, db=db,
    )

    assert servico.get_daily_latency_ms(db) == 1234
    assert servico.get_daily_error_rate(db) == 0.0


def test_falha_entra_sem_token_e_sem_custo(servico, lead_id, db):
    usage = servico.record_failure(
        lead_id=lead_id, model="gpt-4o-mini", operation="chat",
        error_type="APIConnectionError", latency_ms=900, db=db,
    )

    assert usage.status == "erro"
    assert usage.error_type == "APIConnectionError"
    assert usage.tokens_total == 0
    # A falha não pode inflar o consumo que alimenta os budgets.
    assert servico.get_daily_tokens(db) == 0


def test_taxa_de_erro_conta_sucesso_e_falha(servico, lead_id, db):
    for _ in range(3):
        servico.record(
            lead_id=lead_id, model="m", tokens_in=1, tokens_out=1,
            operation="chat", db=db,
        )
    servico.record_failure(
        lead_id=lead_id, model="m", operation="chat", error_type="Timeout", db=db,
    )

    assert servico.get_daily_error_rate(db) == pytest.approx(0.25)


def test_latencia_ignora_a_chamada_que_falhou(servico, lead_id, db):
    """A latência de uma falha mede o timeout, não o tempo de resposta."""
    servico.record(
        lead_id=lead_id, model="m", tokens_in=1, tokens_out=1,
        operation="chat", latency_ms=100, db=db,
    )
    servico.record_failure(
        lead_id=lead_id, model="m", operation="chat",
        error_type="Timeout", latency_ms=30000, db=db,
    )

    assert servico.get_daily_latency_ms(db) == 100


def test_turno_so_conta_chamada_bem_sucedida(servico, lead_id, db):
    """Uma falha do provider não gastou turno do lead.

    Contá-la anteciparia o handover por limite de conversa — o lead seria
    empurrado para o corretor por causa de uma instabilidade nossa.
    """
    servico.record(
        lead_id=lead_id, model="m", tokens_in=1, tokens_out=1,
        operation="chat", db=db,
    )
    servico.record_failure(
        lead_id=lead_id, model="m", operation="chat", error_type="Timeout", db=db,
    )

    assert servico.get_conversation_turns(lead_id, db) == 1


def test_sem_chamada_nenhuma_as_metricas_dizem_que_nao_sabem(servico, db):
    """`None`, e não zero: zero afirmaria que está tudo bem."""
    assert servico.get_daily_error_rate(db) is None
    assert servico.get_daily_latency_ms(db) is None


def test_resumo_do_dashboard_carrega_as_metricas_novas(servico, lead_id, db):
    servico.record(
        lead_id=lead_id, model="m", tokens_in=1, tokens_out=1,
        operation="chat", latency_ms=500, db=db,
    )

    resumo = servico.get_dashboard_summary(db)

    assert resumo["daily_latency_ms"] == 500
    assert resumo["daily_error_rate"] == 0.0
    assert resumo["daily_budget_exceeded"] is False
    assert resumo["monthly_budget_exceeded"] is False

def test_custo_da_conversa_soma_todas_as_operacoes(servico, lead_id, db):
    """Chat, busca e perfil gastam do mesmo bolso, e é o bolso que interessa."""
    for operacao, entrada, saida in (
        ("chat", 1000, 500), ("busca", 4000, 300), ("perfil", 200, 100),
    ):
        servico.record(
            lead_id=lead_id, model="gpt-4o-mini", tokens_in=entrada,
            tokens_out=saida, operation=operacao, db=db,
        )

    esperado = sum(
        servico.estimate_cost("gpt-4o-mini", entrada, saida)
        for entrada, saida in ((1000, 500), (4000, 300), (200, 100))
    )
    assert servico.get_conversation_cost(lead_id, db) == pytest.approx(esperado)


def test_custo_de_uma_conversa_nao_alcanca_a_outra(servico, lead_id, db):
    outro = Lead(status="novo")
    db.add(outro)
    db.commit()
    db.refresh(outro)
    servico.record(
        lead_id=outro.id, model="gpt-4o", tokens_in=500_000, tokens_out=100_000,
        operation="chat", db=db,
    )

    assert servico.get_conversation_cost(lead_id, db) == 0.0
    assert servico.get_conversation_cost(outro.id, db) > 0.0


def test_conversa_sem_chamada_nenhuma_custa_zero(servico, lead_id, db):
    """Zero, e não `None`: a tela soma este número a um teto."""
    assert servico.get_conversation_cost(lead_id, db) == 0.0
