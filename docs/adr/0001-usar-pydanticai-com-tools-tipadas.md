# ADR 0001 — Usar PydanticAI com tools tipadas

- **Status:** Aceito
- **Data:** 2026-09-16

## Contexto

A POC precisa implementar um agente conversacional com:
- saídas estruturadas;
- integração com ferramentas de domínio;
- baixo esforço de parsing manual;
- flexibilidade para trocar provider LLM.

A equipe precisa de uma solução produtiva para hackathon, mas com base técnica suficientemente sólida para evolução posterior.

## Decisão

Adotar **PydanticAI** como framework principal do agente, com uso de **schemas Pydantic v2** e **tools tipadas** para integração com serviços de domínio.

## Alternativas consideradas

### 1. Implementação manual com SDK OpenAI-compatible
- **Prós:** controle total, menos abstração.
- **Contras:** mais código de orquestração, parsing manual, maior risco de inconsistência.

### 2. LangChain/LangGraph
- **Prós:** ecossistema amplo, muitos exemplos.
- **Contras:** maior complexidade para a POC, mais camadas conceituais do que o necessário.

### 3. Framework próprio mínimo
- **Prós:** simplicidade aparente.
- **Contras:** custo de manutenção, menor padronização, maior risco de acoplamento.

## Consequências

### Positivas
- reduz parsing manual;
- facilita validação de entradas e saídas;
- melhora clareza dos contratos entre agente e aplicação;
- acelera implementação da POC.

### Negativas
- adiciona dependência de framework específico;
- exige familiaridade da equipe com o modelo mental do framework.

## Impacto arquitetural

O agente passa a ser o orquestrador de alto nível, enquanto regras de negócio e persistência permanecem em services e repositórios.
