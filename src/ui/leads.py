"""CRUD de leads: a tela de trabalho do corretor.

Duas telas no mesmo menu, alternadas por `st.session_state`: a lista, e a
ficha de um lead. A lista mostra o que se varre de relance — quem atender
primeiro — e a ficha concentra tudo que se faz com um lead: editar, ligar a um
canal, disparar follow-up, ler a conversa e excluir.

O dashboard manda para cá: clicar numa linha lá abre a ficha aqui.
"""

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Optional

import streamlit as st

from src.db.models import Lead
from src.db.session import get_db
from src.scheduler.followup_runner import run_followup_para_lead
from src.services.lead_service import LeadService
from src.services.scheduling_service import SchedulingService
from src.ui.texto import markdown_seguro

# Lead cuja ficha esta aberta. Ausente significa "mostrar a lista"; zero
# significa "ficha em branco", porque nenhum lead tem id 0.
CHAVE_LEAD_ABERTO = "lead_aberto"
# Lead cujo botao de excluir foi clicado, para o segundo clique ser deliberado.
CHAVE_EXCLUSAO = "lead_a_excluir"
# Desfecho do ultimo disparo manual: (lead_id, tipo, texto).
CHAVE_AVISO_FOLLOWUP = "aviso_followup"

FICHA_EM_BRANCO = 0

STATUS = ["novo", "em_qualificacao", "qualificado", "agendado", "inativo"]
INTENCOES = ["compra", "aluguel", "investimento"]
URGENCIAS = ["baixa", "media", "alta"]
# Canais que o agente sabe atender. `streamlit` e o simulador; `telegram` e o
# unico com envio ativo hoje.
CANAIS = ["telegram", "streamlit"]

# A cor acompanha o avanco no funil, e verde fica no melhor desfecho. "primary"
# renderiza vermelho no tema padrao, que leria como erro justamente em
# `agendado`.
COR_DO_STATUS = {
    "novo": "yellow",
    "em_qualificacao": "violet",
    "qualificado": "blue",
    "agendado": "green",
    "inativo": "gray",
}
FAIXAS_DE_SCORE = ((7.0, "red", "quente"), (4.0, "orange", "morno"))
ROTULO_DO_TIPO = {
    "followup": ":material/autorenew: follow-up automático",
    "handover": ":material/handshake: handover ao corretor",
    "system_notice": ":material/settings: aviso do sistema",
}


def abrir_ficha(lead_id: int) -> None:
    """Coloca a ficha deste lead na tela."""
    st.session_state[CHAVE_LEAD_ABERTO] = lead_id


def _voltar_para_a_lista() -> None:
    st.session_state.pop(CHAVE_LEAD_ABERTO, None)
    st.session_state.pop(CHAVE_EXCLUSAO, None)


# --- Formatação compartilhada ------------------------------------------------


def _dinheiro(valor) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def faixa_de_orcamento(lead: Lead) -> str:
    """Orçamento em texto, dizendo qual das duas pontas é conhecida."""
    if lead.orcamento_min is None and lead.orcamento_max is None:
        return "N/I"
    if lead.orcamento_min is None:
        return f"até {_dinheiro(lead.orcamento_max)}"
    if lead.orcamento_max is None:
        return f"a partir de {_dinheiro(lead.orcamento_min)}"
    return f"{_dinheiro(lead.orcamento_min)} a {_dinheiro(lead.orcamento_max)}"


def temperatura(score: float) -> tuple[str, str]:
    """(cor, palavra) da faixa de score — quente, morno ou frio."""
    for piso, cor, palavra in FAIXAS_DE_SCORE:
        if score >= piso:
            return cor, palavra
    return "gray", "frio"


def selos_do_lead(lead: Lead, score: float) -> str:
    """Status, temperatura, intenção e região como selos coloridos."""
    rotulo_status = lead.status.replace("_", " ")
    selos = [f":{COR_DO_STATUS.get(lead.status, 'gray')}-badge[{rotulo_status}]"]

    cor, palavra = temperatura(score)
    selos.append(f":{cor}-badge[{palavra}]")

    if lead.intencao:
        selos.append(f":gray-badge[{lead.intencao}]")
    regiao = lead.regiao_interesse or lead.bairro_interesse
    if regiao:
        selos.append(f":gray-badge[:material/location_on: {regiao}]")
    return " ".join(selos)


# --- Lista -------------------------------------------------------------------


