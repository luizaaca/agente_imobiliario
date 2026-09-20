"""Dashboard do corretor com KPIs, custo de LLM, leads e conversas."""
import asyncio

import streamlit as st
from sqlalchemy import desc, func

from src.db.models import Agendamento, FollowUpAttempt, Lead
from src.db.session import get_db
from src.scheduler.followup_runner import run_followup_para_lead
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService
from src.ui.navegacao import abrir_conversa_no_simulador
from src.ui.texto import markdown_seguro

# Guarda o id do lead cujo botao de excluir foi clicado, para que o segundo
# clique — o que apaga de verdade — seja deliberado.
CHAVE_EXCLUSAO = "lead_a_excluir"

# Desfecho do ultimo disparo manual de follow-up: (lead_id, tipo, texto).
# Precisa sobreviver ao rerun para a mensagem aparecer na tela seguinte.
CHAVE_AVISO_FOLLOWUP = "aviso_followup"

STATUS_DISPONIVEIS = [
    "Todos", "novo", "em_qualificacao", "qualificado", "agendado", "inativo",
]
ROTULO_DO_TIPO = {
    "followup": ":material/autorenew: follow-up automático",
    "handover": ":material/handshake: handover ao corretor",
    "system_notice": ":material/settings: aviso do sistema",
}

# Cor do selo de cada status. Sem o selo colorido, o status e mais uma palavra
# na linha; com ele, o corretor varre a lista pela cor.
COR_DO_STATUS = {
    "novo": "blue",
    "em_qualificacao": "violet",
    "qualificado": "green",
    "agendado": "primary",
    "inativo": "gray",
}

# Faixas de temperatura do lead, da mais quente para a mais fria. O numero do
# score fica na metrica; o selo traduz esse numero em uma palavra, que se le de
# relance e nao depende de o leitor saber que 5,5 e mediano.
FAIXAS_DE_SCORE = ((7.0, "red", "quente"), (4.0, "orange", "morno"))


def _alerta_de_budget(resumo: dict) -> None:
    """Avisa, fora do expander, quando o teto de tokens estourou.

    Dentro do expander fechado o aviso nao existe na pratica: quem abre o
    dashboard com o orcamento estourado veria uma tela normal e so descobriria
    o bloqueio quando o chat parasse de responder.
    """
    if resumo["monthly_budget_exceeded"]:
        st.error(
            "**Orçamento mensal de LLM esgotado.** Conversas novas recebem "
            "mensagem de indisponibilidade até a virada do mês ou até "
            "`LLM_MONTHLY_TOKEN_BUDGET` subir.",
            icon=":material/credit_card_off:",
        )
    elif resumo["daily_budget_exceeded"]:
        st.warning(
            "**Orçamento diário de LLM esgotado.** O chat e o follow-up ficam "
            "bloqueados até amanhã, ou até `LLM_DAILY_TOKEN_BUDGET` subir.",
            icon=":material/schedule:",
        )


def _saude_do_agente(resumo: dict) -> None:
    """Tempo de resposta e taxa de erro do provider, hoje.

    Ambos sao `None` enquanto nao houve chamada nenhuma no dia, e a tela
    mostra "—": um zero ali afirmaria que esta tudo bem quando na verdade nada
    foi exercitado.
    """
    latencia = resumo["daily_latency_ms"]
    taxa = resumo["daily_error_rate"]

    col_tempo, col_erro = st.columns(2)
    col_tempo.metric(
        "Tempo médio de resposta",
        f"{latencia / 1000:.1f} s" if latencia is not None else "—",
        help="Média das chamadas bem-sucedidas ao provider hoje.",
    )
    col_erro.metric(
        "Taxa de erro",
        f"{taxa:.0%}" if taxa is not None else "—",
        help="Chamadas que falharam sobre o total de chamadas de hoje.",
    )


