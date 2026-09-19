"""Escape de markdown na exibicao."""

from src.ui.texto import markdown_seguro


def test_cifrao_e_escapado():
    """Sem isso o Streamlit trata o trecho entre dois 'R$' como formula LaTeX."""
    texto = "O studio sai por R$ 390 mil e o **flat** por R$ 490 mil."

    assert markdown_seguro(texto) == (
        r"O studio sai por R\$ 390 mil e o **flat** por R\$ 490 mil."
    )


def test_texto_sem_cifrao_nao_muda():
    assert markdown_seguro("dois quartos em Pinheiros") == "dois quartos em Pinheiros"