def _filtros(db) -> list[Lead]:
    col_busca, col_status, col_intencao = st.columns(3)
    with col_busca:
        busca = st.text_input(
            "Buscar", placeholder="Nome, bairro, intenção...", type="search"
        )
    with col_status:
        status_filtro = st.selectbox("Status", ["Todos", *STATUS])
    with col_intencao:
        intencao_filtro = st.selectbox("Intenção", ["Todas", *INTENCOES])

    query = db.query(Lead).order_by(Lead.score.desc().nullslast())
    if status_filtro != "Todos":
        query = query.filter(Lead.status == status_filtro)
    if intencao_filtro != "Todas":
        query = query.filter(Lead.intencao == intencao_filtro)
    if busca:
        termo = f"%{busca}%"
        query = query.filter(
            Lead.nome.ilike(termo)
            | Lead.bairro_interesse.ilike(termo)
            | Lead.perfil_narrativo.ilike(termo)
        )
    return query.limit(200).all()


def _cartao_da_lista(lead: Lead) -> None:
    """Uma linha da lista: o que se lê de relance, mais o botão de abrir."""
    score = float(lead.score or 0)
    nome = lead.nome or f"Lead {lead.id}"

    with st.container(border=True):
        col_lead, col_score, col_acao = st.columns(
            [6, 2, 3], vertical_alignment="center"
        )
        with col_lead:
            st.markdown(f"#### {markdown_seguro(nome)}")
            st.markdown(selos_do_lead(lead, score))
        with col_score:
            st.metric("Score", f"{score:.1f}" if lead.score is not None else "—")
        with col_acao:
            # Sem `type="primary"`: repetido em cada linha, o botao preenchido
            # transforma a lista inteira num bloco de cor e nao destaca nada.
            if st.button(
                "Abrir ficha",
                icon=":material/open_in_new:",
                key=f"abrir_ficha_{lead.id}",
                width="stretch",
            ):
                abrir_ficha(lead.id)
                st.rerun()


def _lista(db) -> None:
    col_titulo, col_novo = st.columns([4, 1], vertical_alignment="bottom")
    with col_titulo:
        st.subheader("Carteira de leads")
    with col_novo:
        if st.button("Novo lead", icon=":material/person_add:", width="stretch"):
            abrir_ficha(FICHA_EM_BRANCO)
            st.rerun()

    leads = _filtros(db)
    if not leads:
        st.info("Nenhum lead encontrado com os filtros selecionados.")
        return

    st.caption(f"{len(leads)} lead(s)")
    for lead in leads:
        _cartao_da_lista(lead)


# --- Ficha -------------------------------------------------------------------


def _para_decimal(texto: str) -> Optional[Decimal]:
    """Converte o que foi digitado em número, ou `None` se ficou em branco."""
    texto = (texto or "").strip().replace(".", "").replace(",", ".")
    if not texto:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _indice(opcoes: list[str], valor: Optional[str]) -> int:
    """Posição do valor numa lista que começa com a opção vazia."""
    return opcoes.index(valor) + 1 if valor in opcoes else 0


