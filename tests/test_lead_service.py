"""Testes do LeadService: score, funil e saneamento dos dados da LLM."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.db.models import (
    Agendamento,
    FollowUpAttempt,
    Lead,
    LeadChannelIdentity,
    LLMUsage,
)
from src.services.followup_service import FollowUpService
from src.services.lead_service import (
    FAIXAS_DE_ENGAJAMENTO,
    PESO_AGENDAMENTO,
    PESO_TIPOLOGIA,
    PESO_URGENCIA,
    PONTO_POR_CAMPO_DA_FICHA,
    LeadService,
    _campos_da_ficha,
)
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

QUALIFICACAO_COMPLETA = {
    "intencao": "compra",
    "orcamento_max": 700000,
    "bairro_interesse": "Bela Vista",
    "quartos": 2,
}


@pytest.fixture
def lead_service():
    return LeadService()


@pytest.fixture
def lead_id(lead_service, db):
    return lead_service.get_or_create_lead(
        channel="teste", external_id="teste-001", db=db, nome="Ana"
    ).id


# --- Identidade de canal -----------------------------------------------------


def test_get_or_create_reaproveita_o_mesmo_external_id(lead_service, db):
    primeiro = lead_service.get_or_create_lead(channel="teste", external_id="x1", db=db)
    segundo = lead_service.get_or_create_lead(channel="teste", external_id="x1", db=db)
    assert primeiro.id == segundo.id


def test_external_ids_diferentes_geram_leads_diferentes(lead_service, db):
    a = lead_service.get_or_create_lead(channel="teste", external_id="x1", db=db)
    b = lead_service.get_or_create_lead(channel="teste", external_id="x2", db=db)
    assert a.id != b.id


# --- Funil -------------------------------------------------------------------


def test_lead_nasce_como_novo(lead_service, lead_id, db):
    assert lead_service.get_lead(lead_id, db).status == "novo"


def test_qualificacao_parcial_mantem_em_qualificacao(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, {"intencao": "compra"}, db)
    assert lead_service.get_lead(lead_id, db).status == "em_qualificacao"


def test_dados_minimos_completos_promovem_para_qualificado(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    assert lead_service.get_lead(lead_id, db).status == "qualificado"


def test_orcamento_min_tambem_satisfaz_o_grupo_de_orcamento(lead_service, lead_id, db):
    dados = dict(QUALIFICACAO_COMPLETA)
    dados.pop("orcamento_max")
    dados["orcamento_min"] = 300000
    lead_service.update_qualification(lead_id, dados, db)
    assert lead_service.get_lead(lead_id, db).status == "qualificado"


def test_status_agendado_nao_regride_com_nova_qualificacao(lead_service, lead_id, db):
    lead_service.update_status(lead_id, "agendado", db)
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    assert lead_service.get_lead(lead_id, db).status == "agendado"


def test_lead_inativo_nao_e_promovido_apenas_por_dados(lead_service, lead_id, db):
    lead_service.update_status(lead_id, "inativo", db)
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    assert lead_service.get_lead(lead_id, db).status == "inativo"


def test_mudanca_de_intencao_no_meio_da_conversa(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, {"intencao": "compra"}, db)
    lead_service.update_qualification(lead_id, {"intencao": "aluguel"}, db)
    assert lead_service.get_lead(lead_id, db).intencao == "aluguel"


# --- Saneamento dos dados vindos da LLM --------------------------------------


def test_valor_maior_que_a_coluna_e_truncado(lead_service):
    """Regressão: 95 caracteres em `perfil` (VARCHAR(30)) derrubavam o turno."""
    frase = "Busca de imovel para aluguel na zona leste, com interesse em 1 ou 2 quartos, a vista."
    limpo = lead_service.sanitizar_qualificacao({"perfil": frase})
    assert len(limpo["perfil"]) == 30


def test_persistir_texto_longo_nao_levanta_erro(lead_service, lead_id, db):
    frase = "x" * 400
    lead_service.update_qualification(lead_id, {"perfil": frase}, db)
    assert len(lead_service.get_lead(lead_id, db).perfil) == 30


def test_valor_fora_do_vocabulario_e_descartado(lead_service):
    limpo = lead_service.sanitizar_qualificacao({"urgencia": "muito urgente mesmo"})
    assert "urgencia" not in limpo


def test_valor_do_vocabulario_e_normalizado_para_minusculo(lead_service):
    limpo = lead_service.sanitizar_qualificacao({"intencao": "ALUGUEL"})
    assert limpo["intencao"] == "aluguel"


def test_valores_nao_textuais_passam_intactos(lead_service):
    limpo = lead_service.sanitizar_qualificacao({"quartos": 3, "orcamento_max": 500000.0})
    assert limpo == {"quartos": 3, "orcamento_max": 500000.0}


# --- Score -------------------------------------------------------------------


def marcar_visita(lead_id, db):
    """Põe uma visita de pé na agenda do lead."""
    return SchedulingService().create(
        lead_id=lead_id, tipo="visita",
        data_hora=datetime.now(UTC) + timedelta(days=1), db=db,
    )


def conversar(lead_service, lead_id, db, quantas):
    """Escreve `quantas` mensagens da pessoa, para mexer no engajamento."""
    for i in range(quantas):
        lead_service.save_message(
            lead_id=lead_id, channel="teste", role="user",
            content=f"mensagem {i}", message_type="chat", db=db,
        )


def test_score_de_lead_sem_dados_e_zero(lead_service, lead_id, db):
    assert lead_service.calculate_score(lead_id, db) == Decimal("0.00")


def test_score_cresce_com_a_completude(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, {"intencao": "compra"}, db)
    parcial = lead_service.calculate_score(lead_id, db)

    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    completo = lead_service.calculate_score(lead_id, db)

    assert completo > parcial


def test_telefone_conta_como_campo_da_ficha(lead_service, lead_id, db):
    """O score ordena a fila de ligações, e sem número não há ligação."""
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    sem_telefone = lead_service.calculate_score(lead_id, db)

    lead_service.update_qualification(lead_id, {"telefone": "(11) 99999-0000"}, db)

    assert lead_service.calculate_score(lead_id, db) > sem_telefone


def test_forma_de_pagamento_nao_mexe_no_score(lead_service, lead_id, db):
    """Campo que a conversa nunca capta não pode segurar ponto da régua."""
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    antes = lead_service.calculate_score(lead_id, db)

    lead_service.update_qualification(lead_id, {"forma_pagamento": "a_vista"}, db)

    assert lead_service.calculate_score(lead_id, db) == antes


def test_urgencia_alta_pontua_mais_que_baixa(lead_service, db):
    def score_para(urgencia, sufixo):
        lid = lead_service.get_or_create_lead(
            channel="teste", external_id=f"u-{sufixo}", db=db
        ).id
        lead_service.update_qualification(
            lid, {**QUALIFICACAO_COMPLETA, "urgencia": urgencia}, db)
        return lead_service.calculate_score(lid, db)

    assert score_para("alta", "alta") > score_para("baixa", "baixa")


def test_engajamento_do_lead_soma_ao_score(lead_service, lead_id, db):
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    sem_mensagens = lead_service.calculate_score(lead_id, db)

    conversar(lead_service, lead_id, db, 6)

    assert lead_service.calculate_score(lead_id, db) > sem_mensagens


def test_visita_marcada_leva_o_lead_para_a_faixa_quente(lead_service, lead_id, db):
    """Visita marcada é o evento de conversão: nunca fica abaixo de 7.0.

    Sem o piso, um lead com visita na agenda empatava com um lead que já
    tinha parado de responder — e a fila é ordenada por este número.
    """
    assert lead_service.calculate_score(lead_id, db) < Decimal("7.00")

    marcar_visita(lead_id, db)

    assert lead_service.calculate_score(lead_id, db) >= Decimal("7.00")


def test_marcar_a_visita_recalcula_o_score_sozinho(lead_service, lead_id, db):
    """Ninguém chama `calculate_score` aqui, e o número tem que estar certo.

    É o defeito que motivou esta mudança: `agendar_reuniao` criava o
    compromisso e voltava, e o painel seguia mostrando a nota de antes de a
    visita existir.
    """
    lead_service.update_qualification(lead_id, QUALIFICACAO_COMPLETA, db)
    lead_service.calculate_score(lead_id, db)

    marcar_visita(lead_id, db)

    assert lead_service.get_lead(lead_id, db).score >= Decimal("7.00")


def test_visita_cancelada_devolve_o_score(lead_service, lead_id, db):
    agendamento = marcar_visita(lead_id, db)
    com_visita = lead_service.calculate_score(lead_id, db)

    SchedulingService().update_status(agendamento.id, "cancelado", db)

    assert lead_service.get_lead(lead_id, db).score < com_visita


def test_visita_realizada_nao_segura_o_lead_no_topo(lead_service, lead_id, db):
    """Visita que já aconteceu não é mais promessa de visita."""
    agendamento = marcar_visita(lead_id, db)
    SchedulingService().update_status(agendamento.id, "realizado", db)

    assert lead_service.calculate_score(lead_id, db) < Decimal("7.00")


def test_lead_inativo_tambem_perde_o_ponto_da_visita(lead_service, lead_id, db):
    """O estágio de inativo não é tocado; o score é recalculado assim mesmo.

    Um lead que parou de responder continua parado mesmo com visita antiga no
    calendário — mas se a visita foi cancelada, a nota não pode continuar
    dizendo que existe uma.
    """
    agendamento = marcar_visita(lead_id, db)
    lead_service.update_status(lead_id, "inativo", db)

    SchedulingService().update_status(agendamento.id, "cancelado", db)

    lead = lead_service.get_lead(lead_id, db)
    assert lead.status == "inativo"
    assert lead.score < Decimal("7.00")


def test_a_nota_dez_e_alcancavel(lead_service, lead_id, db):
    """Ficha cheia, prazo apertado, conversa longa e visita marcada dão 10.

    Enquanto `forma_pagamento` valia um ponto ninguém chegava lá: a conversa
    nunca captou esse campo em lead nenhum, e o teto real era 6.5 — abaixo
    dos 7.0 que o painel chama de quente.
    """
    lead_service.update_qualification(
        lead_id,
        {**QUALIFICACAO_COMPLETA, "urgencia": "alta",
         "telefone": "(11) 98888-7777", "tipologia_interesse": "apartamento"},
        db,
    )
    conversar(lead_service, lead_id, db, 12)
    marcar_visita(lead_id, db)

    assert lead_service.calculate_score(lead_id, db) == Decimal("10.00")


def test_os_pesos_das_dimensoes_somam_dez():
    """A régua promete 0 a 10, e quem cobra é o CHECK do banco.

    Não há cláusula de corte no cálculo, de propósito: peso mal somado tem de
    quebrar aqui, e não virar INSERT recusado com o lead na tela.
    """
    teto = (
        len(_campos_da_ficha(Lead())) * PONTO_POR_CAMPO_DA_FICHA
        + max(PESO_URGENCIA.values())
        + PESO_TIPOLOGIA
        + FAIXAS_DE_ENGAJAMENTO[0][1]
        + PESO_AGENDAMENTO
    )
    assert teto == 10.0


# --- Mensagens ---------------------------------------------------------------


def test_historico_volta_em_ordem_cronologica(lead_service, lead_id, db):
    for i in range(3):
        lead_service.save_message(
            lead_id=lead_id, channel="teste", role="user",
            content=f"m{i}", message_type="chat", db=db,
        )
    conteudos = [m.content for m in lead_service.get_history(lead_id, 10, db)]
    assert conteudos == ["m0", "m1", "m2"]


def test_historico_respeita_o_limite_mantendo_as_mais_recentes(lead_service, lead_id, db):
    for i in range(5):
        lead_service.save_message(
            lead_id=lead_id, channel="teste", role="user",
            content=f"m{i}", message_type="chat", db=db,
        )
    conteudos = [m.content for m in lead_service.get_history(lead_id, 2, db)]
    assert conteudos == ["m3", "m4"]


def test_has_message_type_identifica_handover(lead_service, lead_id, db):
    assert not lead_service.has_message_type(lead_id, "handover", db)
    lead_service.save_message(
        lead_id=lead_id, channel="teste", role="assistant",
        content="passando ao corretor", message_type="handover", db=db,
    )
    assert lead_service.has_message_type(lead_id, "handover", db)


def test_mark_message_sent_registra_o_envio(lead_service, lead_id, db):
    msg = lead_service.save_message(
        lead_id=lead_id, channel="teste", role="assistant", content="oi",
        message_type="followup", db=db, status="generated",
    )
    lead_service.mark_message_sent(msg.id, db)
    db.refresh(msg)
    assert msg.status == "sent"
    assert msg.sent_at is not None


def test_dashboard_ordena_por_score_desc(lead_service, db):
    for sufixo, score in (("baixo", 2), ("alto", 9), ("medio", 5)):
        lid = lead_service.get_or_create_lead(
            channel="teste", external_id=f"d-{sufixo}", db=db
        ).id
        db.query(Lead).filter(Lead.id == lid).update({"score": score})
    db.commit()

    scores = [float(item.score) for item in lead_service.get_leads_for_dashboard({}, db)]
    assert scores == sorted(scores, reverse=True)


# --- Exclusao de lead --------------------------------------------------------


@pytest.fixture
def lead_com_historico(lead_service, lead_id, db):
    """Lead com mensagem, identidade, agendamento, follow-up e consumo de LLM."""
    lead_service.save_message(
        lead_id=lead_id, channel="teste", role="user",
        content="oi", message_type="chat", db=db,
    )
    SchedulingService().create(
        lead_id=lead_id, tipo="visita",
        data_hora=datetime.now(UTC) + timedelta(days=1), db=db,
    )
    FollowUpService().record_attempt(
        lead_id=lead_id, regua="lead_novo_sem_resposta", status="sent", db=db,
    )
    LLMUsageService().record(
        lead_id=lead_id, model="modelo-de-teste", tokens_in=100,
        tokens_out=50, operation="chat", db=db,
    )
    return lead_id


def test_excluir_lead_remove_o_lead_e_seus_vinculos(
    lead_service, lead_com_historico, db
):
    assert lead_service.delete_lead(lead_com_historico, db) is True

    db.expire_all()
    assert lead_service.get_lead(lead_com_historico, db) is None
    assert lead_service.count_messages(lead_com_historico, db) == 0
    assert (
        db.query(Agendamento).filter(Agendamento.lead_id == lead_com_historico).count()
        == 0
    )
    assert (
        db.query(FollowUpAttempt)
        .filter(FollowUpAttempt.lead_id == lead_com_historico).count()
        == 0
    )
    assert (
        db.query(LeadChannelIdentity)
        .filter(LeadChannelIdentity.lead_id == lead_com_historico).count()
        == 0
    )


def test_excluir_lead_preserva_o_consumo_de_llm(lead_service, lead_com_historico, db):
    """Os tokens foram gastos de verdade: apagar o lead nao pode zerar o budget."""
    lead_service.delete_lead(lead_com_historico, db)

    db.expire_all()
    assert LLMUsageService().get_daily_tokens(db) == 150
    assert db.query(LLMUsage).filter(LLMUsage.lead_id.is_(None)).count() == 1


def test_excluir_lead_inexistente_devolve_falso(lead_service, db):
    assert lead_service.delete_lead(999999, db) is False


# --- Listagem de conversas do simulador --------------------------------------


def _conversa(lead_service, db, external_id, mensagens):
    lead = lead_service.get_or_create_lead(
        channel="streamlit", external_id=external_id, db=db
    )
    for texto in mensagens:
        lead_service.save_message(
            lead_id=lead.id, channel="streamlit", role="user",
            content=texto, message_type="chat", db=db,
        )
    return lead.id


def test_lista_conversas_de_todos_os_usuarios_e_canais(lead_service, db):
    """Filtrar pelo prefixo do usuario deixava a lista visivelmente incompleta."""
    da_ana = _conversa(lead_service, db, "streamlit_ana_aaa111", ["oi"])
    do_bob = _conversa(lead_service, db, "streamlit_bob_bbb222", ["ola", "tudo bem?"])

    ids = [c.lead_id for c in lead_service.list_conversations(db)]

    assert set(ids) == {da_ana, do_bob}


def test_conversas_vem_da_mais_recente_para_a_mais_antiga(lead_service, db):
    primeira = _conversa(lead_service, db, "streamlit_ana_aaa111", ["oi"])
    segunda = _conversa(lead_service, db, "streamlit_ana_bbb222", ["ola"])

    ids = [c.lead_id for c in lead_service.list_conversations(db)]

    assert ids == [segunda, primeira]


def test_lead_sem_mensagem_fica_fora_da_lista(lead_service, db):
    """Abrir o chat cria a tela, nao a conversa: lead vazio nao e conversa."""
    lead_service.get_or_create_lead(
        channel="streamlit", external_id="streamlit_ana_vazio", db=db
    )

    assert lead_service.list_conversations(db) == []


def test_rotulo_da_conversa_traz_o_que_identifica(lead_service, db):
    lead_id = _conversa(lead_service, db, "streamlit_ana_aaa111", ["oi", "ola"])

    rotulo = lead_service.list_conversations(db)[0].rotulo()

    assert f"Lead #{lead_id}" in rotulo
    assert "2 msgs" in rotulo
    assert "streamlit" in rotulo
