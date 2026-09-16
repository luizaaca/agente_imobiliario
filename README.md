# Agente SDR Imobiliário com IA

POC de um **agente conversacional de pré-venda imobiliária** para o Hackathon FIAP — Tech Challenge (Fase 5).

O objetivo da solução é automatizar o primeiro atendimento de leads, realizar qualificação progressiva, recomendar imóveis aderentes, executar follow-up contextual, apoiar agendamentos e entregar um resumo útil para o corretor.

---

## Visão geral

O projeto foi desenhado para demonstrar uma POC funcional e evolutiva, com foco em:

- atendimento conversacional humanizado;
- qualificação de leads;
- recomendação de imóveis com filtros estruturados + ranking textual;
- follow-up automático;
- agendamento de reunião/visita;
- dashboard operacional para o corretor;
- rastreamento de uso e custo de LLM.

O diferencial central da solução é o **`perfil_narrativo`**: um artefato textual incremental mantido ao longo da conversa, que concentra preferências, objeções, contexto de vida, rejeições e próximos passos do lead.

---

## Problema que a POC resolve

Imobiliárias frequentemente perdem leads por:
- demora no primeiro atendimento;
- qualificação inconsistente;
- ausência de follow-up contextual;
- handover pobre entre atendimento inicial e corretor.

A proposta do agente SDR é reduzir esse gargalo, operando como uma camada de pré-venda 24/7.

---

## Principais capacidades

- responder leads em linguagem natural com tom consultivo;
- coletar dados essenciais sem transformar a conversa em formulário engessado;
- buscar imóveis aderentes ao perfil do lead;
- registrar histórico, score e status do lead;
- gerar follow-up contextual para leads inativos;
- registrar agendamentos;
- gerar resumo executivo para o corretor;
- exibir operação e pipeline em dashboard Streamlit.

---

## Arquitetura resumida

A solução opera em **dois processos independentes** que compartilham a mesma camada de negócio e o mesmo banco PostgreSQL:

1. **Streamlit**
   - chat simulador
   - dashboard do corretor

2. **Telegram Bot**
   - canal real de mensageria
   - scheduler de follow-up automático

Ambos usam a mesma camada de domínio:
- agente SDR;
- tools tipadas;
- services de negócio;
- PostgreSQL como persistência central.

---

## Stack principal

- **Python 3.11+**
- **Streamlit**
- **PydanticAI**
- **Pydantic v2**
- **PostgreSQL 16**
- **SQLAlchemy**
- **psycopg[binary]**
- **Alembic**
- **python-telegram-bot**
- **APScheduler**
- **pytest**
- **ruff**
- **Docker Compose**

---

## Estrutura documental

### Documento principal
- [`PLANO_DE_IMPLEMENTACAO.md`](./PLANO_DE_IMPLEMENTACAO.md)

### Sub-planos funcionais
- [`SUB_PLANO_AGENTE.md`](./SUB_PLANO_AGENTE.md)
- [`SUB_PLANO_MODELAGEM.md`](./SUB_PLANO_MODELAGEM.md)
- [`SUB_PLANO_INFRA.md`](./SUB_PLANO_INFRA.md)
- [`SUB_PLANO_AUTENTICACAO.md`](./SUB_PLANO_AUTENTICACAO.md)
- [`SUB_PLANO_CUSTOS_LLM.md`](./SUB_PLANO_CUSTOS_LLM.md)
- [`SUB_PLANO_BENCHMARKS.md`](./SUB_PLANO_BENCHMARKS.md)

### Documentação complementar de engenharia
- [`SDD_QUALIDADE_E_CRITERIOS.md`](./SDD_QUALIDADE_E_CRITERIOS.md)
- [`docs/runtime_scenarios.md`](./docs/runtime_scenarios.md)
- [`docs/tool_contracts.md`](./docs/tool_contracts.md)
- [`docs/test_strategy.md`](./docs/test_strategy.md)
- [`docs/traceability_matrix.md`](./docs/traceability_matrix.md)
- [`docs/adr/`](./docs/adr/)

---

## Estrutura de diretórios planejada

