"""Testes da factory de provider LLM."""

import asyncio

import pytest

from src.agent import provider as provider_mod
from src.agent.provider import LLMConfigError, _construir_modelo, build_model


@pytest.fixture(autouse=True)
def configuracao_limpa(monkeypatch):
    """Cada teste parte de uma configuração conhecida e sem cache.

    As variáveis de ambiente também são removidas: quando não recebe
    `base_url`, o SDK da OpenAI cai no `OPENAI_BASE_URL` do ambiente, e o .env
    do desenvolvedor vazaria para dentro dos testes.
    """
    for variavel in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
        monkeypatch.delenv(variavel, raising=False)

    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(provider_mod.settings, "LLM_MODEL", "modelo-de-teste")
    monkeypatch.setattr(provider_mod.settings, "OPENAI_API_KEY", "sk-teste")
    monkeypatch.setattr(provider_mod.settings, "OPENAI_BASE_URL", "")
    monkeypatch.setattr(provider_mod, "_modelo_sem_loop", None)
    provider_mod._modelos_por_loop.clear()


def base_url_de(modelo):
    return str(modelo._provider.client.base_url)


# --- Resolução de provider ---------------------------------------------------


def test_openai_usa_o_endpoint_padrao(monkeypatch):
    modelo = _construir_modelo()
    assert modelo.model_name == "modelo-de-teste"
    assert "openai.com" in base_url_de(modelo)


@pytest.mark.parametrize(
    "provider,trecho_esperado",
    [
        ("groq", "api.groq.com"),
        ("gemini", "generativelanguage.googleapis.com"),
        ("ollama", "localhost:11434"),
    ],
)
def test_cada_provider_resolve_sua_base_url(monkeypatch, provider, trecho_esperado):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", provider)
    assert trecho_esperado in base_url_de(_construir_modelo())


def test_base_url_explicita_vence_o_padrao_do_provider(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(provider_mod.settings, "OPENAI_BASE_URL", "https://meu.endpoint/v1")
    assert "meu.endpoint" in base_url_de(_construir_modelo())


def test_provider_aceita_maiusculas_e_espacos(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "  GROQ ")
    assert "api.groq.com" in base_url_de(_construir_modelo())


def test_provider_vazio_assume_openai(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "")
    assert "openai.com" in base_url_de(_construir_modelo())


# --- Erros de configuração ---------------------------------------------------


def test_provider_desconhecido_falha_com_mensagem_util(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "inventado")
    with pytest.raises(LLMConfigError, match="não é suportado"):
        _construir_modelo()


def test_chave_ausente_falha(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "OPENAI_API_KEY", "")
    with pytest.raises(LLMConfigError, match="OPENAI_API_KEY"):
        _construir_modelo()


def test_ollama_dispensa_chave(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(provider_mod.settings, "OPENAI_API_KEY", "")
    assert _construir_modelo() is not None


def test_custom_sem_base_url_falha(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "custom")
    with pytest.raises(LLMConfigError, match="OPENAI_BASE_URL"):
        _construir_modelo()


def test_custom_com_base_url_funciona(monkeypatch):
    monkeypatch.setattr(provider_mod.settings, "LLM_PROVIDER", "custom")
    monkeypatch.setattr(provider_mod.settings, "OPENAI_BASE_URL", "https://interno/v1")
    assert "interno" in base_url_de(_construir_modelo())


# --- Cache por event loop ----------------------------------------------------


def test_mesmo_loop_reaproveita_o_modelo():
    async def obter_duas_vezes():
        return build_model(), build_model()

    primeiro, segundo = asyncio.run(obter_duas_vezes())
    assert primeiro is segundo


def test_loops_diferentes_recebem_modelos_diferentes():
    """Regressão: um modelo cacheado globalmente morria junto com o loop.

    O Streamlit abre um asyncio.run() por mensagem, então reaproveitar o
    cliente entre loops quebrava com 'Event loop is closed'.
    """
    primeiro = asyncio.run(_pegar_modelo())
    segundo = asyncio.run(_pegar_modelo())
    assert primeiro is not segundo


async def _pegar_modelo():
    return build_model()


def test_sem_loop_corrente_tambem_funciona():
    assert build_model() is build_model()
