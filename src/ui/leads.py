"""CRUD de leads: a tela de trabalho do corretor.

Duas paginas de verdade, com URLs proprias: a lista (`/leads`, no menu) e a
ficha de um lead (`/lead`, fora do menu). A lista mostra o que se varre de
relance — quem atender primeiro — e a ficha concentra tudo que se faz com um
lead: editar, ligar a um canal, disparar follow-up, ler a conversa e excluir.

Duas paginas, e nao dois estados da mesma tela, porque e isso que faz o link
"Leads" do menu devolver a listagem de dentro da ficha, sem precisar adivinhar
se o clique veio do menu ou de um botao da propria tela.

O dashboard manda para ca: a lupa da carteira abre a ficha daquele lead.
"""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

import streamlit as st

from src.db.models import Agendamento, Imovel, Lead
from src.db.session import get_db
from src.scheduler.followup_runner import run_followup_para_lead
from src.services.lead_service import LeadService
from src.services.scheduling_service import SchedulingService
from src.tempo import agora, formatar, para_exibir, para_guardar
from src.ui.conversa import falas_do_lead, quantas_falas, renderizar
from src.ui.navegacao import abrir_lista_de_leads, abrir_pagina_da_ficha
from src.ui.tabela import (
    AJUDA_DA_BUSCA,
    PLACEHOLDER_DA_BUSCA,
    Acao,
    Coluna,
    aplicar_ordem,
    filtro_de_busca,
    rotulo_do_lead,
    seletor_de_ordem,
    selo_de_score,
    tabela_de_leads,
    temperatura,
    texto,
)
from src.ui.texto import markdown_seguro

# Lead cuja ficha esta aberta. Zero significa "ficha em branco", porque nenhum
# lead tem id 0. Ausente na pagina da ficha significa que se chegou nela sem
# escolher lead nenhum, e a ficha devolve para a lista.
CHAVE_LEAD_ABERTO = "lead_aberto"
# Lead cujo botao de excluir foi clicado, para o segundo clique ser deliberado.
CHAVE_EXCLUSAO = "lead_a_excluir"
# Desfecho do ultimo disparo manual: (lead_id, tipo, texto).
CHAVE_AVISO_FOLLOWUP = "aviso_followup"
# Formulario de agendamento aberto: (lead_id, agendamento_id ou None p/ novo).
CHAVE_AGENDAMENTO = "agendamento_em_edicao"
# Agendamento cujo botao de excluir foi clicado, para o segundo clique ser
# deliberado. Excluir e definitivo e nao tem desfazer.
CHAVE_EXCLUSAO_DE_AGENDAMENTO = "agendamento_a_excluir"

FICHA_EM_BRANCO = 0

# Altura da caixa da conversa, em pixels. Alta o bastante para caber uma troca
# inteira sem rolar, e baixa o bastante para as acoes do lead continuarem na
# tela junto com ela.
ALTURA_DA_CONVERSA = 420

STATUS = ["novo", "em_qualificacao", "qualificado", "agendado", "inativo"]
INTENCOES = ["compra", "aluguel", "investimento"]
URGENCIAS = ["baixa", "media", "alta"]
# Canais que o agente sabe atender. `streamlit` e o simulador; `telegram` e o
# unico com envio ativo hoje.
CANAIS = ["telegram", "streamlit"]

TIPOS_DE_AGENDAMENTO = ["visita", "reuniao"]
STATUS_DE_AGENDAMENTO = ["pendente", "confirmado", "realizado", "cancelado"]
COR_DO_STATUS_DE_AGENDAMENTO = {
    "pendente": "orange",
    "confirmado": "blue",
    "realizado": "green",
    "cancelado": "gray",
}

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
def abrir_ficha(lead_id: int) -> None:
    """Escolhe o lead e leva para a pagina da ficha."""
    st.session_state[CHAVE_LEAD_ABERTO] = lead_id
    st.session_state.pop(CHAVE_EXCLUSAO, None)
    st.session_state.pop(CHAVE_AGENDAMENTO, None)
    abrir_pagina_da_ficha()


