"""O alerta de orçamento de LLM no dashboard.

O bloqueio por orçamento é abrupto: a conversa em andamento simplesmente para,
e a pessoa do outro lado recebe um aviso de indisponibilidade no meio do
atendimento. Foi o que aconteceu num teste real. Estes testes cobrem o degrau
que avisa antes disso.
"""

from src.ui.dashboard import LIMIAR_DE_AVISO, TOKENS_POR_TURNO, aviso_de_budget


def _resumo(
    daily_tokens=0, daily_budget=500_000,
    monthly_tokens=0, monthly_budget=3_000_000,
    daily_exceeded=False, monthly_exceeded=False,
):
    return {
        "daily_tokens": daily_tokens,
        "daily_budget": daily_budget,
        "monthly_tokens": monthly_tokens,
        "monthly_budget": monthly_budget,
        "daily_budget_exceeded": daily_exceeded,
        "monthly_budget_exceeded": monthly_exceeded,
    }


def test_orcamento_folgado_nao_avisa_nada():
    assert aviso_de_budget(_resumo(daily_tokens=50_000)) is None


def test_abaixo_do_limiar_ainda_nao_avisa():
    quase = int(500_000 * LIMIAR_DE_AVISO) - 1

    assert aviso_de_budget(_resumo(daily_tokens=quase)) is None


def test_no_limiar_avisa():
    nivel, texto, _ = aviso_de_budget(_resumo(daily_tokens=400_000))

    assert nivel == "info"
    assert "80%" in texto


def test_o_aviso_traduz_o_saldo_em_turnos():
    """Tokens não dizem nada a quem atende; "quantos turnos ainda dá", sim."""
    restam = 80_000
    _, texto, _ = aviso_de_budget(_resumo(daily_tokens=500_000 - restam))

    assert f"{restam // TOKENS_POR_TURNO} turnos" in texto


def test_o_saldo_sai_no_formato_brasileiro():
    _, texto, _ = aviso_de_budget(_resumo(daily_tokens=420_000))

    assert "80.000" in texto


def test_manda_o_periodo_mais_apertado():
    """Adianta pouco sobrar mês se o dia é que está acabando."""
    _, texto, _ = aviso_de_budget(
        _resumo(daily_tokens=450_000, monthly_tokens=500_000)
    )

    assert "diário" in texto


def test_mes_apertado_tambem_aparece():
    _, texto, _ = aviso_de_budget(
        _resumo(daily_tokens=10_000, monthly_tokens=2_900_000)
    )

    assert "mensal" in texto


def test_estouro_diario_vence_o_aviso_de_aproximacao():
    nivel, texto, _ = aviso_de_budget(
        _resumo(daily_tokens=500_000, daily_exceeded=True)
    )

    assert nivel == "warning"
    assert "esgotado" in texto


def test_estouro_mensal_vence_o_diario():
    """O mensal é o mais grave: não passa à meia-noite."""
    nivel, texto, _ = aviso_de_budget(
        _resumo(daily_exceeded=True, monthly_exceeded=True)
    )

    assert nivel == "error"
    assert "mensal" in texto


def test_orcamento_zerado_nao_divide_por_zero():
    assert aviso_de_budget(_resumo(daily_budget=0, monthly_budget=0)) is None
