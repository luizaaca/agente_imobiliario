"""Geração contextual da mensagem de follow-up.

Agente separado do SDR conversacional: aqui não há tools nem histórico, só a
redação de uma única mensagem a partir do estado atual do lead. Manter os dois
separados evita que o follow-up dispare buscas ou agendamentos por conta
própria, e mantém o custo do job previsível.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic_ai import Agent

from src.agent.prompts import FOLLOWUP_INSTRUCOES, FOLLOWUP_SYSTEM_PROMPT
from src.agent.provider import build_model

logger = logging.getLogger(__name__)

followup_agent = Agent(system_prompt=FOLLOWUP_SYSTEM_PROMPT, retries=2)


@dataclass
class FollowUpGerado:
    """Mensagem de follow-up produzida pelo LLM, com o custo do turno."""
    texto: str
    tokens_in: int
    tokens_out: int


def _linha(rotulo: str, valor: Any) -> Optional[str]:
    return f"- {rotulo}: {valor}" if valor not in (None, "", "?") else None


def build_followup_prompt(
    contexto: Dict[str, Any], regua: str, tentativa: int
) -> str:
    """Monta o prompt do follow-up a partir do contexto do lead.

    O contexto é um dicionário simples (não o objeto ORM) para que a geração
    não dependa de uma sessão de banco aberta.
    """
    campos = [
        _linha("Nome", contexto.get("nome")),
        _linha("Intenção", contexto.get("intencao")),
        _linha("Orçamento máximo", contexto.get("orcamento_max")),
        _linha("Bairro de interesse", contexto.get("bairro_interesse")),
        _linha("Região de interesse", contexto.get("regiao_interesse")),
        _linha("Quartos", contexto.get("quartos")),
        _linha("Urgência", contexto.get("urgencia")),
        _linha("Motivo da busca", contexto.get("motivo_busca")),
    ]
    dados = "\n".join(c for c in campos if c) or "- Nenhum dado coletado ainda."

    partes = [
        f"## Situação\n{FOLLOWUP_INSTRUCOES[regua]}",
        f"Esta é a tentativa {tentativa} de contato. "
        f"Quanto maior a tentativa, mais leve e mais curta deve ser a mensagem.",
        f"## O que o lead já informou\n{dados}",
    ]

    perfil = contexto.get("perfil_narrativo")
    if perfil:
        partes.append(f"## Perfil narrativo\n{perfil}")

    ultima = contexto.get("ultima_mensagem")
    if ultima:
        partes.append(f"## Última mensagem trocada\n{ultima}")

    agendamento = contexto.get("agendamento")
    if agendamento:
        partes.append(f"## Agendamento\n{agendamento}")

    partes.append("Escreva agora a mensagem de follow-up.")
    return "\n\n".join(partes)


async def gerar_mensagem_followup(
    contexto: Dict[str, Any], regua: str, tentativa: int
) -> FollowUpGerado:
    """Gera o texto do follow-up para a régua informada."""
    prompt = build_followup_prompt(contexto, regua, tentativa)

    result = await followup_agent.run(user_prompt=prompt, model=build_model())
    usage = result.usage

    return FollowUpGerado(
        texto=(result.output or "").strip(),
        tokens_in=usage.input_tokens or 0,
        tokens_out=usage.output_tokens or 0,
    )