def _painel_de_custo(db) -> None:
    """Consumo de LLM do dia e do mes, com o quanto falta para o teto."""
    resumo = LLMUsageService().get_dashboard_summary(db)
    _alerta_de_budget(resumo)

    with st.expander("Consumo de LLM", expanded=False, icon=":material/payments:"):
        _saude_do_agente(resumo)
        st.divider()
        col_dia, col_mes = st.columns(2)
        for coluna, periodo, rotulo in (
            (col_dia, "daily", "Hoje"),
            (col_mes, "monthly", "Este mês"),
        ):
            tokens = resumo[f"{periodo}_tokens"]
            teto = resumo[f"{periodo}_budget"]
            custo = float(resumo[f"{periodo}_cost_usd"])
            with coluna:
                st.metric(f"{rotulo} — tokens", f"{tokens:,}".replace(",", "."))
                st.progress(
                    min(tokens / teto, 1.0) if teto else 0.0,
                    text=f"{tokens:,} de {teto:,} do orçamento".replace(",", "."),
                )
                st.metric(f"{rotulo} — custo estimado", f"US$ {custo:.4f}")

        st.caption(
            "Custo estimado pela tabela de preços por modelo em "
            "`LLMUsageService.PRICING`; modelos fora da tabela usam um preço "
            "genérico e registram aviso no log."
        )


def _kpis(db) -> None:
    total_leads = db.query(func.count(Lead.id)).scalar() or 0
    leads_quentes = db.query(func.count(Lead.id)).filter(Lead.score >= 7).scalar() or 0
    agendamentos = (
        db.query(func.count(Agendamento.id))
        .filter(Agendamento.status == "pendente")
        .scalar() or 0
    )
    leads_inativos = (
        db.query(func.count(Lead.id)).filter(Lead.status == "inativo").scalar() or 0
    )
    # So as tentativas que sairam de fato: uma mensagem gerada sem canal ativo
    # aparece no painel, mas nao foi disparada para ninguem.
    followups = (
        db.query(func.count(FollowUpAttempt.id))
        .filter(FollowUpAttempt.status == "sent")
        .scalar() or 0
    )

    # `border=True` fecha cada numero em um cartao: sem a borda os cinco viram
    # texto solto no topo da pagina, sem separacao entre eles.
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total de leads", total_leads, icon=":material/group:", border=True)
    col2.metric(
        "Leads quentes",
        leads_quentes,
        icon=":material/local_fire_department:",
        border=True,
    )
    col3.metric("Agendamentos", agendamentos, icon=":material/event:", border=True)
    col4.metric(
        "Follow-ups enviados", followups, icon=":material/send:", border=True
    )
    col5.metric("Inativos", leads_inativos, icon=":material/bedtime:", border=True)


def _leads_filtrados(db) -> list[Lead]:
    col1, col2, col3 = st.columns(3)
    with col1:
        busca = st.text_input(
            "Buscar", placeholder="Nome, bairro, intenção...", type="search"
        )
    with col2:
        status_filtro = st.selectbox("Status", STATUS_DISPONIVEIS)
    with col3:
        intencao_filtro = st.selectbox(
            "Intenção", ["Todas", "compra", "aluguel", "investimento"]
        )

    query = db.query(Lead).order_by(desc(Lead.score))
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
    return query.limit(50).all()


def _mostrar_conversa(lead: Lead, db) -> None:
    """Conversa do lead, do jeito que ela aconteceu."""
    mensagens = LeadService().get_history(lead.id, 200, db)
    if not mensagens:
        st.caption("Nenhuma mensagem registrada para este lead.")
        return

    for msg in mensagens:
        if msg.role not in ("user", "assistant"):
            continue
        with st.chat_message(msg.role):
            rotulo = ROTULO_DO_TIPO.get(msg.message_type)
            if rotulo:
                st.caption(rotulo)
            st.markdown(markdown_seguro(msg.content))


def _mostrar_agendamentos(lead: Lead, db) -> None:
    agendamentos = SchedulingService().list_by_lead(lead.id, db)
    if not agendamentos:
        return
    st.write("**Agendamentos**")
    for ag in agendamentos:
        imovel = f" — {ag.imovel.titulo} (imóvel #{ag.imovel.id})" if ag.imovel else ""
        st.write(
            f"- {ag.tipo} em {ag.data_hora:%d/%m/%Y %H:%M} [{ag.status}]{imovel}"
        )


