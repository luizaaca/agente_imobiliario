"""O selo de status significa a mesma coisa em toda tela que o desenha.

A lista de Leads e a carteira do dashboard mostram os mesmos leads. Enquanto
cada uma montava a propria celula de status, a carteira ficou sem a cor do
sub-status do agendamento: o mesmo lead saia verde num menu e azul no outro,
e nada no codigo obrigava as duas a concordarem.
"""

from datetime import timedelta

from src.db.models import Agendamento, Lead
from src.services.lead_service import LeadService
from src.tempo import agora
from src.ui.dashboard import _colunas_da_carteira
from src.ui.leads import (
    COR_DO_STATUS,
    COR_DO_STATUS_DE_AGENDAMENTO,
    _colunas_da_lista,
    selo_de_status,
    situacoes_de_agendamento,
)


def celula_de_status(colunas, lead: Lead) -> str:
    """O que a coluna Status daquela tabela desenharia para este lead."""
    coluna = next(c for c in colunas if c.titulo == "Status")
    return coluna.valor(lead)


def lead_agendado(db, status_do_agendamento: str, dias: int = 3) -> Lead:
    lead = LeadService().get_or_create_lead(
        channel="teste", external_id=f"selo-{status_do_agendamento}", db=db
    )
    LeadService().update_status(lead.id, "agendado", db)
    db.add(Agendamento(
        lead_id=lead.id, tipo="visita",
        data_hora=agora() + timedelta(days=dias),
        status=status_do_agendamento,
    ))
    db.commit()
    db.expire_all()
    return LeadService().get_lead(lead.id, db)


# --- A regra de cor ----------------------------------------------------------


def test_sem_agendamento_a_cor_e_a_do_estagio(db):
    lead = LeadService().get_or_create_lead(
        channel="teste", external_id="selo-novo", db=db
    )
    assert COR_DO_STATUS["novo"] in selo_de_status(lead, {})


def test_visita_pendente_pinta_o_selo_de_laranja(db):
    lead = lead_agendado(db, "pendente")
    situacoes = situacoes_de_agendamento([lead], db)

    selo = selo_de_status(lead, situacoes)
    assert COR_DO_STATUS_DE_AGENDAMENTO["pendente"] in selo
    # O texto continua sendo o estagio do funil: a situacao entra so na cor.
    assert "agendado" in selo


def test_visita_confirmada_pinta_o_selo_de_azul(db):
    lead = lead_agendado(db, "confirmado")
    situacoes = situacoes_de_agendamento([lead], db)
    assert COR_DO_STATUS_DE_AGENDAMENTO["confirmado"] in selo_de_status(lead, situacoes)


def test_compromisso_mais_proximo_manda_na_cor(db):
    """Duas visitas marcadas: vale a que acontece primeiro."""
    lead = lead_agendado(db, "confirmado", dias=10)
    db.add(Agendamento(
        lead_id=lead.id, tipo="visita",
        data_hora=agora() + timedelta(days=1), status="pendente",
    ))
    db.commit()

    situacoes = situacoes_de_agendamento([lead], db)
    assert COR_DO_STATUS_DE_AGENDAMENTO["pendente"] in selo_de_status(lead, situacoes)


def test_agendamento_cancelado_nao_colore_o_selo(db):
    """Cancelado nao esta de pe: a cor volta a ser a do estagio."""
    lead = lead_agendado(db, "cancelado")
    situacoes = situacoes_de_agendamento([lead], db)
    assert COR_DO_STATUS["agendado"] in selo_de_status(lead, situacoes)


# --- As duas telas -----------------------------------------------------------


def test_lista_e_carteira_desenham_o_mesmo_selo(db):
    """A regressao que originou este arquivo, em uma linha."""
    lead = lead_agendado(db, "confirmado")
    situacoes = situacoes_de_agendamento([lead], db)

    assert (
        celula_de_status(_colunas_da_lista(situacoes), lead)
        == celula_de_status(_colunas_da_carteira(situacoes), lead)
    )


def test_as_duas_telas_concordam_em_todos_os_estagios(db):
    for status in ("novo", "em_qualificacao", "qualificado", "inativo"):
        lead = LeadService().get_or_create_lead(
            channel="teste", external_id=f"selo-varredura-{status}", db=db
        )
        LeadService().update_status(lead.id, status, db)
        db.expire_all()
        lead = LeadService().get_lead(lead.id, db)

        assert (
            celula_de_status(_colunas_da_lista({}), lead)
            == celula_de_status(_colunas_da_carteira({}), lead)
        ), status
