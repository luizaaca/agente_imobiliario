"""Ajustes de aparencia aplicados por cima do tema do Streamlit."""

import streamlit as st

# Largura do rail e tamanho do alvo de clique de cada icone.
_RAIL = 68
_ALVO = 44
# Lado do botao de icone das tabelas, e o maior das acoes de cabecalho — ali
# eles sao as acoes principais da tela, nao um detalhe repetido a cada linha.
_ICONE = 36
_ICONE_GRANDE = 46

# O Streamlit recolhe a barra lateral tirando-a da tela: `width: 0` mais um
# `translateX(-300px)`. O rail desfaz esses dois e devolve 68px de barra, onde
# ficam os icones de navegacao — o mesmo padrao de um Slack ou de um Jira, em
# que recolher esconde os rotulos, nao a navegacao.
#
# Os seletores usam so `data-testid`, que o Streamlit mantem estavel entre
# versoes; as classes `st-emotion-cache-*` mudam a cada build e nao servem de
# ancora. Tudo esta preso a `[aria-expanded="false"]`, entao a barra aberta
# continua exatamente como o Streamlit a desenha.
#
# Ao atualizar o Streamlit, os testids a conferir sao: stSidebar,
# stSidebarContent, stSidebarNavLink, stSidebarCollapseButton e
# stExpandSidebarButton. Se algum sumir, a barra volta ao comportamento
# original de sumir por inteiro — degrada, nao quebra.
_RAIL_CSS = f"""
<style>
/* O que a aplicacao escreve na barra — o menu do usuario — desce para o pe.
   Vale nos dois estados da barra, aberta e em rail. */
[data-testid="stSidebarContent"] {{
  display: flex !important;
  flex-direction: column !important;
  height: 100% !important;
}}
[data-testid="stSidebarUserContent"] {{
  margin-top: auto !important;
  /* O Streamlit reserva 96px abaixo do conteudo da barra. Num rodape isso
     vira um vao morto que descola o avatar da base da tela. */
  padding-top: 8px !important;
  padding-bottom: 10px !important;
  /* Risco tenue separando o rodape dos links de navegacao. `currentColor`
     com alfa baixo funciona no tema claro e no escuro sem fixar cor. */
  border-top: 1px solid color-mix(in srgb, currentColor 14%, transparent);
}}

/* O mesmo risco tenue, agora cortando o menu antes da ajuda e antes do
   simulador: o trabalho do dia em cima, o apoio embaixo.

   E CSS, e nao secao nomeada do `st.navigation`, porque uma chave nomeada
   desenha cabecalho com rotulo e seta de recolher — vira um grupo que se
   fecha, nao um risco.

   Os itens sao escolhidos pelo `href`, e nao pela posicao: o simulador so
   existe no menu do admin, entao a ajuda muda de indice conforme o papel de
   quem entrou. */
[data-testid="stSidebarNavItems"] > li:has(a[href$="/ajuda"]),
[data-testid="stSidebarNavItems"] > li:has(a[href$="/chat"]) {{
  border-top: 1px solid color-mix(in srgb, currentColor 14%, transparent);
  margin-top: 8px;
  padding-top: 8px;
}}

section[data-testid="stSidebar"][aria-expanded="false"] {{
  width: {_RAIL}px !important;
  min-width: {_RAIL}px !important;
  max-width: {_RAIL}px !important;
  transform: none !important;
  overflow: visible !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarContent"] {{
  width: {_RAIL}px !important;
  padding-left: 0 !important;
  padding-right: 0 !important;
  /* visivel para o rotulo flutuante do hover poder sair do rail */
  overflow: visible !important;
}}
/* Arrastar a borda para redimensionar nao faz sentido com 68px fixos. */
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarResizeHandle"] {{
  display: none !important;
}}

/* O botao de recolher da barra alterna os dois estados, entao ele mesmo serve
   de botao de abrir dentro do rail. Fica visivel, centralizado e girado 180deg
   para a seta apontar para fora. Com ele no rail, o botao que o Streamlit poe
   no topo da pagina viraria um segundo controle para a mesma acao. */
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarHeader"] {{
  justify-content: center !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stLogoSpacer"] {{
  display: none !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarCollapseButton"] {{
  visibility: visible !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"] {{
  transform: rotate(180deg) !important;
}}
body:has(section[data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stExpandSidebarButton"] {{
  display: none !important;
}}

/* Cada link vira um quadrado de 44px — o minimo confortavel para toque. */
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] {{
  position: relative !important;
  width: {_ALVO}px !important;
  height: {_ALVO}px !important;
  margin: 4px auto !important;
  padding: 0 !important;
  justify-content: center !important;
  border-radius: 10px !important;
}}
/* Sem rotulo, o fundo do item ativo e a unica indicacao de onde se esta; o
   cinza translucido do proprio Streamlit vale nos temas claro e escuro. */
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: rgba(151, 166, 195, 0.28) !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] [data-testid="stIconEmoji"],
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] [data-testid="stIconMaterial"] {{
  font-size: 20px !important;
  width: 20px !important;
  height: 20px !important;
}}

/* O rotulo sai do fluxo e volta como balao ao lado no hover: um icone sozinho
   nao diz para onde leva. */
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"] > span:last-child {{
  display: none !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarNavLink"]:hover > span:last-child {{
  display: block !important;
  position: absolute !important;
  left: 52px !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  z-index: 1000 !important;
  white-space: nowrap !important;
  padding: 5px 10px !important;
  border-radius: 8px !important;
  font-size: 0.82rem !important;
  /* Fundo escuro com borda clara: legivel sobre a barra clara e sobre a
     escura, sem depender de qual tema o navegador escolheu. */
  background: rgba(38, 39, 48, 0.96) !important;
  color: #fff !important;
  border: 1px solid rgba(255, 255, 255, 0.16) !important;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.3) !important;
}}

/* No rail o botao do usuario perde o nome e a seta e vira so o avatar, no
   mesmo alvo de 44px dos links — senao um botao de 300px sobraria da barra. */
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarUserContent"] {{
  padding-left: 0 !important;
  padding-right: 0 !important;
}}
/* O gatilho do popover e `inline-flex`, e `margin: auto` nao centraliza caixa
   em linha — so bloco. Quem centraliza e o container virar flex. */
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stSidebarUserContent"] [data-testid="stPopover"] {{
  display: flex !important;
  justify-content: center !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stPopoverButton"] {{
  width: {_ALVO}px !important;
  min-width: {_ALVO}px !important;
  height: {_ALVO}px !important;
  padding: 0 !important;
  justify-content: center !important;
  border-radius: 10px !important;
}}
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stPopoverButton"] [data-testid="stMarkdownContainer"],
section[data-testid="stSidebar"][aria-expanded="false"] [data-testid="stPopoverButton"] div[aria-hidden="true"] {{
  display: none !important;
}}

/* A divisoria do cabecalho da tabela de leads usa o espacamento generoso que
   o Streamlit da a um separador de secao; entre cabecalho e primeira linha
   isso abre um vao que solta um do outro. */
.st-key-tabela_de_leads hr {{
  margin-top: 0.25rem !important;
  margin-bottom: 0.25rem !important;
}}
/* Linhas mais juntas, para a tabela se varrer de cima a baixo. */
.st-key-tabela_de_leads [data-testid="stHorizontalBlock"] {{
  margin-bottom: -0.35rem !important;
}}

/* Botoes de icone das tabelas de lead e da lista de agendamentos. O Streamlit
   publica a `key` do widget como classe `st-key-<key>`, entao o alvo aqui sao
   exatamente as chaves escolhidas em `tabela.Acao` e em `leads`, e nao "todo
   botao tertiary da aplicacao".

   Um `tertiary` sem rotulo sai como um icone solto, sem area de clique
   visivel. Aqui ele vira um quadrado de 36px com cantos arredondados e fundo
   no hover: alvo previsivel, e discreto o bastante para caber repetido em
   toda linha da tabela. */
[class*="st-key-acao_abrir_"] button,
[class*="st-key-acao_editar_"] button,
[class*="st-key-acao_excluir_"] button,
[class*="st-key-editar_ag_"] button,
[class*="st-key-excluir_ag_"] button,
.st-key-novo_lead button {{
  width: {_ICONE}px !important;
  min-width: {_ICONE}px !important;
  height: {_ICONE}px !important;
  padding: 0 !important;
  justify-content: center !important;
  border-radius: 8px !important;
  color: color-mix(in srgb, currentColor 62%, transparent) !important;
  transition: background 120ms ease, color 120ms ease !important;
}}
[class*="st-key-acao_abrir_"] button:hover,
[class*="st-key-acao_editar_"] button:hover,
[class*="st-key-editar_ag_"] button:hover,
.st-key-voltar_da_ficha button:hover,
.st-key-acao_followup_da_ficha button:hover {{
  color: inherit !important;
  background: color-mix(in srgb, currentColor 10%, transparent) !important;
}}
/* Excluir e a unica acao sem desfazer: o vermelho so aparece no hover, para
   nao gritar em toda linha da tabela, mas aparece antes do clique. */
[class*="st-key-acao_excluir_"] button:hover,
[class*="st-key-excluir_ag_"] button:hover,
.st-key-acao_excluir_da_ficha button:hover {{
  color: #DC2626 !important;
  background: rgba(220, 38, 38, 0.10) !important;
}}

/* Acoes do cabecalho da ficha: mesmo desenho, um tamanho acima, e o icone
   maior junto — em 36px e cinza claro elas sumiam ao lado do nome do lead. */
.st-key-voltar_da_ficha button,
.st-key-acao_followup_da_ficha button,
.st-key-acao_excluir_da_ficha button {{
  width: {_ICONE_GRANDE}px !important;
  min-width: {_ICONE_GRANDE}px !important;
  height: {_ICONE_GRANDE}px !important;
  padding: 0 !important;
  justify-content: center !important;
  border-radius: 10px !important;
  color: color-mix(in srgb, currentColor 78%, transparent) !important;
  transition: background 120ms ease, color 120ms ease !important;
}}
.st-key-voltar_da_ficha button [data-testid="stIconMaterial"],
.st-key-acao_followup_da_ficha button [data-testid="stIconMaterial"],
.st-key-acao_excluir_da_ficha button [data-testid="stIconMaterial"],
.st-key-novo_lead button [data-testid="stIconMaterial"] {{
  font-size: 22px !important;
  width: 22px !important;
  height: 22px !important;
}}
</style>
"""


def aplicar_estilo() -> None:
    """Injeta o CSS da aplicacao. Chamar uma vez, antes de montar a pagina."""
    st.markdown(_RAIL_CSS, unsafe_allow_html=True)
