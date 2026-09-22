"""Preparo do texto do agente para a tela."""

from src.ui.texto import markdown_seguro, mensagem_para_markdown


def test_cifrao_e_escapado():
    """Sem isso o Streamlit trata o trecho entre dois 'R$' como formula LaTeX."""
    texto = "O studio sai por R$ 390 mil e o **flat** por R$ 490 mil."

    assert markdown_seguro(texto) == (
        r"O studio sai por R\$ 390 mil e o **flat** por R\$ 490 mil."
    )


def test_texto_sem_cifrao_nao_muda():
    assert markdown_seguro("dois quartos em Pinheiros") == "dois quartos em Pinheiros"


def test_quebra_de_linha_sobrevive_ao_markdown():
    """O agente escreve para WhatsApp; o markdown colapsa quebra simples.

    Os tres imoveis que ele mandou em tres linhas chegavam a tela como um
    paragrafo unico, com os marcadores no meio do texto corrido.
    """
    texto = "Encontrei 3 opcoes:\n- Moema\n- Brooklin\n- Saude"

    assert mensagem_para_markdown(texto) == (
        "Encontrei 3 opcoes:  \n- Moema  \n- Brooklin  \n- Saude"
    )


def test_paragrafo_continua_separado():
    """A linha em branco nao pode deixar de separar paragrafo."""
    assert mensagem_para_markdown("primeiro\n\nsegundo") == "primeiro  \n  \nsegundo"


def test_a_mensagem_tambem_escapa_cifrao():
    """As duas transformacoes valem juntas: e a mesma fala do agente."""
    assert mensagem_para_markdown("R$ 900 mil\nou R$ 1 milhao") == (
        "R\\$ 900 mil  \nou R\\$ 1 milhao"
    )