def _voltar_para_a_lista() -> None:
    st.session_state.pop(CHAVE_LEAD_ABERTO, None)
    st.session_state.pop(CHAVE_EXCLUSAO, None)
    st.session_state.pop(CHAVE_AGENDAMENTO, None)
    abrir_lista_de_leads()


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


def _filtros(db):
    """Filtros e ordenacao da carteira. Devolve a query ja restringida."""
    col_busca, col_status, col_intencao, col_ordem = st.columns([3, 2, 2, 3])
    with col_busca:
        busca = st.text_input(
            "Buscar",
            placeholder=PLACEHOLDER_DA_BUSCA,
            help=AJUDA_DA_BUSCA,
            type="search",
        )
    with col_status:
        status_filtro = st.selectbox("Status", ["Todos", *STATUS])
    with col_intencao:
        intencao_filtro = st.selectbox("Intenção", ["Todas", *INTENCOES])
    with col_ordem:
        campo, decrescente = seletor_de_ordem("ordem_da_lista_de_leads")

    query = db.query(Lead)
    if status_filtro != "Todos":
        query = query.filter(Lead.status == status_filtro)
    if intencao_filtro != "Todas":
        query = query.filter(Lead.intencao == intencao_filtro)
    if busca:
        query = query.filter(filtro_de_busca(busca))
    return aplicar_ordem(query, campo, decrescente).limit(200).all()


def _colunas_da_lista(situacoes: Mapping[int, str]) -> tuple[Coluna, ...]:
    return (
        # O numero do lead ganha coluna propria: e o identificador que existe
        # no banco, o que a busca encontra e o que sobra quando nao ha nome.
        Coluna("#", 1, lambda lead: f"`{lead.id}`"),
        Coluna("Nome", 3, lambda lead: f"**{markdown_seguro(lead.nome)}**" if lead.nome else "—"),
        # `em qualificacao` e a faixa fechada de orcamento sao os textos mais
        # longos da tabela: sem folga, um trunca e o outro quebra em duas linhas.
        coluna_de_status(situacoes, peso=3),
        Coluna("Intenção", 2, lambda lead: texto(lead.intencao)),
        Coluna("Região", 2, lambda lead: texto(lead.regiao_interesse or lead.bairro_interesse)),
        Coluna("Orçamento", 4, lambda lead: texto(faixa_de_orcamento(lead))),
        Coluna("Telefone", 2, lambda lead: texto(lead.telefone)),
        Coluna("Score", 2, selo_de_score),
    )


def situacoes_de_agendamento(leads: Sequence[Lead], db) -> dict[int, str]:
    """Situação do compromisso mais próximo de cada lead, numa consulta só."""
    ids = [lead.id for lead in leads if lead.status == "agendado"]
    if not ids:
        return {}

    linhas = (
        db.query(Agendamento.lead_id, Agendamento.status, Agendamento.data_hora)
        .filter(
            Agendamento.lead_id.in_(ids),
            Agendamento.status.in_(SchedulingService.STATUS_ATIVOS),
        )
        .order_by(Agendamento.data_hora.asc())
        .all()
    )
    situacoes: dict[int, str] = {}
    for lead_id, status, _ in linhas:
        situacoes.setdefault(lead_id, status)  # o mais próximo manda
    return situacoes


def selo_de_status(lead: Lead, situacoes: Mapping[int, str]) -> str:
    """O estágio do lead, colorido pela situação da visita quando há uma.

    A situação entra como cor do próprio selo, e não como um segundo selo ao
    lado: dois selos na mesma célula quebravam a linha e desalinhavam a tabela.

    A cor é a mesma que a situação já tem na ficha — azul para confirmado,
    laranja para pendente. Um segundo vocabulário de cores para a mesma coisa
    obrigaria a reaprender a leitura ao trocar de tela.
    """
    cor = (
        COR_DO_STATUS_DE_AGENDAMENTO.get(situacoes.get(lead.id))
        or COR_DO_STATUS.get(lead.status, "gray")
    )
    return f":{cor}-badge[{lead.status.replace('_', ' ')}]"


