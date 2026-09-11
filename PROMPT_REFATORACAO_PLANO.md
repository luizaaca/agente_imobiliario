# Prompt de Refatoração: Enxugar o PLANO_DE_IMPLEMENTACAO.md

**Objetivo:** Extrair seções detalhadas do `PLANO_DE_IMPLEMENTACAO.md` para sub-planos independentes,
transformando o plano principal em um **roteiro executivo enxuto** (~200-250 linhas) que referencia
os documentos de detalhe.

**Princípio:** O plano principal deve responder "O QUE fazemos e POR QUÊ". Os sub-planos respondem "COMO, exatamente".

---

## Seções a extrair

### 1. §8 "Estratégia de Agente e Tool Calling" → `SUB_PLANO_AGENTE.md`
**Linhas atuais:** ~221-267 (~47 linhas)
**Motivo:** Contém detalhes de implementação do agente (estratégia conversacional passo a passo, perfil narrativo incremental, tabela de tools, boas práticas de tool calling) que são referência de implementação, não visão executiva.
**O que fica no plano principal:** Parágrafo de 3-4 linhas descrevendo o papel do agente + link para o sub-plano.
**Sugestão de texto resumido:**
```markdown
## 8. Estratégia de Agente e Tool Calling

O agente SDR opera como pré-vendedor consultivo: qualifica progressivamente via conversa natural,
mantém um `perfil_narrativo` incremental (artefato principal do SDR), busca imóveis quando há contexto
suficiente e propõe agendamento no momento adequado. Expõe 6 tools tipadas ao modelo (buscar, qualificar,
atualizar perfil, agendar, gerar resumo, gerar follow-up).

> Detalhamento completo: [SUB_PLANO_AGENTE.md](SUB_PLANO_AGENTE.md)
```

---

### 2. §9 "Modelagem de Dados da POC" → `SUB_PLANO_MODELAGEM.md`
**Linhas atuais:** ~270-382 (~113 linhas) — a maior seção do documento
**Motivo:** Contém schemas completos de todas as entidades (Lead com 20+ campos, Mensagem, Agendamento, Imóvel), enums, exemplo extenso do perfil_narrativo (~30 linhas de texto simulado) e tabela comparativa perfil_narrativo vs resumo. Tudo isso é referência de implementação.
**O que fica no plano principal:** Lista das entidades com 1 linha cada + menção ao `perfil_narrativo` como diferencial + link.
**Sugestão de texto resumido:**
```markdown
## 9. Modelagem de Dados da POC

Entidades principais: **Lead** (qualificação + `perfil_narrativo` evolutivo), **Mensagem** (histórico),
**Agendamento** (visitas/reuniões), **Imóvel** (catálogo) e **LLMUsage** (tracking de consumo).
O `perfil_narrativo` é um campo TEXT mantido pela LLM que acumula contexto rico do lead — o produto
principal do SDR.

> Detalhamento completo dos schemas, enums e exemplo ilustrativo: [SUB_PLANO_MODELAGEM.md](SUB_PLANO_MODELAGEM.md)
```

---

### 3. §10 "Estratégia de Busca de Imóveis" → incorporar em `SUB_PLANO_AGENTE.md`
**Linhas atuais:** ~385-405 (~21 linhas)
**Motivo:** É curta mas técnica (filtros estruturados + ranking textual). Faz mais sentido como subseção do sub-plano do agente, já que é uma das tools dele.
**O que fica no plano principal:** 2 linhas mencionando a abordagem de busca em camadas.
**Sugestão de texto resumido:**
```markdown
## 10. Estratégia de Busca de Imóveis

Busca em duas camadas: filtros estruturados por metadados + ranking textual com RapidFuzz.
Embeddings/busca vetorial como evolução opcional.

> Detalhamento: seção "Busca de Imóveis" em [SUB_PLANO_AGENTE.md](SUB_PLANO_AGENTE.md)
```

---

### 4. §11 "Estrutura de Diretórios" + §12 "Dependências" → incorporar em `SUB_PLANO_INFRA.md`
**Linhas atuais:** ~409-504 (~96 linhas)
**Motivo:** A árvore de diretórios completa e a lista de dependências são referência operacional que já está parcialmente no SUB_PLANO_INFRA.md. Mover integralmente para lá e manter no plano apenas uma menção.
**O que fica no plano principal:** 2-3 linhas dizendo que a estrutura e deps estão documentadas no sub-plano de infra.
**Sugestão de texto resumido:**
```markdown
## 11. Estrutura de Diretórios e Dependências

Estrutura de pastas, `requirements.txt`, `Dockerfile`, `docker-compose.yml` e todas as variáveis
de ambiente estão documentados no sub-plano de infraestrutura.

> Detalhamento: [SUB_PLANO_INFRA.md](SUB_PLANO_INFRA.md)
```

