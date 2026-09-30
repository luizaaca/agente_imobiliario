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
from src.ui.conversa import Fala, custo_da_conversa, falas_do_lead, renderizar
from src.ui.navegacao import entrou_na_pagina_agora
from src.ui.papeis import papeis_da_sessao, ve_os_bastidores
from src.ui.texto import mensagem_para_markdown

CANAL = "streamlit"
# Quantas mensagens a tela mostra ao retomar uma conversa. E so exibicao: o que
# vai para o modelo e limitado a parte por HISTORY_LIMIT.
LIMITE_EXIBIDO = 100

# Altura da janela de conversa, em pixels. A caixa rola por dentro e mantem o
# painel de troca de lead e o campo de mensagem sempre visiveis.
ALTURA_DA_CONVERSA = 460

# De quanto em quanto tempo a caixa da conversa relê o banco sem esperar
# clique. Cada vez são duas consultas pequenas, limitadas a LIMITE_EXIBIDO
# falas, e só enquanto o chat está aberto num lead.
INTERVALO_DE_RELEITURA = "5s"


def _prefixo_do_usuario() -> str:
    return f"streamlit_{st.session_state.get('username', 'demo')}_"


def _recarregar(lead_id: int) -> None:
    """Relê a conversa do banco para a tela.

    O simulador mostra tudo que aconteceu, e não só o que a pessoa leria: as
    chamadas de ferramenta, as consultas que o agente de busca escreveu e o que
    cada uma devolveu. É ferramenta de quem constrói o agente.

    Ler do banco, em vez de ir acumulando o que a tela já sabe, é o que traz as
    ferramentas junto — elas acontecem dentro do turno e ninguém as anuncia.
    """
    with get_db() as db:
        st.session_state.messages = falas_do_lead(lead_id, db, LIMITE_EXIBIDO)


def abrir_conversa(lead_id: int) -> None:
    """Carrega no simulador a conversa de um lead existente."""
    _recarregar(lead_id)
    st.session_state.lead_id = lead_id


def nova_conversa() -> None:
    """Zera a tela para comecar do zero.

    O lead so nasce no primeiro envio: abrir uma conversa em branco nao deve
    encher o painel do corretor de leads vazios.
    """
    st.session_state.lead_id = None
    st.session_state.messages = []


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
    usuario: o seletor precisa alcancar qualquer conversa, inclusive as que
    vieram do Telegram ou de outro corretor.
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
        # Numa linha propria: o seletor de conversa ao lado ja aperta esta
        # coluna, e as duas juntas quebravam no meio do numero.
        if custo := custo_da_conversa(lead.id, db, ve_os_bastidores(papeis_da_sessao())):
            st.caption(custo)


def _painel_da_conversa() -> None:
    """Seletor de conversa, botao de nova e resumo do lead aberto.

    Fica no corpo da pagina, e nao na barra lateral: pertence ao chat, e a
    barra lateral e da navegacao entre paginas.
    """
    atual = st.session_state.lead_id
    opcoes = _opcoes_de_conversa(atual)
    ids = [lead_id for lead_id, _ in opcoes]
    rotulos = dict(opcoes)

    col_sel, col_nova, col_info = st.columns([5, 1, 5], vertical_alignment="bottom")

    with col_sel:
        # A chave carrega o lead aberto de proposito. Um selectbox mantem o
        # valor escolhido enquanto a chave nao muda — inclusive sem `key`
        # explicita, que o Streamlit gera internamente — e esse valor vence o
        # `index`. Com chave fixa, abrir uma conversa pelo painel devolveria o
        # lead anterior no rerun seguinte.
        escolhido = st.selectbox(
            "Conversa",
            ids,
            index=ids.index(atual) if atual in ids else 0,
            format_func=lambda i: rotulos[i],
            key=f"seletor_conversa_{atual}",
        )

    with col_nova:
        # Só o ícone, como o "novo lead" da lista: o rótulo escrito ocupava
        # mais largura que o seletor de conversa ao lado, que é o controle
        # que de fato se usa aqui.
        nova = st.button(
            "", icon=":material/add:", key="nova_conversa",
            help="Começar uma conversa nova",
        )

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

    # Só o nome das variáveis: como elas são definidas — .env, secrets do
    # pipeline, ambiente do host — depende de onde isto está rodando, e a tela
    # não tem como saber. O "como" fica no README, num lugar só.
    variaveis = ", ".join(f"`{nome}`" for nome in faltando)
    plural = "Variáveis de ambiente ausentes" if len(faltando) > 1 else (
        "Variável de ambiente ausente"
    )
    st.warning(
        f"**Configuração de LLM incompleta** — o chat está desativado.\n\n"
        f"{plural}: {variaveis}\n\n"
        f"Consulte a seção **Configuração** do README.",
        icon=":material/settings:",
    )
    return faltando