def coluna_de_status(situacoes: Mapping[int, str], peso: int) -> Coluna:
    """A coluna Status, para qualquer tabela de leads.

    As situações vêm por parâmetro, e não de uma consulta por linha: são os
    compromissos de pé de todos os leads da página de uma vez. E vêm por
    parâmetro em vez de um global do módulo porque a carteira do dashboard
    desenha a mesma coluna — com o global, bastava uma tela esquecer de
    preenchê-lo para o selo mudar de significado de uma página para a outra.
    """
    return Coluna(
        "Status", peso, lambda lead: selo_de_status(lead, situacoes)
    )


def _pedir_exclusao(lead: Lead) -> None:
    st.session_state[CHAVE_EXCLUSAO] = lead.id
    st.rerun()


def _confirmacao_na_lista(lead: Lead) -> None:
    """Desfecho do follow-up e confirmacao de exclusao, abaixo da linha.

    Na coluna dos botoes nao caberiam: o aviso quebraria em varias linhas e os
    botoes ficariam menores que o alvo confortavel de clique.
    """
    aviso = st.session_state.get(CHAVE_AVISO_FOLLOWUP)
    if aviso and aviso[0] == lead.id:
        mostrar = st.success if aviso[1] == "ok" else st.info
        mostrar(aviso[2], icon=":material/send:")

    if st.session_state.get(CHAVE_EXCLUSAO) != lead.id:
        return

    nome = rotulo_do_lead(lead)
    st.warning(
        f"Excluir **{markdown_seguro(nome)}** e todas as suas mensagens?",
        icon=":material/warning:",
    )
    col_sim, col_nao, _ = st.columns([2, 2, 8])
    if col_sim.button(
        "Confirmar", key=f"confirma_lista_{lead.id}", type="primary", width="stretch"
    ):
        with get_db() as db:
            LeadService().delete_lead(lead.id, db)
        st.session_state.pop(CHAVE_EXCLUSAO, None)
        st.toast("Lead excluído.", icon=":material/delete:")
        st.rerun()
    if col_nao.button("Cancelar", key=f"cancela_lista_{lead.id}", width="stretch"):
        st.session_state.pop(CHAVE_EXCLUSAO, None)
        st.rerun()
    st.divider()


ACOES_DA_LISTA = (
    Acao(":material/edit:", "Abrir a ficha deste lead", "acao_editar",
         lambda lead: abrir_ficha(lead.id)),
    Acao(":material/send:", "Disparar follow-up para este lead", "acao_followup",
         lambda lead: _disparar_followup(lead)),
    Acao(":material/delete:", "Excluir este lead", "acao_excluir", _pedir_exclusao),
)


def _lista(db) -> None:
    leads = _filtros(db)

    col_contagem, col_novo = st.columns([4, 1], vertical_alignment="center")
    with col_contagem:
        st.caption(f"{len(leads)} lead(s)")
    with col_novo:
        # Alinhado a direita para encostar na coluna dos icones da tabela,
        # logo abaixo.
        with st.container(horizontal=True, horizontal_alignment="right"):
            if st.button(
                "", icon=":material/person_add:", key="novo_lead",
                help="Cadastrar um lead à mão",
            ):
                abrir_ficha(FICHA_EM_BRANCO)

    if not leads:
        st.info("Nenhum lead encontrado com os filtros selecionados.")
        return

    tabela_de_leads(
        leads,
        _colunas_da_lista(situacoes_de_agendamento(leads, db)),
        ACOES_DA_LISTA,
        depois_da_linha=_confirmacao_na_lista,
    )


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
                # O status escolhido na ficha vale para os estagios de
                # julgamento; `agendado` e fato verificavel, e quem manda e a
                # agenda. Sem isto daria para marcar `agendado` sem visita
                # nenhuma, ou tirar de `agendado` quem tem visita marcada.
                SchedulingService().sincronizar_status_do_lead(lead_id, db)

            st.toast(
                "Lead criado." if novo else "Ficha salva.", icon=":material/check:"
            )
            if novo:
                # Criar leva para a ficha do lead recem-nascido; salvar apenas
                # recarrega a que ja esta aberta.
                abrir_ficha(lead_id)
            st.rerun()