def _formulario(lead: Optional[Lead]) -> None:
    """Campos da ficha. `lead` é `None` quando se está criando."""
    novo = lead is None

    with st.form("ficha_do_lead"):
        st.markdown("##### Identificação")
        col1, col2 = st.columns(2)
        nome = col1.text_input("Nome", value=(lead.nome if lead else "") or "")
        telefone = col2.text_input(
            "Telefone", value=(lead.telefone if lead else "") or ""
        )

        st.markdown("##### Qualificação")
        col1, col2, col3 = st.columns(3)
        intencao = col1.selectbox(
            "Intenção", ["", *INTENCOES],
            index=_indice(INTENCOES, lead.intencao if lead else None),
        )
        urgencia = col2.selectbox(
            "Urgência", ["", *URGENCIAS],
            index=_indice(URGENCIAS, lead.urgencia if lead else None),
        )
        status = col3.selectbox(
            "Status", STATUS,
            index=STATUS.index(lead.status) if lead and lead.status in STATUS else 0,
        )

        col1, col2, col3 = st.columns(3)
        # Texto e não `number_input`: em branco precisa significar "não sei",
        # e um campo numérico não tem como ficar vazio.
        orcamento_min = col1.text_input(
            "Orçamento mínimo (R$)",
            value=f"{lead.orcamento_min:.0f}" if lead and lead.orcamento_min else "",
        )
        orcamento_max = col2.text_input(
            "Orçamento máximo (R$)",
            value=f"{lead.orcamento_max:.0f}" if lead and lead.orcamento_max else "",
        )
        quartos = col3.text_input(
            "Quartos", value=str(lead.quartos) if lead and lead.quartos else ""
        )

        col1, col2, col3 = st.columns(3)
        bairro = col1.text_input(
            "Bairro", value=(lead.bairro_interesse if lead else "") or ""
        )
        regiao = col2.text_input(
            "Região", value=(lead.regiao_interesse if lead else "") or ""
        )
        tipologia = col3.text_input(
            "Tipologia",
            value=(lead.tipologia_interesse if lead else "") or "",
            placeholder="apartamento, casa...",
        )

        col1, col2, col3 = st.columns(3)
        perfil = col1.text_input(
            "Perfil",
            value=(lead.perfil if lead else "") or "",
            placeholder="investidor, primeiro_imovel...",
        )
        pagamento = col2.text_input(
            "Forma de pagamento",
            value=(lead.forma_pagamento if lead else "") or "",
            placeholder="financiamento, a_vista...",
        )
        motivo = col3.text_input(
            "Motivo da busca", value=(lead.motivo_busca if lead else "") or ""
        )

        amenidades = st.text_input(
            "Amenidades desejadas",
            value=(lead.amenidades_desejadas if lead else "") or "",
            placeholder="piscina, academia...",
        )
        narrativo = st.text_area(
            "Perfil narrativo",
            value=(lead.perfil_narrativo if lead else "") or "",
            height=160,
            help="O artefato que o agente usa para retomar a conversa com contexto.",
        )

        if st.form_submit_button(
            "Criar lead" if novo else "Salvar ficha",
            icon=":material/save:",
            type="primary",
        ):
            campos = {
                "nome": nome.strip() or None,
                "telefone": telefone.strip() or None,
                "intencao": intencao or None,
                "urgencia": urgencia or None,
                "status": status,
                "orcamento_min": _para_decimal(orcamento_min),
                "orcamento_max": _para_decimal(orcamento_max),
                "quartos": int(quartos) if quartos.strip().isdigit() else None,
                "bairro_interesse": bairro.strip() or None,
                "regiao_interesse": regiao.strip() or None,
                "tipologia_interesse": tipologia.strip() or None,
                "perfil": perfil.strip() or None,
                "forma_pagamento": pagamento.strip() or None,
                "motivo_busca": motivo.strip() or None,
                "amenidades_desejadas": amenidades.strip() or None,
                "perfil_narrativo": narrativo.strip() or None,
            }
            servico = LeadService()
            with get_db() as db:
                alvo = (
                    servico.criar_lead_manual(campos, db)
                    if novo
                    else servico.editar_lead(lead.id, campos, db)
                )
                lead_id = alvo.id
                servico.calculate_score(lead_id, db)

            abrir_ficha(lead_id)
            st.toast(
                "Lead criado." if novo else "Ficha salva.", icon=":material/check:"
            )
            st.rerun()


def _canal_do_lead(lead: Lead) -> None:
    """Canal por onde o agente fala com este lead.

    É o que torna um lead criado à mão alcançável pelo follow-up: sem
    identidade de canal o runner não tem para onde despachar, e a mensagem
    fica apenas registrada aqui no painel.
    """
    with get_db() as db:
        identidade = LeadService().get_primary_identity(lead.id, db)
        canal_atual = identidade.channel if identidade else None
        id_atual = identidade.external_chat_id if identidade else ""

    if canal_atual is None:
        st.warning(
            "Este lead não está ligado a nenhum canal. O follow-up é gerado e "
            "fica registrado na conversa, mas não é despachado para ninguém.",
            icon=":material/link_off:",
        )

    col_canal, col_id, col_botao = st.columns([2, 3, 2], vertical_alignment="bottom")
    canal = col_canal.selectbox(
        "Canal", CANAIS,
        index=CANAIS.index(canal_atual) if canal_atual in CANAIS else 0,
        key=f"canal_{lead.id}",
    )
    externo = col_id.text_input(
        "Identificador no canal",
        value=id_atual or "",
        key=f"canal_id_{lead.id}",
        help=(
            "No Telegram é o `chat_id` numérico que o bot enxerga. Um valor "
            "inventado faz o envio falhar no canal, não aqui."
        ),
    )
    if col_botao.button(
        "Vincular", icon=":material/link:", width="stretch",
        key=f"vincular_{lead.id}",
    ):
        if not externo.strip():
            st.error("Informe o identificador do lead no canal.")
        else:
            with get_db() as db:
                LeadService().definir_identidade(lead.id, canal, externo.strip(), db)
            st.toast("Canal vinculado.", icon=":material/link:")
            st.rerun()


def _conversa(lead: Lead) -> None:
    """Histórico do lead, do jeito que aconteceu."""
    with get_db() as db:
        conversa = [
            (m.role, m.message_type, m.content)
            for m in LeadService().get_history(lead.id, 200, db)
            if m.role in ("user", "assistant")
        ]

    if not conversa:
        st.caption("Nenhuma mensagem registrada para este lead.")
        return

    for role, tipo, conteudo in conversa:
        with st.chat_message(role):
            rotulo = ROTULO_DO_TIPO.get(tipo)
            if rotulo:
                st.caption(rotulo)
            st.markdown(markdown_seguro(conteudo))


