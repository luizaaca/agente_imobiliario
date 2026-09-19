"""Alinhamento entre os schemas Pydantic e o ORM.

Os schemas eram documentacao que ninguem executava, e por isso tinham
divergido do banco: `ImovelBase` falava em `iptu`, `area_util` e `vagas` onde a
tabela tem `iptu_anual`, `area_m2` e `vaga_garagem`; `MensagemResponse` e
`AgendamentoResponse` exigiam um `updated_at` que nao existe. Estes testes
fecham esse caminho: qualquer campo que sobrar ou faltar quebra a suite.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.db.models import Agendamento, Imovel, Lead, Mensagem
from src.schemas import (
    AgendamentoResponse,
    ImovelResponse,
    LeadResponse,
    MensagemResponse,
)

PARES = [
    (ImovelResponse, Imovel),
    (LeadResponse, Lead),
    (MensagemResponse, Mensagem),
    (AgendamentoResponse, Agendamento),
]


@pytest.mark.parametrize(
    "schema,modelo", PARES, ids=lambda x: getattr(x, "__name__", str(x))
)
def test_todo_campo_do_schema_existe_como_coluna(schema, modelo):
    colunas = {c.name for c in modelo.__table__.columns}
    faltando = set(schema.model_fields) - colunas
    assert not faltando, (
        f"{schema.__name__} declara campos que {modelo.__tablename__} nao tem: "
        f"{sorted(faltando)}"
    )


def test_resposta_de_imovel_valida_uma_linha_real(db, catalogo):
    imovel = db.query(Imovel).first()
    resposta = ImovelResponse.model_validate(imovel)
    assert resposta.id == imovel.id
    assert resposta.area_m2 == imovel.area_m2
    assert resposta.operacao == imovel.operacao


def test_resposta_de_lead_valida_uma_linha_real(db):
    lead = Lead(status="novo", score=Decimal("3.5"), intencao="compra")
    db.add(lead)
    db.commit()

    resposta = LeadResponse.model_validate(lead)
    assert resposta.id == lead.id
    assert resposta.score == Decimal("3.5")


def test_resposta_de_mensagem_valida_uma_linha_real(db):
    lead = Lead(status="novo")
    db.add(lead)
    db.flush()
    msg = Mensagem(
        lead_id=lead.id,
        channel="streamlit",
        role="user",
        message_type="chat",
        content="oi",
        status="created",
    )
    db.add(msg)
    db.commit()

    resposta = MensagemResponse.model_validate(msg)
    assert resposta.content == "oi"
    assert resposta.sent_at is None


def test_resposta_de_agendamento_valida_uma_linha_real(db, catalogo):
    lead = Lead(status="novo")
    db.add(lead)
    db.flush()
    imovel = db.query(Imovel).first()
    agendamento = Agendamento(
        lead_id=lead.id,
        imovel_id=imovel.id,
        tipo="visita",
        data_hora=datetime(2026, 10, 1, 15, 0, tzinfo=UTC),
        status="pendente",
    )
    db.add(agendamento)
    db.commit()

    resposta = AgendamentoResponse.model_validate(agendamento)
    assert resposta.imovel_id == imovel.id
    assert resposta.status.value == "pendente"