@st.fragment(run_every=INTERVALO_DE_RELEITURA)
def _conversa_ao_vivo() -> None:
    """As falas do lead aberto, relidas do banco a cada desenho.

    A conversa também cresce por fora desta tela — o follow-up disparado na
    ficha ou pelo ciclo automático, a pessoa escrevendo pelo Telegram. Relida
    só ao trocar de lead ou ao fim de um turno, ela ficava para trás até
    alguém escrever aqui.

    É fragmento para se redesenhar sozinho, sem esperar clique, e sem rodar a
    página inteira: só esta caixa vai ao banco a cada intervalo. Durante um
    turno o Streamlit segura esses redesenhos e os retoma ao fim, então a
    resposta que está sendo gerada não é interrompida.
    """
    lead_id = st.session_state.lead_id
    if lead_id is not None:
        _recarregar(lead_id)
    renderizar(st.session_state.messages, ve_os_bastidores(papeis_da_sessao()))


def render_chat():
    st.header("Chat com o Agente SDR", divider="gray")
    st.caption("Simule uma conversa como lead imobiliário")
    faltando = _aviso_de_configuracao()

    # Entrar pelo menu abre uma conversa em branco. O simulador existe para
    # experimentar um atendimento do começo, e cair no meio de uma conversa
    # antiga obrigava a limpar a tela antes de poder testar qualquer coisa.
    # As conversas anteriores continuam todas no seletor do painel.
    if entrou_na_pagina_agora() or "lead_id" not in st.session_state:
        nova_conversa()

    _painel_da_conversa()

    # A conversa fica numa caixa de altura fixa, e não solta na página: solta,
    # ela empurra o painel de conversa para fora da tela conforme cresce, e
    # trocar de lead passa a exigir rolar tudo de volta para cima.
    #
    # `autoscroll` explícito porque o automático não enxerga as falas dentro
    # do fragmento: a caixa abria no topo da conversa em vez de no fim.
    janela = st.container(height=ALTURA_DA_CONVERSA, autoscroll=True)
    with janela:
        _conversa_ao_vivo()

    # Desabilitado quando falta configuração: deixar o campo ativo só levaria
    # o usuário a mandar uma mensagem e receber "atendimento indisponível".
    entrada = st.chat_input(
        "Configure o LLM para conversar" if faltando else "Digite sua mensagem...",
        disabled=bool(faltando),
    )
    if prompt := entrada:
        st.session_state.messages.append(Fala(role="user", conteudo=prompt))
        with janela:
            with st.chat_message("user"):
                st.markdown(mensagem_para_markdown(prompt))

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
                    st.markdown(mensagem_para_markdown(response))

        # O turno inteiro vem do banco, e nao so a resposta: as ferramentas que
        # rodaram no meio dele so existem la.
        _recarregar(lead_id)
        # Rerun para o painel refletir o lead recem-criado e a contagem de
        # mensagens atualizada.
        st.rerun()
