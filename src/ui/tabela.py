"""Tabela de leads compartilhada pelo dashboard e pelo menu de Leads.

Linhas montadas com `st.columns`, e nao `st.dataframe`: uma celula de dataframe
e desenhada em canvas e nao comporta botao nenhum — foi o que impediu a lupa de
funcionar como link. Com colunas, cada linha tem botoes de verdade, com icone,
tooltip e alvo de clique previsivel.

O preco e a ordenacao: sem o dataframe nao ha clique no cabecalho, entao ela
vira um controle explicito (`seletor_de_ordem`), que as duas telas montam
acima da tabela.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Optional

import streamlit as st
from sqlalchemy import String, cast, func, or_

from src.db.models import Lead
from src.ui.texto import markdown_seguro


@dataclass(frozen=True)
class Coluna:
    """Uma coluna da tabela: cabecalho, largura relativa e como extrair o valor."""

    titulo: str
    peso: int
    valor: Callable[[Lead], str]


@dataclass(frozen=True)
class Acao:
    """Um botao de icone no fim da linha."""

    icone: str
    ajuda: str
    chave: str
    callback: Callable[[Lead], None]


def rotulo_do_lead(lead: Lead) -> str:
    """Como o lead aparece na tela: o nome, ou `Lead <id>` quando nao ha nome."""
    return lead.nome or f"Lead {lead.id}"


def _rotulo_em_sql():
    """A mesma regra de `rotulo_do_lead`, mas para o banco ordenar por ela.

    Sem isso, "Nome (A-Z)" ordenava pela coluna `nome` — que na maioria dos
    leads e nula, porque o nome so aparece quando a pessoa o diz na conversa.
    O resultado era uma ordenacao que nao correspondia a nada do que a tela
    mostra. Aqui ela ordena pelo rotulo visivel.
    """
    return func.coalesce(
        func.nullif(func.trim(Lead.nome), ""), "Lead " + cast(Lead.id, String)
    )


# Ordenacoes oferecidas. O score decrescente vem primeiro porque e a leitura
# que a tela existe para dar: quem ligar primeiro no topo.
ORDENS = {
    "Score (maior primeiro)": (lambda: Lead.score, True),
    "Score (menor primeiro)": (lambda: Lead.score, False),
    "Nome (A-Z)": (_rotulo_em_sql, False),
    "Nome (Z-A)": (_rotulo_em_sql, True),
    "Atualizado recentemente": (lambda: Lead.updated_at, True),
    "Mais antigos": (lambda: Lead.created_at, False),
}


def seletor_de_ordem(chave: str) -> tuple[Callable, bool]:
    """Desenha o seletor e devolve (expressao, decrescente)."""
    escolha = st.selectbox(
        "Ordenar por",
        list(ORDENS),
        key=chave,
        help="Nome ordena pelo rótulo que aparece na tabela.",
    )
    return ORDENS[escolha]


def aplicar_ordem(query, expressao: Callable, decrescente: bool):
    """Ordena a query, mandando os nulos para o fim em qualquer sentido.

    Desempata por `id` para a ordem nao dancar entre recargas quando varios
    leads tem o mesmo valor — score igual e o caso comum.
    """
    coluna = expressao()
    ordenacao = coluna.desc() if decrescente else coluna.asc()
    return query.order_by(ordenacao.nullslast(), Lead.id.asc())


# Campos varridos pela busca livre. O que o placeholder promete e o que ela
# olha precisam ser a mesma lista: `intencao` faltava aqui, entao procurar
# "compra" so achava os leads cujo perfil narrativo por acaso citava a palavra.
CAMPOS_DA_BUSCA = (
    Lead.nome,
    Lead.telefone,
    Lead.intencao,
    Lead.bairro_interesse,
    Lead.regiao_interesse,
    Lead.tipologia_interesse,
    Lead.perfil,
    Lead.motivo_busca,
    Lead.amenidades_desejadas,
    Lead.perfil_narrativo,
)


def filtro_de_busca(termo: str):
    """Condicao `OR` sobre todos os campos de texto que a busca cobre."""
    padrao = f"%{termo.strip()}%"
    return or_(*(campo.ilike(padrao) for campo in CAMPOS_DA_BUSCA))


def _cabecalho(colunas: Sequence[Coluna], peso_das_acoes: int) -> None:
    celulas = st.columns([c.peso for c in colunas] + [peso_das_acoes])
    for celula, coluna in zip(celulas, colunas, strict=False):
        celula.caption(f"**{coluna.titulo}**")
    st.divider()


def _linha(
    lead: Lead,
    colunas: Sequence[Coluna],
    acoes: Sequence[Acao],
    peso_das_acoes: int,
) -> None:
    celulas = st.columns(
        [c.peso for c in colunas] + [peso_das_acoes], vertical_alignment="center"
    )
    for celula, coluna in zip(celulas, colunas, strict=False):
        celula.markdown(coluna.valor(lead))

    with celulas[-1]:
        botoes = st.columns(len(acoes))
        for botao, acao in zip(botoes, acoes, strict=True):
            with botao:
                if st.button(
                    "",
                    icon=acao.icone,
                    key=f"{acao.chave}_{lead.id}",
                    help=acao.ajuda,
                    type="tertiary",
                ):
                    acao.callback(lead)


# Container com chave propria: e por ela que o CSS aperta o espacamento das
# linhas sem mexer em nenhuma outra tabela ou divisoria da aplicacao.
CHAVE_DO_CONTAINER = "tabela_de_leads"


def tabela_de_leads(
    leads: Sequence[Lead],
    colunas: Sequence[Coluna],
    acoes: Sequence[Acao],
    depois_da_linha: Optional[Callable[[Lead], None]] = None,
    peso_das_acoes: int = 2,
) -> None:
    """Desenha a tabela inteira.

    `depois_da_linha` desenha algo na largura toda logo abaixo de um lead —
    e onde a confirmacao de exclusao aparece, para nao ser espremida na
    coluna estreita dos botoes.
    """
    with st.container(key=CHAVE_DO_CONTAINER):
        _cabecalho(colunas, peso_das_acoes)
        for lead in leads:
            _linha(lead, colunas, acoes, peso_das_acoes)
            if depois_da_linha is not None:
                depois_da_linha(lead)


def texto(valor: Optional[str]) -> str:
    """Valor de celula, com travessao quando vazio e cifrao escapado.

    `markdown_seguro` porque uma faixa de orcamento traz dois `R$` na mesma
    celula, e o Streamlit leria o trecho entre eles como formula LaTeX.
    """
    return markdown_seguro(valor) if valor else "—"
