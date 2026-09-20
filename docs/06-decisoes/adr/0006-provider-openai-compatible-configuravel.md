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

### Revisão de 20/09/2026 — nomenclatura

A versão original desta ADR adotava `OPENAI_API_KEY` e `OPENAI_BASE_URL`, com esta justificativa:

> "usam o prefixo `OPENAI_` por compatibilidade com a maioria dos SDKs e bibliotecas que seguem o padrão OpenAI-compatible (incluindo PydanticAI)".

O argumento não se sustentou na prática, por dois motivos:

1. **A aplicação sempre passa `api_key` e `base_url` explicitamente** ao `OpenAIProvider`. Nunca dependeu da leitura automática de variáveis pelo SDK, então a "compatibilidade" não estava sendo exercida.
2. **O nome ficava incoerente com o próprio modelo de configuração.** `LLM_PROVIDER=gemini` acompanhado de `OPENAI_API_KEY` sugere que a chave é da OpenAI, quando é do Gemini. O prefixo comunicava o oposto do desenho da ADR, que é justamente tratar todos os provedores de forma uniforme.

Renomeadas para `LLM_API_KEY` e `LLM_BASE_URL`, alinhadas a `LLM_PROVIDER` e `LLM_MODEL`.

**Efeito colateral corrigido junto:** o SDK da OpenAI lê `OPENAI_BASE_URL` do ambiente por conta própria quando não recebe `base_url`. Com os nomes antigos, uma variável solta no ambiente redirecionava as chamadas sem nada no código indicar isso. A base URL do provider `openai` passou a ser explícita (`https://api.openai.com/v1`) em vez de omitida, tornando o destino determinado apenas pela configuração da aplicação.
