"""Uma conversa na tela, com o que aconteceu por baixo dela.

As falas do lead e do agente são o que interessa a quem lê. O que o agente fez
entre uma e outra — buscar, registrar, marcar — fica recolhido num painel por
chamada, fechado, ao lado da fala que aquilo produziu.

A busca é a que mais precisa disso. O agente de busca escreve SQL e consulta o
catálogo quantas vezes precisar, e nada dessas consultas vira mensagem: elas só
existem no `metadata_json` da chamada. Sem um lugar para vê-las, "como ele achou
esses imóveis" só se responde com um `psql` aberto.

Serve à ficha do corretor e ao simulador, e o que cada um desenha depende de
quem está olhando: os painéis de ferramenta e o custo da conversa são do
`admin`, e a tela do corretor fica só com o diálogo. O bot do Telegram não
passa por aqui — o que a pessoa recebe lá é só a resposta final do agente.
"""

from dataclasses import dataclass, field
from typing import Optional

import streamlit as st

from src.config import settings
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.ui.texto import markdown_seguro, mensagem_para_markdown

# Rótulo para as falas que não nasceram de uma pergunta da pessoa.
ROTULO_DO_TIPO = {
    "followup": ":material/autorenew: follow-up automático",
    "handover": ":material/handshake: handover ao corretor",
    "system_notice": ":material/settings: aviso do sistema",
}

# Ícone de cada ferramenta, para o painel ser reconhecível fechado.
ICONE_DA_TOOL = {
    "buscar_imoveis": ":material/search:",
    "detalhar_imoveis": ":material/description:",
    "registrar_qualificacao": ":material/edit_note:",
    "atualizar_perfil_lead": ":material/person:",
    "agendar_reuniao": ":material/event:",
    "listar_agendamentos": ":material/calendar_month:",
    "confirmar_agendamento": ":material/check_circle:",
    "cancelar_agendamento": ":material/cancel:",
    "encerrar_atendimento": ":material/flag:",
}
ICONE_PADRAO = ":material/build:"

PAPEIS_DA_CONVERSA = ("user", "assistant")


@dataclass(frozen=True)
class Fala:
    """Uma linha da conversa, já desligada do ORM.

    Os campos são copiados dentro da sessão de banco de propósito: acessar um
    atributo de objeto do SQLAlchemy depois do `close` levanta
    `DetachedInstanceError`, e a renderização acontece bem depois.
    """

    role: str
    conteudo: str
    tipo: Optional[str] = None
    meta: dict = field(default_factory=dict)

    @property
    def e_ferramenta(self) -> bool:
        return self.role == "tool"


def falas_do_lead(lead_id: int, db, limite: int) -> list[Fala]:
    """A conversa do lead pronta para a tela, com as chamadas de ferramenta."""
    return [
        Fala(
            role=m.role,
            conteudo=m.content or "",
            tipo=m.message_type,
            meta=m.metadata_json or {},
        )
        for m in LeadService().get_history(lead_id, limite, db)
        if m.role in (*PAPEIS_DA_CONVERSA, "tool")
    ]


def quantas_falas(falas: list[Fala]) -> int:
    """Só o que a pessoa e o agente disseram — ferramenta não é mensagem."""
    return sum(1 for f in falas if f.role in PAPEIS_DA_CONVERSA)


def falas_visiveis(falas: list[Fala], bastidores: bool) -> list[Fala]:
    """As falas que esta tela desenha.

    Sem bastidores sobra o diálogo. O SQL que o agente de busca escreveu e o
    texto cru que cada ferramenta devolveu ao modelo são informação de quem
    constrói o agente — na ficha do corretor eles só afastam uma fala da
    seguinte.
    """
    return falas if bastidores else [f for f in falas if not f.e_ferramenta]


def legenda_da_conversa(falas: list[Fala], bastidores: bool) -> str:
    """A linha acima da conversa, dizendo o tamanho dela.

    A dica sobre os painéis só aparece para quem tem painéis: prometer ao
    corretor uma ferramenta que a tela dele não desenha é pior do que não
    dizer nada.
    """
    legenda = f"{quantas_falas(falas)} mensagem(ns)"
    if bastidores:
        legenda += " — as ferramentas que o agente usou abrem nos painéis"
    return legenda


def custo_da_conversa(lead_id: int, db, bastidores: bool) -> str:
    """O que esta conversa já consumiu, sobre o teto que a encerra.

    Vazio para quem não vê os bastidores, e sem ida ao banco: custo em dólar
    do provider é informação de quem opera a aplicação, não de quem atende
    leads, e quem chama isto na tela não precisa relembrar a regra.

    O denominador não é enfeite. Atingido o teto de tokens por conversa, o
    atendimento é entregue ao corretor na hora, no meio da frase — sem ele, o
    número diz quanto gastou e não diz o quanto falta.
    """
    if not bastidores:
        return ""

    servico = LLMUsageService()
    tokens = servico.get_conversation_tokens(lead_id, db)
    teto = settings.LLM_MAX_TOKENS_PER_CONVERSATION
    custo = servico.get_conversation_cost(lead_id, db)
    return (
        f"{tokens:,} / {teto:,} tokens".replace(",", ".")
        + f" · US$ {custo:.4f} estimados"
    )


def renderizar(falas: list[Fala], bastidores: bool = True) -> None:
    """Desenha a conversa na ordem em que aconteceu."""
    for fala in falas_visiveis(falas, bastidores):
        if fala.e_ferramenta:
            _painel_da_ferramenta(fala)
            continue
        with st.chat_message(fala.role):
            if rotulo := ROTULO_DO_TIPO.get(fala.tipo):
                st.caption(rotulo)
            st.markdown(mensagem_para_markdown(fala.conteudo))


def _painel_da_ferramenta(fala: Fala) -> None:
    """Uma chamada de ferramenta, fechada, com tudo que ela produziu."""
    nome = fala.meta.get("tool_name") or "ferramenta"
    busca = fala.meta.get("busca") or {}
    consultas = busca.get("consultas") or []

    with st.expander(
        _titulo_da_ferramenta(nome, consultas, busca),
        icon=ICONE_DA_TOOL.get(nome, ICONE_PADRAO),
    ):
        if argumentos := fala.meta.get("args"):
            st.caption("O que o agente pediu")
            for chave, valor in argumentos.items():
                st.markdown(f"**{chave}:** {markdown_seguro(str(valor))}")

        if consultas:
            st.caption(f"{len(consultas)} consulta(s) ao catálogo")
            for sql in consultas:
                st.code(sql, language="sql")

        st.caption("O que a ferramenta devolveu ao agente")
        # `st.code` em vez de markdown: aqui o valor é ver o texto exatamente
        # como o modelo o leu, com a formatação crua à mostra.
        st.code(fala.conteudo, language=None, wrap_lines=True)


def _titulo_da_ferramenta(nome: str, consultas: list, busca: dict) -> str:
    """O nome da ferramenta e, quando houver, o que ela custou."""
    partes = [f"`{nome}`"]
    if consultas:
        partes.append(f"{len(consultas)} consulta(s)")
    entrada, saida = busca.get("tokens_in"), busca.get("tokens_out")
    if entrada or saida:
        partes.append(f"{entrada or 0} → {saida or 0} tokens")
    return " · ".join(partes)
