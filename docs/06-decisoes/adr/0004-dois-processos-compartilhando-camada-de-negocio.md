# ADR 0004 — Executar Streamlit e Telegram em dois processos independentes

- **Status:** Aceito
- **Data:** 2026-09-16

## Contexto

A solução possui duas responsabilidades operacionais distintas:
- interface Streamlit para simulação e dashboard;
- bot Telegram com polling contínuo e scheduler de follow-up.

Misturar tudo em um único processo aumentaria acoplamento operacional e complexidade de ciclo de vida.

## Decisão

Executar a solução em **dois processos independentes** que compartilham a mesma camada de negócio e o mesmo banco PostgreSQL.

## Alternativas consideradas

### 1. Processo único
- **Prós:** menos entrypoints.
- **Contras:** maior acoplamento, lifecycle mais frágil, mistura de responsabilidades.

### 2. Separação em serviços totalmente independentes com APIs internas
- **Prós:** maior isolamento.
- **Contras:** complexidade excessiva para a POC.

## Consequências

### Positivas
- separação clara de responsabilidades;
- falha de um processo não implica falha lógica do outro;
- facilita desenvolvimento e depuração.

### Negativas
- exige cuidado com concorrência e consistência;
- aumenta necessidade de observabilidade e disciplina de persistência.

## Impacto arquitetural

A lógica de domínio deve permanecer desacoplada da UI e do canal, com persistência centralizada no PostgreSQL.