def _disparar_followup(lead: Lead) -> None:
    """Gera e despacha o follow-up deste lead agora.

    Sem `sender`: o dashboard nao tem canal de saida proprio. A mensagem e
    gerada, persistida e aparece na conversa do lead — para os canais com push,
    quem despacha e o processo do Telegram.
    """
    with st.spinner("Gerando follow-up..."):
        resultado = asyncio.run(run_followup_para_lead(lead.id))

    if not resultado.executado:
        st.session_state[CHAVE_AVISO_FOLLOWUP] = (lead.id, "aviso", resultado.motivo)
    else:
        st.session_state[CHAVE_AVISO_FOLLOWUP] = (
            lead.id,
            "ok",
            "Follow-up gerado e registrado na conversa do lead.",
        )
    st.rerun()


def _aviso_do_followup(lead: Lead) -> None:
    """Desfecho do ultimo disparo, na largura toda do cartao."""
    aviso = st.session_state.get(CHAVE_AVISO_FOLLOWUP)
    if not aviso or aviso[0] != lead.id:
        return

    _, tipo, texto = aviso
    if tipo == "ok":
        st.success(texto, icon=":material/send:")
    else:
        st.info(texto, icon=":material/info:")


def _botoes_do_lead(lead: Lead) -> None:
    """As acoes do cartao, na coluna da direita."""
    if st.button(
        "Disparar follow-up",
        icon=":material/send:",
        key=f"followup_{lead.id}",
        width="stretch",
        help="Mesma régua do follow-up automático, sem esperar a janela de inatividade.",
    ):
        _disparar_followup(lead)

    # Fora de `on_click` de proposito: `abrir_conversa_no_simulador` termina em
    # `st.switch_page`, que interrompe a execucao para trocar de pagina.
    if st.button(
        "Abrir no simulador",
        icon=":material/forum:",
        key=f"abrir_{lead.id}",
        width="stretch",
        help="Carrega esta conversa no chat para você continuar de onde parou.",
    ):
        abrir_conversa_no_simulador(lead.id)

    # Some enquanto a confirmacao esta aberta, para nao ficarem dois botoes de
    # excluir no mesmo cartao.
    if st.session_state.get(CHAVE_EXCLUSAO) != lead.id:
        if st.button(
            "Excluir lead",
            icon=":material/delete:",
            key=f"excluir_{lead.id}",
            width="stretch",
        ):
            st.session_state[CHAVE_EXCLUSAO] = lead.id
            st.rerun()


def _confirmacao_de_exclusao(lead: Lead) -> None:
    """Segundo clique da exclusao, na largura toda do cartao.

    Fora da coluna de acoes de proposito: espremido em um terco da largura, o
    aviso quebrava em varias linhas e os botoes ficavam menores que o alvo
    confortavel de clique.
    """
    if st.session_state.get(CHAVE_EXCLUSAO) != lead.id:
        return

    st.warning(
        f"Excluir o lead {lead.id} e todas as suas mensagens?",
        icon=":material/warning:",
    )
    col_sim, col_nao, _ = st.columns([2, 2, 6])
    if col_sim.button(
        "Confirmar", key=f"confirma_{lead.id}", type="primary", width="stretch"
    ):
        with get_db() as db:
            LeadService().delete_lead(lead.id, db)
        st.session_state.pop(CHAVE_EXCLUSAO, None)
        # A conversa aberta no simulador pode ser justamente esta.
        if st.session_state.get("lead_id") == lead.id:
            st.session_state.lead_id = None
            st.session_state.messages = []
        st.rerun()
    if col_nao.button("Cancelar", key=f"cancela_{lead.id}", width="stretch"):
        st.session_state.pop(CHAVE_EXCLUSAO, None)
        st.rerun()


def _selos_do_lead(lead: Lead, score: float) -> str:
    """Status, temperatura, intencao e regiao como selos coloridos."""
    selos = [
        f":{COR_DO_STATUS.get(lead.status, 'gray')}-badge[{lead.status.replace('_', ' ')}]"
    ]

    cor, palavra = "gray", "frio"
    for piso, cor_da_faixa, nome_da_faixa in FAIXAS_DE_SCORE:
        if score >= piso:
            cor, palavra = cor_da_faixa, nome_da_faixa
            break
    selos.append(f":{cor}-badge[{palavra}]")

    if lead.intencao:
        selos.append(f":gray-badge[{lead.intencao}]")
    regiao = lead.regiao_interesse or lead.bairro_interesse
    if regiao:
        selos.append(f":gray-badge[:material/location_on: {regiao}]")
    return " ".join(selos)


