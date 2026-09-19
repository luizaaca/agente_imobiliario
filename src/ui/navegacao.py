"""Navegacao entre as abas da UI.

Existe como modulo proprio para o dashboard conseguir mandar o usuario para o
simulador sem importar o chat (e vice-versa).

As abas rodam com `key` e `on_change="rerun"`, entao o Streamlit guarda o
rotulo da aba ativa em `st.session_state[CHAVE_NAV]` e aceita que a gente
escreva nele — e assim "Abrir no simulador" consegue trocar de aba.
"""

import streamlit as st

PAGINA_CHAT = "💬 Chat Simulador"
PAGINA_DASHBOARD = "📊 Dashboard"
PAGINAS = [PAGINA_CHAT, PAGINA_DASHBOARD]

CHAVE_NAV = "nav"
# Lead que o dashboard pediu para abrir no simulador. O chat consome e limpa.
CHAVE_CONVERSA_PEDIDA = "conversa_pedida"


def ir_para(pagina: str) -> None:
    """Troca de aba.

    So pode ser chamada de um `on_click`/`on_change`: os callbacks rodam antes
    do rerun, quando as abas ainda nao foram instanciadas. Fora deles, o
    Streamlit recusa a escrita em uma chave de widget ja criada no ciclo.
    """
    st.session_state[CHAVE_NAV] = pagina


def abrir_conversa_no_simulador(lead_id: int) -> None:
    """Callback do dashboard: leva o lead para a aba do chat."""
    st.session_state[CHAVE_CONVERSA_PEDIDA] = lead_id
    ir_para(PAGINA_CHAT)


def conversa_pedida() -> int | None:
    """Consome o pedido pendente de abertura de conversa, se houver."""
    return st.session_state.pop(CHAVE_CONVERSA_PEDIDA, None)
