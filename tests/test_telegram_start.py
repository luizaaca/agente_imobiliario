"""O /start do Telegram abre a conversa pelo agente.

Os objetos do python-telegram-bot são imutáveis. O fake da mensagem também é,
para que um handler que tente reescrever `message.text` quebre aqui do mesmo
jeito que quebra no bot de verdade.
"""

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from src.channels import telegram_bot
from src.db.models import Lead


@dataclass(frozen=True)
class _Mensagem:
    text: str
    respostas: list = field(default_factory=list)

    async def reply_text(self, texto):
        self.respostas.append(texto)


class _Chat:
    id = 777001

    async def send_action(self, acao):
        pass


def _update(texto):
    return SimpleNamespace(
        effective_chat=_Chat(),
        effective_user=SimpleNamespace(full_name="Rita Almeida"),
        message=_Mensagem(text=texto),
    )


@pytest.fixture
def agente_fake(monkeypatch):
    """Troca o agente por um que anota o que recebeu."""
    recebido = []

    async def process_message(lead_id, user_text, channel, deps):
        recebido.append(user_text)
        return "Olá! Eu sou a Marina."

    monkeypatch.setattr(telegram_bot, "process_message", process_message)
    return recebido


def test_start_responde_pelo_agente(db, agente_fake):
    update = _update("/start")

    asyncio.run(telegram_bot.start_handler(update, None))

    assert agente_fake == [telegram_bot.SAUDACAO_DO_START]
    assert update.message.respostas == ["Olá! Eu sou a Marina."]


def test_start_cria_o_lead_com_o_nome(db, agente_fake):
    asyncio.run(telegram_bot.start_handler(_update("/start"), None))

    lead = db.query(Lead).filter(Lead.nome == "Rita Almeida").one()
    assert lead.canal_origem == "telegram"


def test_mensagem_comum_chega_ao_agente_como_foi_escrita(db, agente_fake):
    update = _update("quero um 2 quartos na Mooca")

    asyncio.run(telegram_bot.message_handler(update, None))

    assert agente_fake == ["quero um 2 quartos na Mooca"]
    assert update.message.respostas == ["Olá! Eu sou a Marina."]


def test_mensagem_comum_tambem_cria_o_lead_com_o_nome(db, agente_fake):
    """O Telegram só manda /start na primeira vez que o chat é aberto.

    Com o lead excluído, a pessoa volta a escrever no mesmo chat sem /start, e
    o lead novo nascia sem nome — a Marina pedia o que o perfil já dizia.
    """
    asyncio.run(telegram_bot.message_handler(_update("oi"), None))

    lead = db.query(Lead).filter(Lead.nome == "Rita Almeida").one()
    assert lead.canal_origem == "telegram"


def test_nome_do_perfil_nao_sobrescreve_o_que_a_pessoa_disse(db, agente_fake):
    asyncio.run(telegram_bot.message_handler(_update("oi"), None))
    lead = db.query(Lead).filter(Lead.nome == "Rita Almeida").one()
    lead.nome = "Ritinha"
    db.commit()

    asyncio.run(telegram_bot.message_handler(_update("tudo bem?"), None))

    db.refresh(lead)
    assert lead.nome == "Ritinha"
