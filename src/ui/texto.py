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


def mensagem_para_markdown(texto: str) -> str:
    """Fala de conversa pronta para `st.markdown`, com as quebras preservadas.

    O agente escreve para o WhatsApp, onde uma quebra de linha e uma quebra de
    linha — a persona diz isso a ele. O markdown colapsa quebra simples em
    espaco, entao a lista de tres imoveis que ele mandou em tres linhas chegava
    a tela como um paragrafo unico, com os marcadores no meio do texto corrido.

    Dois espacos no fim da linha sao a quebra forte do markdown: preservam a
    linha sem precisar de HTML — que aqui seria abrir a tela para o que o
    modelo escrever — e a linha em branco continua separando paragrafo.
    """
    return markdown_seguro(texto).replace("\n", "  \n")