---

### 5. §16 "Referências de Mercado (Benchmarks)" → `SUB_PLANO_BENCHMARKS.md`
**Linhas atuais:** ~642-676 (~35 linhas)
**Motivo:** Descritivos de Lais.ai, Maya e Squad com dados de fundraising, fundadores e features. É contexto de pesquisa, não roteiro executivo.
**O que fica no plano principal:** 3-4 linhas dizendo que o projeto foi informado por benchmarks de mercado + tabela de padrões adotados (6 linhas, que é a parte acionável) + link.
**Sugestão de texto resumido:**
```markdown
## 16. Referências de Mercado

O design do projeto foi informado pela análise de 3 ferramentas comerciais de SDR imobiliário com IA
(Lais.ai, Maya/Plaza, Squad/Inner AI). Os padrões convergentes incorporados: qualificação progressiva,
perfil narrativo rico, rejeições como dado, dossier como produto, follow-up contextual e scoring transparente.

> Detalhamento dos benchmarks: [SUB_PLANO_BENCHMARKS.md](SUB_PLANO_BENCHMARKS.md)
```

---

## Seções que DEVEM permanecer no plano principal (já enxutas)

| Seção | Motivo para manter | Linhas atuais |
|---|---|---|
| §1 O que é um SDR | Contexto essencial | ~11 |
| §2 Visão Geral | Síntese do projeto | ~7 |
| §3 Objetivos da POC | Define critérios de sucesso | ~19 |
| §4 Requisitos e Cobertura | Tabela de aderência ao edital | ~11 |
| §5 Cenários Obrigatórios | Referência dos 3 cenários | ~13 |
| §6 Stack Tecnológica | Decisões técnicas centrais | ~53 |
| §7 Arquitetura (diagrama) | Visão visual do sistema | ~90 |
| §13 Fases de Execução | Checklist do roadmap | ~97 |
| §14 Riscos e Mitigações | Gestão de risco | ~18 |
| §15 Próximos Passos | Evolução pós-hackathon | ~9 |
| §17 Sub-planos (tabela) | Índice de documentos | ~10 |
| §18 Conclusão | Fechamento | ~9 |

---

## Resumo do impacto estimado

| Métrica | Antes | Depois (estimado) |
|---|---|---|
| **Linhas do plano principal** | ~703 | ~350-400 |
| **Seções detalhadas movidas** | 0 | 5 (→ 4 sub-planos) |
| **Sub-planos totais** | 3 | 7 (3 existentes + 3 novos + 1 fusão) |

---

## Sub-planos resultantes (finais)

| Documento | Conteúdo | Status |
|---|---|---|
| `SUB_PLANO_INFRA.md` | Docker, PostgreSQL, diretórios, deps, env vars, deploy | ✅ Existe (expandir com §11 e §12) |
| `SUB_PLANO_AUTENTICACAO.md` | Streamlit-authenticator, credenciais, proteção | ✅ Existe |
| `SUB_PLANO_CUSTOS_LLM.md` | Tabela llm_usage, limites, tracking | ✅ Existe |
| `SUB_PLANO_AGENTE.md` | Estratégia de agente, tools, perfil narrativo, busca de imóveis | 🆕 Criar (a partir de §8 e §10) |
| `SUB_PLANO_MODELAGEM.md` | Schemas, entidades, enums, exemplo perfil_narrativo | 🆕 Criar (a partir de §9) |
| `SUB_PLANO_BENCHMARKS.md` | Lais, Maya, Squad: análise e padrões convergentes | 🆕 Criar (a partir de §16) |

---

## Instruções de execução

1. **Criar** `SUB_PLANO_AGENTE.md` com o conteúdo integral das seções §8 e §10 atuais.
2. **Criar** `SUB_PLANO_MODELAGEM.md` com o conteúdo integral da seção §9 atual.
3. **Criar** `SUB_PLANO_BENCHMARKS.md` com o conteúdo integral da seção §16 atual.
4. **Mover** conteúdo de §11 (árvore de diretórios) e §12 (dependências + env vars) para `SUB_PLANO_INFRA.md` existente.
5. **Substituir** cada seção extraída do `PLANO_DE_IMPLEMENTACAO.md` pelo texto resumido + link (conforme sugestões acima).
6. **Fundir** §11 e §12 em uma única seção no plano principal.
7. **Atualizar** a tabela §17 (Documentos Complementares) com os 3 novos sub-planos.
8. **Renumerar** seções se necessário (fusão de §11+§12 pode reduzir a contagem).
9. **Verificar** que nenhum conteúdo foi perdido — tudo que saiu do plano deve estar em algum sub-plano.

---

**ATENÇÃO:** Este arquivo é apenas um prompt/roteiro de alteração. Não execute as mudanças até aprovação.
