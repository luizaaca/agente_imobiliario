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
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from src.db.models import Mensagem

# Quantas falas do histórico reidratar por turno. O teto existe para
# controlar custo: cada mensagem reenviada é cobrada como token de entrada.
# Conta só `user` e `assistant`; as linhas de ferramenta entram de carona na
# janela que elas delimitam (ver `LeadService.get_history`).
HISTORY_LIMIT = 20

# Quanto de um retorno de ferramenta volta ao contexto nos turnos seguintes.
# Uma busca devolve uns 3.000 caracteres, e reenviar isso inteiro a cada turno
# multiplicaria o custo — foi um turno de 15.000 tokens que estourou o teto de
# uma conversa. O começo é o que interessa: ali vêm o cabeçalho e os primeiros
# imóveis, com título e ID, que é o que faz o agente reconhecer o que já
# mostrou.
LIMITE_DO_RETORNO_DE_TOOL = 900

_TRUNCADO = "\n[...] (resultado abreviado no histórico)"


def _retorno_abreviado(conteudo: str) -> str:
    if len(conteudo) <= LIMITE_DO_RETORNO_DE_TOOL:
        return conteudo
    return conteudo[:LIMITE_DO_RETORNO_DE_TOOL] + _TRUNCADO


def _par_de_ferramenta(msg: Mensagem, conteudo: str) -> list[ModelMessage]:
    """A chamada e o retorno de uma ferramenta, como o modelo os viu.

    Vão sempre juntos e nesta ordem: o provider rejeita um retorno solto e
    rejeita uma chamada sem resposta. O `tool_call_id` é o que amarra os dois,
    por isso é persistido junto em `metadata_json`.
    """
    meta = msg.metadata_json or {}
    nome = meta.get("tool_name") or "ferramenta"
    chamada_id = meta.get("tool_call_id") or f"historico-{msg.id}"

    return [
        ModelResponse(parts=[ToolCallPart(
            tool_name=nome, args=meta.get("args") or {}, tool_call_id=chamada_id,
        )]),
        ModelRequest(parts=[ToolReturnPart(
            tool_name=nome, content=conteudo, tool_call_id=chamada_id,
        )]),
    ]


def build_message_history(mensagens: Iterable[Mensagem]) -> list[ModelMessage]:
    """Converte mensagens persistidas (em ordem cronológica) para o PydanticAI.

    Entram `user`, `assistant` e `tool`. As instruções do agente não vêm daqui:
    o pydantic-ai as reaplica a cada run (por isso são `@instructions`, e não
    `@system_prompt` — este último só entraria se o histórico chegasse vazio).

    As linhas de ferramenta existem porque sem elas o agente não tem como saber
    o que já fez. Os IDs dos imóveis só aparecem no retorno da busca, nunca no
    texto que ele escreve para a pessoa; sem persistir isso, ele reapresentava
    o mesmo imóvel sem perceber que era o mesmo.
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
        elif msg.role == "tool":
            history.extend(_par_de_ferramenta(msg, _retorno_abreviado(conteudo)))

    return history
