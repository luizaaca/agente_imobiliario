"""Interface de chat simulador do agente SDR."""
import asyncio
import uuid

import streamlit as st

from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.session import get_db
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService
from src.ui.navegacao import conversa_pedida

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
    """Reabre a conversa mais recente do usuario (ex.: apos um refresh)."""
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


def _rotulo_da_conversa(lead, total_mensagens: int) -> str:
    return f"Lead #{lead.id} · {lead.status} · {total_mensagens} msgs"


def _conversas_disponiveis(lead_aberto: int | None) -> list[tuple[int | None, str]]:
    """Opcoes do seletor: as conversas deste usuario, da mais recente.

    O lead aberto entra na lista mesmo quando nao nasceu aqui — o corretor pode
    ter chegado nele pelo botao "Abrir no simulador" do painel, e sem isso o
    seletor sumiria justamente na conversa que esta na tela.
    """
    servico = LeadService()
    conversas: list[tuple[int | None, str]] = []

    with get_db() as db:
        vistos: set[int] = set()
        for identidade in servico.list_identities_by_prefix(
            CANAL, _prefixo_do_usuario(), db
        ):
            lead = servico.get_lead(identidade.lead_id, db)
            if lead is None or lead.id in vistos:
                continue  # lead excluido pelo dashboard, ou ja listado
            vistos.add(lead.id)
            conversas.append(
                (lead.id, _rotulo_da_conversa(lead, servico.count_messages(lead.id, db)))
            )

        if lead_aberto is None:
            conversas.insert(0, (None, "Nova conversa (ainda sem lead)"))
        elif lead_aberto not in vistos:
            lead = servico.get_lead(lead_aberto, db)
            if lead is not None:
                total = servico.count_messages(lead.id, db)
                conversas.insert(
                    0, (lead.id, f"{_rotulo_da_conversa(lead, total)} · do painel")
                )

    return conversas


def _barra_lateral() -> None:
    st.subheader("Conversa")

    atual = st.session_state.lead_id
    conversas = _conversas_disponiveis(atual)
    ids = [lead_id for lead_id, _ in conversas]
    rotulos = dict(conversas)

    # A chave carrega o lead aberto de proposito. Um selectbox mantem o valor
    # escolhido enquanto a chave nao muda — inclusive sem `key` explicita, que
    # o Streamlit gera internamente —, e esse valor vence o `index`. Com uma
    # chave fixa, abrir uma conversa pelo painel virava um widget "desatual" que
    # devolvia o lead anterior e desfazia a troca no rerun seguinte. Trocando a
    # chave junto com o lead, o widget e outro e nasce com o `index` correto.
    escolhido = st.selectbox(
        "Trocar de conversa",
        ids,
        index=ids.index(atual) if atual in ids else 0,
        format_func=lambda i: rotulos[i],
        key=f"seletor_conversa_{atual}",
    )
    if escolhido != st.session_state.lead_id and escolhido is not None:
        abrir_conversa(escolhido)
        st.rerun()

    if st.button("➕ Nova conversa", width="stretch"):
        nova_conversa()
        st.rerun()

    st.divider()
    st.subheader("Info do Lead")
    if st.session_state.lead_id is None:
        st.caption("O lead é criado ao enviar a primeira mensagem.")
        return

    with get_db() as db:
        lead = LeadService().get_lead(st.session_state.lead_id, db)
        if lead is None:
            st.caption("Lead removido. Comece uma nova conversa.")
            return
        st.write(f"ID: {lead.id}")
        st.write(f"Status: {lead.status}")
        st.write(f"Score: {lead.score or 'N/A'}")


def render_chat():
    st.header("💬 Chat com o Agente SDR")
    st.caption("Simule uma conversa como lead imobiliário")

    if "lead_id" not in st.session_state:
        _retomar_ultima_conversa()

    # O dashboard pode ter pedido para abrir a conversa de um lead especifico.
    pedido = conversa_pedida()
    if pedido is not None and pedido != st.session_state.lead_id:
        abrir_conversa(pedido)

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Digite sua mensagem..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

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
                st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})
        # Rerun para a barra lateral refletir o lead recem-criado e a contagem
        # de mensagens atualizada.
        st.rerun()

    with st.sidebar:
        _barra_lateral()
