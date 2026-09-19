"""Preparo de texto para exibicao na UI."""


def markdown_seguro(texto: str) -> str:
    """Escapa o que o markdown do Streamlit interpretaria como formula.

    O `st.markdown` renderiza `$...$` como LaTeX. Uma mensagem com dois preços
    ("R$ 390 mil" ... "R$ 460 mil") vira uma formula: os cifrões somem e o
    texto entre eles sai embaralhado, junto com a negrito que estiver no meio.

    Escapar so na exibicao, e nao no que se grava, mantem o conteudo original
    intacto no banco e no historico enviado ao modelo.
    """
    return texto.replace("$", r"\$")