def _canal_do_lead(lead: Lead) -> None:
    """Canal por onde o agente fala com este lead.

    É o que torna um lead criado à mão alcançável pelo follow-up: sem
    identidade de canal o runner não tem para onde despachar, e a mensagem
    fica apenas registrada aqui no painel.

    Vincula-se uma vez só. Depois disso os três campos ficam travados — ver o
    comentário abaixo sobre por que reapontar o vínculo é perigoso.
    """
    with get_db() as db:
        identidade = LeadService().get_primary_identity(lead.id, db)
        canal_atual = identidade.channel if identidade else None
        id_atual = identidade.external_chat_id if identidade else ""

    st.markdown(
        "**Por onde o agente fala com este lead.** Um lead que chegou pelo "
        "Telegram já vem ligado ao canal; um cadastrado à mão, não. "
        "**Vincular** grava esse endereço — é o que permite ao follow-up sair "
        "daqui e chegar na pessoa."
    )

    # Uma vez gravado, o vinculo trava. Ele nao e uma preferencia: e a
    # identidade da pessoa no canal, e trocar o identificador nao corrige um
    # dado deste lead — aponta a conversa dele para outra pessoa, que passaria
    # a receber o follow-up e o historico sem ninguem perceber.
    vinculado = canal_atual is not None

    if vinculado:
        st.success(
            f"Vinculado a **{canal_atual}**. O vínculo não é editável: "
            "trocá-lo apontaria esta conversa para outra pessoa.",
            icon=":material/link:",
        )
    else:
        st.warning(
            "Este lead não está ligado a nenhum canal. O follow-up é gerado e "
            "fica registrado na conversa, mas não é despachado para ninguém.",
            icon=":material/link_off:",
        )

    # A chave carrega o estado de trava de proposito. Um widget guarda o valor
    # escolhido enquanto a chave nao muda, e esse valor vence o `value` — ao
    # travar, o campo continuaria mostrando o que havia antes de gravar, que e
    # vazio no caso comum de acabar de vincular.
    sufixo = f"{lead.id}_{'travado' if vinculado else 'livre'}"

    col_canal, col_id, col_botao = st.columns([2, 3, 2], vertical_alignment="bottom")
    canal = col_canal.selectbox(
        "Canal", CANAIS,
        index=CANAIS.index(canal_atual) if canal_atual in CANAIS else 0,
        key=f"canal_{sufixo}",
        disabled=vinculado,
    )
    externo = col_id.text_input(
        "Identificador no canal",
        value=id_atual or "",
        key=f"canal_id_{sufixo}",
        disabled=vinculado,
        help=(
            "No Telegram é o `chat_id` numérico que o bot enxerga. Um valor "
            "inventado faz o envio falhar no canal, não aqui."
        ),
    )
    if col_botao.button(
        "Vincular", icon=":material/link:", width="stretch",
        key=f"vincular_{sufixo}",
        disabled=vinculado,
        help=(
            "Já vinculado — o endereço no canal não muda pela tela."
            if vinculado
            else "Grava por onde o follow-up alcança este lead."
        ),
    ):
        if not externo.strip():
            st.error("Informe o identificador do lead no canal.")
        else:
            with get_db() as db:
                LeadService().definir_identidade(lead.id, canal, externo.strip(), db)
            st.toast("Canal vinculado.", icon=":material/link:")
            st.rerun()


def _conversa(lead: Lead) -> None:
    """Histórico do lead, do jeito que aconteceu.

    Dentro de uma caixa de altura fixa: solta na página, uma conversa de
    algumas dezenas de turnos empurra as ações do lead para fora da tela e
    obriga a rolar tudo de volta para chegar a elas.
    """
    with get_db() as db:
        falas = falas_do_lead(lead.id, db, 200)

    if not falas:
        st.caption("Nenhuma mensagem registrada para este lead.")
        return

    st.caption(
        f"{quantas_falas(falas)} mensagem(ns) — as ferramentas que o agente "
        f"usou abrem nos painéis"
    )
    with st.container(height=ALTURA_DA_CONVERSA):
        renderizar(falas)


def _resumo_para_o_corretor(lead: Lead) -> None:
    """O briefing executivo do atendimento, escrito no encerramento.

    É o produto final do SDR: o que o corretor lê antes de ligar, para não
    precisar reconstruir a conversa inteira a partir do histórico.
    """
    if not lead.resumo:
        st.caption(
            "O resumo é gerado quando o atendimento é encerrado — por "
            "agendamento, desistência ou pedido de contato humano."
        )
        return

    st.markdown(markdown_seguro(lead.resumo))


