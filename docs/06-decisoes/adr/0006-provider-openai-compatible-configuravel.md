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
