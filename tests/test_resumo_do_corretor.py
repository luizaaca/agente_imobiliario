"""O briefing executivo que o corretor lê antes de ligar.

O compromisso não aponta mais para um imóvel: o que será visitado mora na
`observacoes` dele. Junto do perfil narrativo, é o que orienta o corretor —
e por isso precisa estar aqui, e não só na aba de agendamentos. Sem isto o
resumo afirmava que havia visita marcada sem dizer para ver o quê.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.services.lead_service import LeadService
from src.services.scheduling_service import SchedulingService
from src.services.summary_service import SummaryService

PARA_VER = "Quer ver os imóveis 142 (Mooca) e 144 (Tatuapé); vai com o marido."


@pytest.fixture
def resumo():
    return SummaryService()


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="resumo-001", db=db, nome="Helena"
    ).id


@pytest.fixture
def amanha():
    return datetime.now(UTC) + timedelta(days=1)


def test_o_resumo_diz_quando_e_o_compromisso(resumo, lead_id, amanha, db):
    SchedulingService().create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db
    )

    texto = resumo.generate_resumo(lead_id, db)

    assert "Compromisso marcado" in texto
    assert "visita" in texto


def test_o_resumo_diz_o_que_ela_quer_ver(resumo, lead_id, amanha, db):
    """É o único lugar do briefing onde os imóveis aparecem, e com ID."""
    SchedulingService().create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db,
        observacoes=PARA_VER,
    )

    texto = resumo.generate_resumo(lead_id, db)

    assert PARA_VER in texto


def test_sem_compromisso_nao_ha_secao(resumo, lead_id, db):
    """Uma seção vazia faz o corretor procurar o que não existe."""
    assert "Compromisso marcado" not in resumo.generate_resumo(lead_id, db)


def test_compromisso_cancelado_sai_do_resumo(resumo, lead_id, amanha, db):
    """O corretor não sai de casa por causa de uma visita desmarcada."""
    agendamento = SchedulingService().create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db,
        observacoes=PARA_VER,
    )
    SchedulingService().update_status(agendamento.id, "cancelado", db)

    texto = resumo.generate_resumo(lead_id, db)

    assert "Compromisso marcado" not in texto
    assert PARA_VER not in texto


def test_o_resumo_segue_trazendo_o_perfil_narrativo(resumo, lead_id, amanha, db):
    """O compromisso entra ao lado do perfil, e não no lugar dele."""
    LeadService().update_perfil_narrativo(
        lead_id, "Psicóloga, atende em casa; precisa de um quarto silencioso.", db
    )
    SchedulingService().create(
        lead_id=lead_id, tipo="visita", data_hora=amanha, db=db, observacoes=PARA_VER
    )

    texto = resumo.generate_resumo(lead_id, db)

    assert "atende em casa" in texto
    assert PARA_VER in texto
