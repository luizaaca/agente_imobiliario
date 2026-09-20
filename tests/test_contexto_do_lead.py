"""Contexto do lead injetado no system prompt.

Listar todos os campos, com "Nao informado" ao lado dos vazios, entrega ao
modelo um formulario em branco — e ele passa a conduzir a conversa assim,
pedindo os campos em sequencia. Estes testes fixam o que entra no contexto e,
principalmente, o que nao entra.
"""

from decimal import Decimal

from src.agent.sdr_agent import montar_contexto_do_lead
from src.db.models import Lead


def _lead(**campos) -> Lead:
    return Lead(status=campos.pop("status", "em_qualificacao"), **campos)


def test_sem_lead_avisa_que_e_a_primeira_mensagem():
    assert "Primeira mensagem" in montar_contexto_do_lead(None)


def test_campo_vazio_nao_vira_linha_no_contexto():
    contexto = montar_contexto_do_lead(_lead(intencao="compra"))

    assert "Quer: compra" in contexto
    assert "Não informado" not in contexto
    assert "Quartos" not in contexto
    assert "Orçamento" not in contexto


def test_lacunas_aparecem_como_anotacao_e_nao_como_roteiro():
    contexto = montar_contexto_do_lead(_lead(intencao="compra"))

    assert "Ainda em aberto:" in contexto
    assert "orçamento" in contexto
    assert "não pergunte esses itens em sequência" in contexto.lower()


def test_lead_completo_nao_tem_secao_de_lacunas():
    contexto = montar_contexto_do_lead(
        _lead(
            intencao="compra",
            orcamento_max=Decimal("700000"),
            bairro_interesse="Bela Vista",
            quartos=2,
            urgencia="alta",
        )
    )

    assert "Ainda em aberto" not in contexto


def test_orcamento_so_com_teto_e_escrito_como_ate():
    contexto = montar_contexto_do_lead(_lead(orcamento_max=Decimal("700000")))

    assert "Orçamento: até R$ 700.000" in contexto


def test_orcamento_com_faixa_mostra_os_dois_extremos():
    contexto = montar_contexto_do_lead(
        _lead(orcamento_min=Decimal("400000"), orcamento_max=Decimal("700000"))
    )

    assert "de R$ 400.000 a R$ 700.000" in contexto


def test_lead_novo_sem_dado_nenhum_diz_isso_explicitamente():
    contexto = montar_contexto_do_lead(_lead(status="novo"))

    assert "ainda não sabe nada" in contexto
    assert "Estágio no funil: novo." in contexto
