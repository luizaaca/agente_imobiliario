# Matriz de Rastreabilidade

**Objetivo:** relacionar requisitos, cenários, componentes, testes e evidências esperadas para facilitar revisão de cobertura e preparação da demo.

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
| RT-04 | Follow-up automático | Follow-up automático | `FollowUpService`, `followup_runner`, scheduler | `test_followup_service.py`, `test_followup_manual.py`, E2E | follow-up contextual registrado, pelo ciclo ou pelo botão do dashboard |
| RT-05 | Agendamento | Compra residencial / Investimento | `SchedulingService`, `agendar_reuniao` | testes unitários + integração | agendamento persistido e visível |
| RT-06 | Resumo para corretor | Todos | `SummaryService`, `gerar_resumo_corretor` | testes de contrato + revisão manual | resumo com score, objeções e próximos passos |
| RT-07 | Persistência de dados | Todos | PostgreSQL, SQLAlchemy, Alembic | testes de integração | leads, mensagens e agendamentos no banco |
| RT-08 | Dashboard operacional | Todos | `app.py`, `ui/dashboard.py`, `ui/estilo.py` | validação manual + integração | KPIs, distribuição da carteira e tabela ordenável |
| RT-08b | Operação sobre o lead | Todos | `ui/leads.py`, `LeadService` | `test_lead_crud.py` + validação manual | ficha editável, vínculo de canal, follow-up manual, conversa e exclusão |
| RT-09 | Controle de custos LLM | Todos | `LLMUsageService`, tabela `llm_usage` | `test_llm_usage_service.py` + integração | consumo, latência e erro por chamada; limites aplicados |
| RT-10 | Autenticação da UI | Todos | `app.py`, `ui/papeis.py`, `streamlit-authenticator` | `test_papeis.py` + validação manual | acesso protegido a toda a UI; menu conforme o papel |

---

## 3. Uso recomendado

Esta matriz deve ser usada para:
- revisar cobertura antes da demo;
- organizar backlog técnico;
- justificar aderência ao edital;
- conectar documentação, implementação e testes.
