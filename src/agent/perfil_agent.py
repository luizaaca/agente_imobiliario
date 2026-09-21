"""Consolidação do perfil narrativo do lead.

O perfil é o artefato que o corretor lê antes de ligar, e ele cresce ao longo
da conversa. Quem observa a conversa é o agente SDR; quem escreve o perfil é
este agente, que recebe o texto que já existe e a novidade do turno e devolve
os dois fundidos num texto só.

A separação é o que garante que o perfil não encolha. O SDR relata apenas o
que acabou de descobrir e nunca reescreve o que já estava gravado, então não
tem como deixar nada para trás. E este agente não tem tools nem histórico de
conversa — recebe dois textos e devolve um —, o que mantém a chamada barata e
o resultado previsível.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from pydantic_ai import Agent

from src.agent.prompts import PERFIL_SYSTEM_PROMPT
from src.agent.provider import build_model

logger = logging.getLogger(__name__)

perfil_agent = Agent(system_prompt=PERFIL_SYSTEM_PROMPT, retries=2)

SEM_PERFIL = "Ainda não há perfil registrado — esta é a primeira anotação."


@dataclass
class PerfilConsolidado:
    """Perfil reescrito pelo LLM, com o custo da chamada."""
    texto: str
    tokens_in: int
    tokens_out: int


def build_perfil_prompt(perfil_atual: Optional[str], novidades: str) -> str:
    """Monta o prompt da consolidação: o que existe e o que chegou."""
    atual = (perfil_atual or "").strip() or SEM_PERFIL
    return (
        f"## Perfil atual\n{atual}\n\n"
        f"## O que a conversa acabou de revelar\n{novidades.strip()}\n\n"
        "Escreva agora o perfil consolidado."
    )


def juntar_sem_llm(perfil_atual: Optional[str], novidades: str) -> str:
    """Emenda a novidade ao fim do perfil, sem reescrever nada.

    É o caminho de degradação de `consolidar_perfil`: se o provider estiver
    fora do ar, o dado que a pessoa acabou de contar precisa chegar ao corretor
    de algum jeito. Um perfil com emenda visível é pior de ler que um perfil
    consolidado, e muito melhor que um perfil sem a informação.
    """
    atual = (perfil_atual or "").strip()
    novo = novidades.strip()
    return f"{atual}\n\n{novo}" if atual else novo


async def consolidar_perfil(
    perfil_atual: Optional[str], novidades: str
) -> PerfilConsolidado:
    """Funde a novidade ao perfil atual e devolve o texto resultante.

    Levanta exceção se o provider falhar ou devolver texto vazio — gravar
    vazio apagaria o perfil inteiro, que é exatamente o que este agente existe
    para impedir.
    """
    result = await perfil_agent.run(
        user_prompt=build_perfil_prompt(perfil_atual, novidades),
        model=build_model(),
    )
    texto = (result.output or "").strip()
    if not texto:
        raise ValueError("consolidação devolveu texto vazio")

    usage = result.usage
    return PerfilConsolidado(
        texto=texto,
        tokens_in=usage.input_tokens or 0,
        tokens_out=usage.output_tokens or 0,
    )