def _agendamentos(lead: Lead) -> None:
    with get_db() as db:
        itens = [
            (
                a.tipo, a.data_hora, a.status,
                a.imovel.titulo if a.imovel else None,
                a.imovel.id if a.imovel else None,
            )
            for a in SchedulingService().list_by_lead(lead.id, db)
        ]

    if not itens:
        st.caption("Nenhum agendamento para este lead.")
        return

    for tipo, data_hora, status, titulo, imovel_id in itens:
        imovel = f" — {titulo} (imóvel #{imovel_id})" if titulo else ""
        st.write(f"- **{tipo}** em {data_hora:%d/%m/%Y %H:%M} `{status}`{imovel}")


def _disparar_followup(lead: Lead) -> None:
    """Gera o follow-up deste lead agora.

    Sem `sender`: a UI não tem canal de saída próprio. A mensagem é gerada,
    persistida e aparece na conversa — nos canais com push quem despacha é o
    processo do Telegram.
    """
    with st.spinner("Gerando follow-up..."):
        resultado = asyncio.run(run_followup_para_lead(lead.id))

    st.session_state[CHAVE_AVISO_FOLLOWUP] = (
        lead.id,
        "ok" if resultado.executado else "aviso",
        "Follow-up gerado e registrado na conversa do lead."
        if resultado.executado
        else resultado.motivo,
    )
    st.rerun()


def _acoes(lead: Lead) -> None:
    confirmando = st.session_state.get(CHAVE_EXCLUSAO) == lead.id

    col_followup, col_excluir = st.columns(2)
    with col_followup:
        if st.button(
            "Disparar follow-up",
            icon=":material/send:",
            width="stretch",
            help=(
                "Mesma régua do follow-up automático, sem esperar a janela de "
                "inatividade."
            ),
        ):
            _disparar_followup(lead)
    with col_excluir:
        # Some enquanto a confirmacao esta aberta, para nao ficarem dois
        # botoes de excluir na mesma tela.
        if not confirmando and st.button(
            "Excluir lead", icon=":material/delete:", width="stretch"
        ):
            st.session_state[CHAVE_EXCLUSAO] = lead.id
            st.rerun()

    aviso = st.session_state.get(CHAVE_AVISO_FOLLOWUP)
    if aviso and aviso[0] == lead.id:
        mostrar = st.success if aviso[1] == "ok" else st.info
        mostrar(aviso[2], icon=":material/send:")

    if confirmando:
        st.warning(
            f"Excluir o lead {lead.id} e todas as suas mensagens?",
            icon=":material/warning:",
        )
        col_sim, col_nao, _ = st.columns([2, 2, 6])
        if col_sim.button("Confirmar", type="primary", width="stretch"):
            with get_db() as db:
                LeadService().delete_lead(lead.id, db)
            _voltar_para_a_lista()
            st.toast("Lead excluído.", icon=":material/delete:")
            st.rerun()
        if col_nao.button("Cancelar", width="stretch"):
            st.session_state.pop(CHAVE_EXCLUSAO, None)
            st.rerun()


def _cabecalho_da_ficha(lead: Optional[Lead]) -> None:
    col_voltar, col_titulo = st.columns([1, 6], vertical_alignment="center")
    with col_voltar:
        if st.button("Voltar", icon=":material/arrow_back:", width="stretch"):
            _voltar_para_a_lista()
            st.rerun()
    with col_titulo:
        if lead is None:
            st.subheader("Novo lead")
            return
        st.subheader(markdown_seguro(lead.nome or f"Lead {lead.id}"))
        st.markdown(selos_do_lead(lead, float(lead.score or 0)))


def _ficha(lead_id: int) -> None:
    if lead_id == FICHA_EM_BRANCO:
        _cabecalho_da_ficha(None)
        st.divider()
        _formulario(None)
        return

    with get_db() as db:
        lead = LeadService().get_lead(lead_id, db)
        if lead is not None:
            # Sai da sessão junto com os dados já carregados: o resto da tela
            # lê os atributos depois que a sessão fechou.
            db.expunge(lead)

    if lead is None:
        st.error("Lead não encontrado. Ele pode ter sido excluído.")
        if st.button("Voltar para a lista", icon=":material/arrow_back:"):
            _voltar_para_a_lista()
            st.rerun()
        return

    _cabecalho_da_ficha(lead)
    st.divider()

    ficha, canal, conversa, agenda = st.tabs(
        ["Ficha", "Canal", "Conversa", "Agendamentos"]
    )
    with ficha:
        _formulario(lead)
    with canal:
        _canal_do_lead(lead)
    with conversa:
        _conversa(lead)
    with agenda:
        _agendamentos(lead)

    st.divider()
    _acoes(lead)


def render_leads() -> None:
    st.header("Leads", divider="gray")

    lead_aberto = st.session_state.get(CHAVE_LEAD_ABERTO)
    if lead_aberto is not None:
        _ficha(lead_aberto)
        return

    with get_db() as db:
        _lista(db)