def _opcoes_de_imovel(db) -> list[tuple[Optional[int], str]]:
    """(id, rótulo) dos imóveis disponíveis, com uma opção vazia na frente.

    Só id e título: carregar o objeto inteiro de 300 imóveis a cada render da
    ficha seria pagar caro por dois campos.
    """
    linhas = (
        db.query(Imovel.id, Imovel.titulo, Imovel.bairro)
        .filter(Imovel.disponivel.is_(True))
        .order_by(Imovel.titulo)
        .all()
    )
    return [(None, "— nenhum —")] + [
        (id_, f"#{id_} · {titulo} ({bairro})") for id_, titulo, bairro in linhas
    ]


def _formulario_de_agendamento(lead: Lead, agendamento_id: Optional[int]) -> None:
    """Cria um agendamento, ou reescreve um existente.

    O mesmo formulário serve aos dois casos: os campos são idênticos e o que
    muda é de onde vêm os valores iniciais. Só a edição mostra o status —
    agendamento novo nasce sempre `pendente`.
    """
    editando = agendamento_id is not None

    with get_db() as db:
        opcoes = _opcoes_de_imovel(db)
        atual = SchedulingService().get(agendamento_id, db) if editando else None
        if editando and atual is None:
            st.error("Agendamento não encontrado. Ele pode ter sido excluído.")
            return
        inicial = {
            "tipo": atual.tipo if atual else "visita",
            "quando": (
                para_exibir(atual.data_hora) if atual
                else agora() + timedelta(days=1)
            ),
            "status": atual.status if atual else "pendente",
            "observacoes": (atual.observacoes if atual else "") or "",
            "imovel_id": atual.imovel_id if atual else None,
        }

    ids = [id_ for id_, _ in opcoes]
    rotulos = dict(opcoes)

    with st.form(f"agendamento_{agendamento_id or 'novo'}"):
        col_tipo, col_data, col_hora = st.columns(3)
        tipo = col_tipo.selectbox(
            "Tipo", TIPOS_DE_AGENDAMENTO,
            index=TIPOS_DE_AGENDAMENTO.index(inicial["tipo"]),
        )
        data = col_data.date_input("Data", value=inicial["quando"].date())
        hora = col_hora.time_input(
            "Hora", value=inicial["quando"].time(), step=timedelta(minutes=15)
        )

        imovel_id = st.selectbox(
            "Imóvel",
            ids,
            index=ids.index(inicial["imovel_id"])
            if inicial["imovel_id"] in ids else 0,
            format_func=lambda i: rotulos[i],
            help="Opcional. Uma reunião de alinhamento não precisa de imóvel.",
        )
        observacoes = st.text_area(
            "Observações", value=inicial["observacoes"], height=90,
            placeholder="O que o corretor precisa saber antes de ir.",
        )
        status = (
            st.selectbox(
                "Status", STATUS_DE_AGENDAMENTO,
                index=STATUS_DE_AGENDAMENTO.index(inicial["status"]),
            )
            if editando
            else "pendente"
        )

        col_salvar, col_cancelar = st.columns([1, 4])
        salvou = col_salvar.form_submit_button(
            "Salvar" if editando else "Agendar",
            icon=":material/event_available:",
            type="primary",
        )
        fechou = col_cancelar.form_submit_button("Cancelar", icon=":material/close:")

    if fechou:
        st.session_state.pop(CHAVE_AGENDAMENTO, None)
        st.rerun()

    if salvou:
        # O formulário devolve hora de São Paulo; o banco guarda em UTC.
        quando = para_guardar(datetime.combine(data, hora))
        servico = SchedulingService()
        with get_db() as db:
            if editando:
                servico.editar(
                    agendamento_id, db, tipo=tipo, data_hora=quando,
                    status=status, observacoes=observacoes.strip() or None,
                    imovel_id=imovel_id,
                )
            else:
                servico.create(
                    lead_id=lead.id, tipo=tipo, data_hora=quando,
                    observacoes=observacoes.strip() or None, db=db,
                    imovel_id=imovel_id,
                )
        st.session_state.pop(CHAVE_AGENDAMENTO, None)
        st.toast(
            "Agendamento salvo." if editando else "Agendamento criado.",
            icon=":material/event_available:",
        )
        st.rerun()


