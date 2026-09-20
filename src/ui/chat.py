"""Interface de chat simulador do agente SDR."""
import asyncio
import uuid

import streamlit as st

from src.agent.provider import configuracao_ausente
from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.session import get_db
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService
from src.ui.navegacao import conversa_pedida
from src.ui.texto import markdown_seguro

CANAL = "streamlit"
# Quantas mensagens a tela mostra ao retomar uma conversa. E so exibicao: o que
# vai para o modelo e limitado a parte por HISTORY_LIMIT.
LIMITE_EXIBIDO = 100


def _prefixo_do_usuario() -> str:
    return f"streamlit_{st.session_state.get('username', 'demo')}_"


def _historico_visivel(lead_id: int, db) -> list[dict]:
    """Mensagens do lead prontas para o `st.chat_message` (sem system/tool)."""
    return [
        {"role": m.role, "content": m.content}
        for m in LeadService().get_history(lead_id, LIMITE_EXIBIDO, db)
        if m.role in ("user", "assistant")
    ]


def abrir_conversa(lead_id: int) -> None:
    """Carrega no simulador a conversa de um lead existente."""
    with get_db() as db:
        st.session_state.messages = _historico_visivel(lead_id, db)
    st.session_state.lead_id = lead_id


def nova_conversa() -> None:
    """Zera a tela para comecar do zero.

    O lead so nasce no primeiro envio: abrir uma conversa em branco nao deve
    encher o painel do corretor de leads vazios.
    """
    st.session_state.lead_id = None
    st.session_state.messages = []


def _retomar_ultima_conversa() -> None:
    """Reabre a conversa mais recente deste usuario (ex.: apos um refresh)."""
    with get_db() as db:
        identidade = LeadService().get_latest_identity_by_prefix(
            CANAL, _prefixo_do_usuario(), db
        )
        if identidade is None:
            nova_conversa()
            return
        st.session_state.lead_id = identidade.lead_id
        st.session_state.messages = _historico_visivel(identidade.lead_id, db)


def _garantir_lead() -> int:
    """Cria o lead da conversa no primeiro envio, se ainda nao existir.

    Cada conversa recebe um external_id proprio. Sem isso todas as conversas do
    mesmo usuario colapsavam em um unico lead no painel.
    """
    if st.session_state.lead_id is None:
        with get_db() as db:
            lead = LeadService().get_or_create_lead(
                channel=CANAL,
                external_id=f"{_prefixo_do_usuario()}{uuid.uuid4().hex[:8]}",
                db=db,
            )
            st.session_state.lead_id = lead.id
    return st.session_state.lead_id


def _opcoes_de_conversa(lead_aberto: int | None) -> list[tuple[int | None, str]]:
    """(lead_id, rotulo) de cada conversa, da mais recente para a mais antiga.

    A lista vem de `list_conversations`, que nao filtra por canal nem por
    usuario: antes o seletor so enxergava as conversas iniciadas por este
    usuario no Streamlit e aparecia visivelmente incompleto.
    """
    with get_db() as db:
        servico = LeadService()
        conversas = servico.list_conversations(db)
        opcoes: list[tuple[int | None, str]] = [
            (c.lead_id, c.rotulo()) for c in conversas
        ]

        if lead_aberto is None:
            opcoes.insert(0, (None, "Nova conversa (ainda sem lead)"))
        elif lead_aberto not in {c.lead_id for c in conversas}:
            # Lead criado mas ainda sem mensagem nenhuma.
            lead = servico.get_lead(lead_aberto, db)
            if lead is not None:
                opcoes.insert(0, (lead.id, f"Lead #{lead.id} · {lead.status}"))

    return opcoes


def _resumo_do_lead() -> None:
    if st.session_state.lead_id is None:
        st.caption("O lead é criado ao enviar a primeira mensagem.")
        return

    with get_db() as db:
        lead = LeadService().get_lead(st.session_state.lead_id, db)
        if lead is None:
            st.caption("Lead removido. Comece uma nova conversa.")
            return
        score = lead.score if lead.score is not None else "N/A"
        st.caption(f"**Lead #{lead.id}** · {lead.status} · score {score}")


