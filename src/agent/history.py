"""Conversão do histórico persistido para o formato de mensagens do PydanticAI.

As mensagens ficam em `mensagens` (tabela própria, fonte de verdade da
conversa). A cada turno, os últimos turnos são reidratados e passados como
`message_history`, para que o agente enxergue o contexto recente sem depender
de estado em memória — o que é essencial porque Streamlit e Telegram rodam em
processos diferentes.
"""

from collections.abc import Iterable

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from src.db.models import Mensagem

# Quantas mensagens do histórico reidratar por turno. O teto existe para
# controlar custo: cada mensagem reenviada é cobrada como token de entrada.
HISTORY_LIMIT = 20


def build_message_history(mensagens: Iterable[Mensagem]) -> list[ModelMessage]:
    """Converte mensagens persistidas (em ordem cronológica) para o PydanticAI.

    Apenas `user` e `assistant` entram: o system prompt é remontado a cada run
    pelo prompt dinâmico, e mensagens de tool são reconstruídas pelo próprio
    agente quando necessário.
    """
    history: list[ModelMessage] = []

    for msg in mensagens:
        conteudo = (msg.content or "").strip()
        if not conteudo:
            continue

        if msg.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=conteudo)]))
        elif msg.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=conteudo)]))

    return history