def _confirmar_exclusao_de_agendamento(
    agendamento_id: int, tipo: str, data_hora: datetime
) -> None:
    """Segundo clique da exclusao, logo abaixo do agendamento.

    Excluir apaga o registro de vez. Quando a visita existiu e nao aconteceu, o
    caminho e marcar `cancelado` na edicao — isso aqui e para o compromisso que
    nunca deveria ter sido criado.
    """
    if st.session_state.get(CHAVE_EXCLUSAO_DE_AGENDAMENTO) != agendamento_id:
        return

    st.warning(
        f"Excluir a {tipo} de {formatar(data_hora)}? "
        "Para registrar que ela não aconteceu, use o status **cancelado**.",
        icon=":material/warning:",
    )
    col_sim, col_nao, _ = st.columns([2, 2, 6])
    if col_sim.button(
        "Confirmar", key=f"confirma_ag_{agendamento_id}", type="primary",
        width="stretch",
    ):
        with get_db() as db:
            SchedulingService().excluir(agendamento_id, db)
        st.session_state.pop(CHAVE_EXCLUSAO_DE_AGENDAMENTO, None)
        st.toast("Agendamento excluído.", icon=":material/delete:")
        st.rerun()
    if col_nao.button(
        "Cancelar", key=f"cancela_ag_{agendamento_id}", width="stretch"
    ):
        st.session_state.pop(CHAVE_EXCLUSAO_DE_AGENDAMENTO, None)
        st.rerun()


def _agendamentos(lead: Lead) -> None:
    aberto = st.session_state.get(CHAVE_AGENDAMENTO)
    if aberto is not None and aberto[0] == lead.id:
        _formulario_de_agendamento(lead, aberto[1])
        return

    with get_db() as db:
        itens = [
            (
                a.id, a.tipo, a.data_hora, a.status,
                a.imovel.titulo if a.imovel else None,
                a.imovel.id if a.imovel else None,
                a.observacoes,
            )
            for a in SchedulingService().list_by_lead(lead.id, db)
        ]

    if st.button(
        "Novo agendamento", icon=":material/event:", key=f"novo_ag_{lead.id}"
    ):
        st.session_state[CHAVE_AGENDAMENTO] = (lead.id, None)
        st.rerun()

    if not itens:
        st.caption("Nenhum agendamento para este lead.")
        return

    for id_, tipo, data_hora, status, titulo, imovel_id, observacoes in itens:
        with st.container(border=True):
            col_quando, col_status, col_acoes = st.columns(
                [7, 3, 2], vertical_alignment="center"
            )
            with col_quando:
                st.markdown(f"**{tipo.capitalize()}** · {formatar(data_hora)}")
                if titulo:
                    st.caption(f":material/home: #{imovel_id} · {titulo}")
                if observacoes:
                    st.caption(markdown_seguro(observacoes))
            with col_status:
                cor = COR_DO_STATUS_DE_AGENDAMENTO.get(status, "gray")
                st.markdown(f":{cor}-badge[{status}]")
            with col_acoes:
                col_editar, col_excluir = st.columns(2)
                if col_editar.button(
                    "", icon=":material/edit:", key=f"editar_ag_{id_}",
                    help="Editar este agendamento", type="tertiary",
                ):
                    st.session_state[CHAVE_AGENDAMENTO] = (lead.id, id_)
                    st.rerun()
                if col_excluir.button(
                    "", icon=":material/delete:", key=f"excluir_ag_{id_}",
                    help="Excluir este agendamento", type="tertiary",
                ):
                    st.session_state[CHAVE_EXCLUSAO_DE_AGENDAMENTO] = id_
                    st.rerun()

            _confirmar_exclusao_de_agendamento(id_, tipo, data_hora)


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


