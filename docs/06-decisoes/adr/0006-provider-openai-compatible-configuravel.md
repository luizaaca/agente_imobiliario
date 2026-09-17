# ADR 0006 — Usar provider OpenAI-compatible configurável por ambiente

- **Status:** Aceito
- **Data:** 2026-09-16

## Contexto

A POC precisa manter flexibilidade para:
- trocar modelo;
- trocar provedor;
- controlar custo;
- testar ambientes diferentes sem reescrever a aplicação.

## Decisão

Adotar um **provider OpenAI-compatible configurável por `.env`**, com parâmetros de modelo e endpoint externos ao código.

## Alternativas consideradas

### 1. Acoplamento direto a um único provedor
- **Prós:** simplicidade inicial.
- **Contras:** menor flexibilidade, maior risco de lock-in.

### 2. Abstração própria complexa de múltiplos providers
- **Prós:** flexibilidade máxima.
- **Contras:** complexidade excessiva para a POC.

## Consequências

### Positivas
- facilita troca de modelo/provedor;
- melhora controle de custo e experimentação;
- reduz lock-in técnico.

### Negativas
- exige validação cuidadosa de compatibilidade entre providers;
- diferenças sutis de comportamento podem afetar prompts e tools.

## Impacto arquitetural

A configuração do modelo deve ficar centralizada e externa ao código de domínio.

---

## Variáveis de ambiente canônicas

A nomenclatura definitiva adotada para o projeto é:

| Variável | Obrigatória | Descrição | Exemplo |
|---|:---:|---|---|
| `LLM_PROVIDER` | Sim | Identificador do provedor | `openai`, `groq`, `gemini`, `ollama` |
| `LLM_MODEL` | Sim | Nome do modelo específico | `gpt-4o-mini`, `gemini-2.5-flash` |
| `OPENAI_API_KEY` | Sim | API key do provedor (nome mantido por compatibilidade com SDKs OpenAI-compatible) | `sk-...`, `gsk_...` |
| `OPENAI_BASE_URL` | Não | URL base para provedores alternativos; deixar vazio para OpenAI padrão | `https://generativelanguage.googleapis.com/v1beta/openai/` |

> **Nota sobre nomenclatura**: `OPENAI_API_KEY` e `OPENAI_BASE_URL` usam o prefixo `OPENAI_` por compatibilidade com a maioria dos SDKs e bibliotecas que seguem o padrão OpenAI-compatible (incluindo PydanticAI). O `LLM_PROVIDER` e `LLM_MODEL` são variáveis de projeto que permitem lógica condicional na aplicação.