def _painel_da_conversa() -> None:
    """Seletor de conversa, botao de nova e resumo do lead aberto.

    Fica no corpo da pagina, e nao na barra lateral: pertence ao chat, e a
    barra lateral e da navegacao entre paginas.
    """
    atual = st.session_state.lead_id
    opcoes = _opcoes_de_conversa(atual)
    ids = [lead_id for lead_id, _ in opcoes]
    rotulos = dict(opcoes)

    col_sel, col_nova, col_info = st.columns([5, 2, 4], vertical_alignment="bottom")

    with col_sel:
        # A chave carrega o lead aberto de proposito. Um selectbox mantem o
        # valor escolhido enquanto a chave nao muda — inclusive sem `key`
        # explicita, que o Streamlit gera internamente — e esse valor vence o
        # `index`. Com chave fixa, abrir uma conversa pelo painel virava um
        # widget desatualizado que devolvia o lead anterior no rerun seguinte.
        escolhido = st.selectbox(
            "Conversa",
            ids,
            index=ids.index(atual) if atual in ids else 0,
            format_func=lambda i: rotulos[i],
            key=f"seletor_conversa_{atual}",
        )

    with col_nova:
        nova = st.button("➕ Nova conversa", width="stretch")

    with col_info:
        _resumo_do_lead()

    if escolhido != st.session_state.lead_id and escolhido is not None:
        abrir_conversa(escolhido)
        st.rerun()

    if nova:
        nova_conversa()
        st.rerun()


def _aviso_de_configuracao() -> list[str]:
    """Avisa na tela o que falta configurar e devolve a lista.

    A aplicação sobe de propósito sem configuração de LLM — dá para navegar
    pelo catálogo e pelo painel. Só o chat depende dela, e quem chega aqui
    precisa saber disso antes de tentar conversar, não depois.
    """
    faltando = configuracao_ausente()
    if not faltando:
        return faltando

    variaveis = ", ".join(f"`{nome}`" for nome in faltando)
    plural = "as variáveis" if len(faltando) > 1 else "a variável"
    st.warning(
        f"**Configuração de LLM incompleta** — o chat está desativado.\n\n"
        f"Falta preencher {plural} {variaveis}. Copie `.env.example` para "
        f"`.env`, preencha e suba de novo com `docker compose up`.\n\n"
        f"O dashboard e o catálogo de imóveis funcionam normalmente sem isso.",
        icon="⚙️",
    )
    return faltando


def render_chat():
    st.header("💬 Chat com o Agente SDR")
    st.caption("Simule uma conversa como lead imobiliário")
    faltando = _aviso_de_configuracao()

    if "lead_id" not in st.session_state:
        _retomar_ultima_conversa()

    # O dashboard pode ter pedido para abrir a conversa de um lead especifico.
    pedido = conversa_pedida()
    if pedido is not None and pedido != st.session_state.lead_id:
        abrir_conversa(pedido)

    _painel_da_conversa()
    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(markdown_seguro(msg["content"]))

    # Desabilitado quando falta configuração: deixar o campo ativo só levaria
    # o usuário a mandar uma mensagem e receber "atendimento indisponível".
    entrada = st.chat_input(
        "Configure o LLM para conversar" if faltando else "Digite sua mensagem...",
        disabled=bool(faltando),
    )
    if prompt := entrada:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(markdown_seguro(prompt))

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                lead_id = _garantir_lead()
                deps = SDRDependencies(
                    lead_id=lead_id,
                    channel=CANAL,
                    lead_service=LeadService(),
                    catalog_service=CatalogService(),
                    scheduling_service=SchedulingService(),
                    llm_usage_service=LLMUsageService(),
                )
                response = asyncio.run(
                    process_message(
                        lead_id=lead_id,
                        user_text=prompt,
                        channel=CANAL,
                        deps=deps,
                    )
                )
                st.markdown(markdown_seguro(response))

        st.session_state.messages.append({"role": "assistant", "content": response})
        # Rerun para o painel refletir o lead recem-criado e a contagem de
        # mensagens atualizada.
        st.rerun()