```text
agente_imobiliario/
├── app.py
├── run_telegram.py
├── run_all.py
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── requirements.txt
├── PLANO_DE_IMPLEMENTACAO.md
├── SDD_QUALIDADE_E_CRITERIOS.md
├── docs/
│   ├── adr/
│   ├── runtime_scenarios.md
│   ├── tool_contracts.md
│   ├── test_strategy.md
│   └── traceability_matrix.md
├── src/
│   ├── agent/
│   ├── channels/
│   ├── db/
│   ├── scheduler/
│   ├── schemas/
│   ├── services/
│   └── ui/
├── scripts/
└── tests/
```

---

## Fluxos principais da POC

### 1. Compra residencial
Lead informa interesse em comprar imóvel residencial, o agente qualifica, busca imóveis e propõe agendamento.

### 2. Investimento
Lead informa intenção de investir, o agente muda a estratégia de qualificação e direciona para oportunidades aderentes.

### 3. Follow-up automático
Lead interrompe a conversa antes do agendamento, e o sistema retoma o contato com contexto.

---

## Qualidade e critérios técnicos

Os requisitos não funcionais e critérios de aceite estão em:
- [`SDD_QUALIDADE_E_CRITERIOS.md`](./SDD_QUALIDADE_E_CRITERIOS.md)

Lá estão definidos, entre outros:
- metas de performance da POC;
- confiabilidade mínima;
- segurança e privacidade mínimas;
- observabilidade;
- critérios de pronto.

---

## Decisões arquiteturais registradas

As principais decisões do projeto foram registradas como ADRs em [`docs/adr/`](./docs/adr/), incluindo:

- uso de PydanticAI;
- PostgreSQL + FTS no MVP;
- Telegram como canal real da POC;
- dois processos independentes;
- `perfil_narrativo` como artefato central;
- provider OpenAI-compatible configurável.

---

## Estratégia de testes

A estratégia de testes está documentada em:
- [`docs/test_strategy.md`](./docs/test_strategy.md)

Ela cobre:
- testes unitários;
- testes de contrato;
- testes de integração;
- validação dos 3 cenários obrigatórios.

---

## Como executar

### Pré-requisitos
- Python 3.11+
- Docker e Docker Compose
- PostgreSQL via Docker Compose ou instância externa
- credenciais configuradas em `.env`

### Variáveis de ambiente esperadas
Consulte:
- [`SUB_PLANO_INFRA.md`](./SUB_PLANO_INFRA.md)
- `.env.example` (quando criado no projeto)

Variáveis principais esperadas:
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` (opcional)
- `LLM_MODEL`
- `TELEGRAM_BOT_TOKEN`
- `AUTH_COOKIE_KEY`

### Execução local planejada

#### Opção 1 — Docker Compose
```bash
docker-compose up --build
```

#### Opção 2 — Processos separados
```bash
streamlit run app.py
python run_telegram.py
```

#### Opção 3 — Supervisor
```bash
python run_all.py
```

> Observação: este repositório está em fase de especificação/estruturação. Alguns arquivos de execução ainda serão implementados conforme o plano.

---

## Roadmap resumido

1. Fundamentos de dados, infraestrutura e catálogo
2. Agente SDR e estado conversacional
3. Qualificação, score e perfil narrativo
4. Follow-up automático
5. Canal Telegram
6. Interface Streamlit e dashboard
7. Observabilidade, testes e refino
8. Documentação e entrega

Detalhamento completo em [`PLANO_DE_IMPLEMENTACAO.md`](./PLANO_DE_IMPLEMENTACAO.md).

---

## Limitações assumidas da POC

- sem CRM externo real;
- sem calendário externo real;
- autenticação simples;
- Telegram no lugar de WhatsApp Business API;
- busca vetorial como evolução futura, não requisito do MVP.

---

## Próximos passos sugeridos

- implementar a estrutura base do projeto;
- materializar os schemas e contratos em código;
- criar a camada de banco e migrations;
- implementar services e tools;
- validar os 3 cenários obrigatórios ponta a ponta.

---

## Status atual

Atualmente o repositório contém a **especificação funcional e técnica** da POC, incluindo:
- plano principal;
- sub-planos especializados;
- documentação complementar de engenharia;
- ADRs.

A implementação do código seguirá essa base documental.