def _dinheiro(valor) -> str:
    return f"R$ {valor:,.0f}".replace(",", ".")


def _faixa_de_orcamento(lead: Lead) -> str:
    """Orcamento em texto, dizendo qual das duas pontas e conhecida."""
    if lead.orcamento_min is None and lead.orcamento_max is None:
        return "N/I"
    if lead.orcamento_min is None:
        return f"até {_dinheiro(lead.orcamento_max)}"
    if lead.orcamento_max is None:
        return f"a partir de {_dinheiro(lead.orcamento_min)}"
    return f"{_dinheiro(lead.orcamento_min)} a {_dinheiro(lead.orcamento_max)}"


def _detalhes_do_lead(lead: Lead, db) -> None:
    st.write(f"**Intenção:** {lead.intencao or 'N/I'}")
    regiao = lead.regiao_interesse or lead.bairro_interesse or "N/I"
    st.write(f"**Região:** {regiao}")
    # `markdown_seguro` porque dois `R$` na mesma linha viram uma formula LaTeX
    # para o Streamlit: os cifroes somem e o texto entre eles sai embaralhado.
    st.write(markdown_seguro(f"**Orçamento:** {_faixa_de_orcamento(lead)}"))
    st.write(f"**Quartos:** {lead.quartos or 'N/I'}")
    st.write(f"**Urgência:** {lead.urgencia or 'N/I'}")

    if lead.perfil_narrativo:
        st.write("**Perfil narrativo**")
        st.markdown(markdown_seguro(lead.perfil_narrativo))
    if lead.resumo:
        st.write("**Resumo executivo**")
        st.markdown(markdown_seguro(lead.resumo))

    _mostrar_agendamentos(lead, db)


def _cartao_do_lead(lead: Lead, db) -> None:
    """Uma linha da lista de leads.

    O nome, os selos e o score ficam abertos, e as acoes ao lado: a lista se
    varre de relance procurando quem atender primeiro, e isso nao pode exigir
    abrir cada item. O que e leitura demorada — ficha e conversa — fica atras
    de um clique.
    """
    score = float(lead.score or 0)
    nome = lead.nome or f"Lead {lead.id}"

    with st.container(border=True):
        col_lead, col_score, col_acoes = st.columns(
            [6, 2, 3], vertical_alignment="center"
        )

        with col_lead:
            st.markdown(f"#### {markdown_seguro(nome)}")
            st.markdown(_selos_do_lead(lead, score))

        with col_score:
            st.metric(
                "Score",
                f"{score:.1f}" if lead.score is not None else "—",
                label_visibility="visible",
            )

        with col_acoes:
            _botoes_do_lead(lead)

        _aviso_do_followup(lead)
        _confirmacao_de_exclusao(lead)

        col_ficha, col_conversa = st.columns([1, 3], vertical_alignment="center")
        with col_ficha:
            ver_ficha = st.toggle("Ficha do lead", key=f"ficha_{lead.id}")
        with col_conversa:
            # A conversa fica atras de um toggle: sem isso o Streamlit montaria
            # o historico inteiro dos 50 leads a cada recarga.
            ver_conversa = st.toggle("Ver conversa", key=f"conversa_{lead.id}")

        # Fora das colunas: ficha e conversa ocupam a largura toda do cartao.
        if ver_ficha:
            _detalhes_do_lead(lead, db)
        if ver_conversa:
            _mostrar_conversa(lead, db)


def render_dashboard():
    st.header("Dashboard do Corretor", divider="gray")

    with get_db() as db:
        _kpis(db)
        _painel_de_custo(db)
        st.divider()

        leads = _leads_filtrados(db)
        if not leads:
            st.info("Nenhum lead encontrado com os filtros selecionados.")
            return

        st.subheader(f"Leads ({len(leads)})")
        for lead in leads:
            _cartao_do_lead(lead, db)
