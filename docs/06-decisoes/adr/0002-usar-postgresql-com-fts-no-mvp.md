# ADR 0002 — Usar PostgreSQL com Full-Text Search no MVP

- **Status:** Aceito; quem monta a consulta é definido pelo [ADR 0007](./0007-agente-de-busca-dedicado.md)
- **Data:** 2026-09-16

## Contexto

A solução precisa consultar um catálogo de imóveis com volume suficiente para demonstração, combinando:
- filtros estruturados;
- ranking textual;
- persistência transacional de leads, mensagens e agendamentos.

A POC precisa equilibrar qualidade de busca, simplicidade operacional e velocidade de entrega.

## Decisão

Adotar **PostgreSQL** como banco principal e usar **Full-Text Search (FTS)** como mecanismo inicial de ranking textual para imóveis.

## Alternativas consideradas

### 1. SQLite
- **Prós:** simplicidade local.
- **Contras:** pior aderência a concorrência multiprocesso, menos robustez para evolução e busca textual mais limitada.

### 2. PostgreSQL + pgvector desde o início
- **Prós:** busca semântica mais sofisticada.
- **Contras:** maior complexidade para a POC, custo adicional de embeddings e pipeline de indexação.

### 3. Motor externo de busca
- **Prós:** recursos avançados.
- **Contras:** complexidade e custo desnecessários para o MVP.

## Consequências

### Positivas
- unifica persistência operacional e catálogo;
- suporta concorrência entre Streamlit e bot;
- permite filtros SQL e ranking textual sem infraestrutura extra;
- facilita evolução futura para `pgvector`.

### Negativas
- FTS não entrega busca semântica profunda como embeddings;
- qualidade depende da riqueza textual do catálogo sintético carregado na base.

## Impacto arquitetural

O catálogo combina filtros estruturados e ranking textual (`search_vector` com índice GIN, `websearch_to_tsquery`, `ts_rank`). Quem escreve essa consulta é o agente de busca do ADR 0007; a busca estruturada do `CatalogService`, com filtros primeiro e ranking depois, é o caminho de degradação quando o provider falha.
