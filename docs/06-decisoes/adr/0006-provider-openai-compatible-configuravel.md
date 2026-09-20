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
| `LLM_API_KEY` | Sim | Credencial do provedor escolhido | `sk-...`, `gsk_...` |
| `LLM_BASE_URL` | Não | Endpoint OpenAI-compatible; vazio usa o padrão do `LLM_PROVIDER` | `https://generativelanguage.googleapis.com/v1beta/openai/` |

> **Nomenclatura**: todas as variáveis usam o prefixo `LLM_`. A credencial é do provedor escolhido em `LLM_PROVIDER`, não da OpenAI — por isso `LLM_API_KEY`, e não `OPENAI_API_KEY`. A aplicação passa `api_key` e `base_url` explicitamente ao `OpenAIProvider`, sem depender da leitura automática de variáveis pelo SDK.

> **Base URL do provider `openai`**: é passada explicitamente ao SDK (`https://api.openai.com/v1`), e não omitida. O SDK da OpenAI lê `OPENAI_BASE_URL` do ambiente por conta própria quando não recebe `base_url`, e uma variável solta no ambiente redirecionaria as chamadas sem nada no código indicar isso.
