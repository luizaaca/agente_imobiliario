# Matriz de Rastreabilidade

---

## 1. Objetivo

Relacionar requisitos do desafio, cenários de negócio, componentes da solução, testes e evidências esperadas.

---

## 2. Matriz

| ID | Requisito / Objetivo | Cenário | Componentes principais | Validação / Teste | Evidência esperada |
|---|---|---|---|---|---|
| RT-01 | Atendimento conversacional humanizado | Compra residencial / Investimento | `sdr_agent.py`, `prompts.py`, canal Streamlit/Telegram | testes E2E + roteiro manual | resposta contextual e tom consultivo |
| RT-02 | Qualificação de leads | Compra residencial / Investimento | `LeadService`, `registrar_qualificacao`, schemas | testes unitários + integração | lead com intenção, orçamento, região, urgência |
| RT-03 | Recomendação de imóveis | Compra residencial / Investimento | `CatalogService`, `buscar_imoveis` | testes unitários de catálogo | lista coerente de imóveis ou refinamento |
| RT-04 | Follow-up automático | Follow-up automático | `FollowUpService`, scheduler, geração contextual de follow-up | testes de integração + E2E | follow-up contextual registrado |
| RT-05 | Agendamento | Compra residencial / Investimento | `SchedulingService`, `agendar_reuniao` | testes unitários + integração | agendamento persistido e visível |
| RT-06 | Resumo para corretor | Todos | `SummaryService`, `gerar_resumo_corretor` | testes de contrato + revisão manual | resumo com score, objeções e próximos passos |
| RT-07 | Persistência de dados | Todos | PostgreSQL, SQLAlchemy, Alembic | testes de integração | leads, mensagens e agendamentos no banco |
| RT-08 | Dashboard operacional | Todos | `app.py`, `ui/dashboard.py` | validação manual + integração | KPIs, tabela de leads, expanders |
| RT-09 | Controle de custos LLM | Todos | tracking de uso, tabela `LLMUsage` | testes de integração / inspeção | consumo por interação e limites aplicados |
| RT-10 | Autenticação da UI | Todos | Streamlit + autenticação | validação manual | acesso protegido ao dashboard |

---

## 3. Uso recomendado

Esta matriz deve ser usada para:
- revisar cobertura antes da demo;
- organizar backlog técnico;
- justificar aderência ao edital;
- conectar documentação, implementação e testes.