def _avisos_e_confirmacao(lead: Lead) -> None:
    """Desfecho do follow-up e confirmacao de exclusao, na largura da pagina.

    Fora do cabecalho de proposito: espremidos na faixa dos botoes de icone
    eles quebrariam em varias linhas, e a confirmacao de uma acao sem desfazer
    precisa de espaco para ser lida antes de clicada.
    """
    aviso = st.session_state.get(CHAVE_AVISO_FOLLOWUP)
    if aviso and aviso[0] == lead.id:
        mostrar = st.success if aviso[1] == "ok" else st.info
        mostrar(aviso[2], icon=":material/send:")

    if st.session_state.get(CHAVE_EXCLUSAO) != lead.id:
        return

    st.warning(
        f"Excluir **{markdown_seguro(rotulo_do_lead(lead))}** e todas as suas "
        "mensagens?",
        icon=":material/warning:",
    )
    col_sim, col_nao, _ = st.columns([2, 2, 8])
    if col_sim.button("Confirmar", type="primary", width="stretch"):
        with get_db() as db:
            LeadService().delete_lead(lead.id, db)
        st.toast("Lead excluído.", icon=":material/delete:")
        _voltar_para_a_lista()
    if col_nao.button("Cancelar", width="stretch"):
        st.session_state.pop(CHAVE_EXCLUSAO, None)
        st.rerun()


def _cabecalho_da_ficha(lead: Optional[Lead]) -> None:
    """Uma faixa so: voltar, nome com selos e as acoes do lead.

    Os tres botoes viram icones com tooltip e sobem para a linha do nome. Em
    tamanho cheio e empilhados eles ocupavam um terco da altura util da ficha,
    e "Excluir lead" desenhado na largura de meia tela pesava mais que o
    proprio lead.
    """
    col_voltar, col_titulo, col_acoes = st.columns(
        [1, 7, 2], vertical_alignment="center"
    )
    with col_voltar:
        if st.button(
            "", icon=":material/arrow_back:", key="voltar_da_ficha",
            help="Voltar para a lista", type="tertiary",
        ):
            _voltar_para_a_lista()

    with col_titulo:
        if lead is None:
            st.subheader("Novo lead")
            return
        st.subheader(markdown_seguro(rotulo_do_lead(lead)))
        st.markdown(selos_do_lead(lead, float(lead.score or 0)))

    with col_acoes:
        # `horizontal_alignment="right"` encosta os dois no canto. Em colunas
        # de larguras iguais eles ficavam no inicio de cada metade, soltos no
        # meio da faixa.
        with st.container(horizontal=True, horizontal_alignment="right"):
            if st.button(
                "", icon=":material/send:", key="acao_followup_da_ficha",
                help=(
                    "Disparar follow-up: mesma régua do automático, sem "
                    "esperar a janela de inatividade."
                ),
                type="tertiary",
            ):
                _disparar_followup(lead)
            # Some enquanto a confirmacao esta aberta, para nao ficarem dois
            # botoes de excluir na mesma tela.
            if st.session_state.get(CHAVE_EXCLUSAO) != lead.id and st.button(
                "", icon=":material/delete:", key="acao_excluir_da_ficha",
                help="Excluir este lead", type="tertiary",
            ):
                st.session_state[CHAVE_EXCLUSAO] = lead.id
                st.rerun()


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
        return

    _cabecalho_da_ficha(lead)
    _avisos_e_confirmacao(lead)
    st.divider()

    ficha, resumo, canal, conversa, agenda = st.tabs(
        ["Ficha", "Resumo", "Canal", "Conversa", "Agendamentos"]
    )
    with ficha:
        _formulario(lead)
    with resumo:
        _resumo_para_o_corretor(lead)
    with canal:
        _canal_do_lead(lead)
    with conversa:
        _conversa(lead)
    with agenda:
        _agendamentos(lead)


def render_leads() -> None:
    """Pagina da listagem (`/leads`), a que o menu aponta."""
    st.header("Leads", divider="gray")
    with get_db() as db:
        _lista(db)


def render_ficha() -> None:
    """Pagina da ficha (`/lead`), fora do menu.

    Chegar aqui sem lead escolhido acontece quando alguem abre a URL direto ou
    recarrega depois de excluir: nesse caso volta para a lista, em vez de
    mostrar uma ficha vazia.
    """
    st.header("Leads", divider="gray")

    lead_aberto = st.session_state.get(CHAVE_LEAD_ABERTO)
    if lead_aberto is None:
        abrir_lista_de_leads()
        return

    _ficha(lead_aberto)
