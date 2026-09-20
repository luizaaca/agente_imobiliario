# Agente SDR Imobiliário com IA

POC de um **agente conversacional de pré-venda imobiliária** para o POSTECH/FIAP — Tech Challenge (Fase 5).

O agente atende o lead em linguagem natural, qualifica pela conversa, busca imóveis no catálogo, registra visitas e entrega ao corretor um resumo do que foi conversado.

> **Status:** implementação funcional, rodando ponta a ponta no Streamlit contra PostgreSQL e um provider OpenAI-compatible. 157 testes automatizados. O canal Telegram está implementado mas **nunca foi exercitado com um bot real** — ver [Limitações](#limitações-conhecidas).

---

## O que funciona hoje

| Capacidade | Estado |
|---|---|
| Chat com o agente, com memória da conversa | funcionando |
| Qualificação progressiva pela conversa (sem formulário) | funcionando |
| Busca no catálogo: filtros estruturados + Full-Text Search com ranking | funcionando, 300 imóveis |
| Busca que se afrouxa sozinha quando não há resultado exato | funcionando |
| Score do lead em 5 dimensões e avanço no funil | funcionando |
| Perfil narrativo incremental | funcionando |
| Agendamento de visita/reunião, com vínculo ao imóvel | funcionando |
| Resumo executivo para o corretor | funcionando |
| Follow-up automático com 4 réguas e limite de tentativas | funcionando; envio ativo só no Telegram |
| Dashboard: KPIs, filtros, conversa do lead, exclusão, custo de LLM | funcionando |
| Budgets de token (conversa, dia, mês) e custo estimado | funcionando |
| Canal Telegram | implementado, não exercitado |

### O diferencial

O **`perfil_narrativo`** é o artefato central: um texto incremental mantido ao longo da conversa com preferências, objeções, contexto de vida e — o mais valioso — as **rejeições** ("descartou o de Moema por causa do condomínio de R$ 1.800"). É ele que o corretor lê antes de ligar.

---

## Como executar

### Pré-requisitos
- Python 3.11+ (desenvolvido em 3.13)
- Docker e Docker Compose, ou um PostgreSQL 16 acessível
- Uma chave de um provider OpenAI-compatible (OpenAI, Azure AI Foundry, Groq, Gemini, Ollama local)

### Opção 1 — Docker Compose

```bash
cp .env.example .env    # preencha as chaves de LLM
docker compose up --build
```

O serviço `migrate` aplica as migrations e carrega o catálogo antes de subir a aplicação. O Streamlit fica em `http://localhost:8501`.

### Opção 2 — Local

Suba só o banco pelo Compose e rode a aplicação na sua máquina:

```bash
docker compose up -d postgres
```

```bash
python -m venv .venv && .venv/Scripts/activate
```

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Preencha no `.env` pelo menos `OPENAI_API_KEY`, `LLM_MODEL` e `AUTH_COOKIE_KEY`. Depois:

```bash
alembic upgrade head
```

```bash
python -m scripts.seed_imoveis
```

```bash
streamlit run app.py
```

> **Use `127.0.0.1`, não `localhost`, na `DATABASE_URL`.** Em Windows `localhost` resolve para `::1` primeiro e a conexão fica pendurada até o timeout, porque o container só escuta em IPv4.

### Login

As credenciais ficam em `config/credentials.yaml`, com hash bcrypt. Para criar ou trocar uma senha:

```bash
python -m scripts.generate_password_hash
```

### Telegram (opcional)

```bash
python run_telegram.py
```

Precisa de `TELEGRAM_BOT_TOKEN` no `.env`, obtido com o @BotFather. Este caminho **não foi validado** — ver Limitações.

---

## Variáveis de ambiente

| Variável | Para quê |
|---|---|
| `DATABASE_URL` | PostgreSQL. `postgresql://` é normalizado para `postgresql+psycopg://` |
| `LLM_PROVIDER` | `openai`, `groq`, `gemini`, `ollama` ou `custom` |
| `LLM_MODEL` | nome do modelo/deployment |
| `OPENAI_API_KEY` | chave do provider (dispensável só no `ollama`) |
| `OPENAI_BASE_URL` | endpoint, quando não for a OpenAI. Vence o padrão do provider |
| `AUTH_COOKIE_KEY` | assinatura do cookie de sessão do Streamlit |
| `TELEGRAM_BOT_TOKEN` | só para o canal Telegram |
| `LLM_DAILY_TOKEN_BUDGET`, `LLM_MONTHLY_TOKEN_BUDGET` | tetos de consumo |
| `LLM_MAX_TOKENS_PER_CONVERSATION`, `LLM_MAX_TURNS_PER_CONVERSATION` | quando fazer handover ao corretor |

O exemplo completo está em `.env.example`.

---

## Arquitetura

Dois processos independentes sobre a mesma camada de domínio e o mesmo PostgreSQL:

```
app.py (Streamlit)              run_telegram.py
  ├─ chat simulador               ├─ bot (long polling)
  └─ dashboard do corretor        └─ scheduler de follow-up (APScheduler)
            │                               │
            └──────────┬────────────────────┘
                       │
        src/agent/    agente PydanticAI + 5 tools
        src/services/ regras de domínio
        src/db/       SQLAlchemy + Alembic
                       │
                  PostgreSQL 16
```

O agente nunca toca no banco: ele chama tools, que chamam services. O canal não tem regra de negócio.

### Decisões que valem explicar

**O modelo é resolvido por event loop.** Cada mensagem do Streamlit roda em um `asyncio.run` próprio, que fecha o loop ao terminar. Um cliente HTTP em cache global morria junto com o primeiro loop e derrubava a segunda mensagem com `Event loop is closed`. O `build_model()` mantém um modelo por loop, em `WeakKeyDictionary`.

**A busca textual é coluna gerada, não trigger.** `imoveis.search_vector` é `GENERATED ALWAYS AS (to_tsvector(...)) STORED` com índice GIN: o PostgreSQL mantém o vetor sozinho, sem código de aplicação que possa esquecer de atualizar. A consulta usa `websearch_to_tsquery` com OU entre os termos e ordena por `ts_rank`.

**Quem afrouxa a busca é a tool, não o modelo.** Quando nada casa com os filtros exatos, `search_relaxando` afrouxa um critério por vez e devolve em português o que mudou. Sem isso o modelo afirmava ter ampliado a busca sem ter ampliado.

**O contexto do lead lista só o que se sabe.** Mandar todo campo com "não informado" ao lado entregava ao modelo um formulário em branco — e ele conduzia a conversa preenchendo campos, um a um.

**Excluir um lead preserva o consumo de LLM.** As linhas de `llm_usage` só perdem o vínculo (`lead_id` fica nulo). Os tokens foram gastos de fato; apagá-los transformaria a exclusão de leads em uma forma de zerar o controle de orçamento.

---

## Testes

```bash
pytest
```

157 testes, ~10 segundos. Cobrem services, contrato das cinco tools, ciclo de mensagem, budgets, réguas de follow-up, alinhamento dos schemas com o ORM e os **3 cenários obrigatórios** (`tests/test_cenarios.py`): compra residencial, investimento e follow-up automático.

Duas decisões que explicam a suíte:

**PostgreSQL de verdade, em um banco separado (`<banco>_test`), não SQLite.** SQLite ignora o tamanho declarado em `VARCHAR`, então um bug real — a LLM gravando 95 caracteres em uma coluna `VARCHAR(30)` — passaria despercebido. As CHECK constraints e o comportamento transacional também só são fiéis no Postgres.

**O schema da suíte vem de `alembic upgrade head`**, em um banco recriado a cada execução, e não de `create_all()`. É o mesmo caminho que roda em produção: um modelo que ande sem a migration correspondente quebra os testes em vez de passar despercebido.

Lint:

```bash
ruff check .
```

---

## Catálogo de imóveis

300 imóveis sintéticos em `data/imoveis_catalogo.csv`, carregados por `python -m scripts.seed_imoveis`. O seed é idempotente: usa SAVEPOINT por linha, pula duplicados e ressincroniza a sequência do ID ao final.

O processo de geração do catálogo está documentado em `seed/` (`planejamento_geracao_catalogo.md` e `walkthrough.md`).

---

## Limitações conhecidas

São limitações reais da entrega, não do desenho:

- **O canal Telegram nunca foi executado.** O código existe (`src/channels/telegram_bot.py`, `run_telegram.py`, scheduler no `post_init`), mas sem um `TELEGRAM_BOT_TOKEN` real o fluxo Telegram → agente → banco → dashboard não foi verificado ponta a ponta.
- **Sem streaming de resposta.** O chat espera a resposta completa e então a exibe.
- **A UI não tem teste automatizado.** Os fluxos foram verificados manualmente no navegador.
- **O follow-up só envia ativamente pelo Telegram.** Sem canal com push, a mensagem é gerada e registrada com status `generated`, mas não sai. No Streamlit ela aparece no histórico do lead.
- **Custo estimado por tabela fixa** (`LLMUsageService.PRICING`). Modelo fora da tabela cai num preço genérico e registra aviso no log — o número aparece no dashboard, mas é um palpite.
- **O tom do agente degrada em conversas longas.** Ele tende a voltar a listar opções e oferecer menus de próximos passos, porque imita as próprias mensagens anteriores no histórico.
- **Dashboard sem ações de escrita além de excluir.** Não há "agendar ligação" nem "disparar follow-up" pela tela; o follow-up manual roda por `python -m scripts.run_followup_once`.
- **Sem CRM nem calendário externos.** Agendamento é uma linha no banco.
- **Autenticação simples**, por arquivo de credenciais com hash bcrypt, sem perfis nem permissões.
- **Busca vetorial (`pgvector`) não entra na POC** — o FTS do PostgreSQL cobre o caso.

---

## Estrutura do projeto

```text
agente_imobiliario/
├── app.py                  # Streamlit: chat + dashboard
├── run_telegram.py         # bot + scheduler de follow-up
├── run_all.py              # sobe os dois em paralelo
├── src/
│   ├── agent/              # agente, tools, prompts, provider, histórico
│   ├── channels/           # adaptador do Telegram
│   ├── db/                 # modelos SQLAlchemy e sessão
│   ├── scheduler/          # ciclo e agendamento do follow-up
│   ├── schemas/            # contratos Pydantic (espelham o ORM)
│   ├── services/           # regras de domínio
│   └── ui/                 # páginas Streamlit
├── alembic/versions/       # migrations
├── data/                   # catálogo de imóveis (CSV)
├── scripts/                # seed, hash de senha, follow-up manual
├── tests/                  # 157 testes
└── docs/                   # especificação funcional e técnica
```

---

## Documentação

Índice completo em [`docs/00-indice.md`](./docs/00-indice.md).

| Assunto | Documento |
|---|---|
| Plano de implementação e fases | [`01-visao-geral/01-plano-de-implementacao.md`](./docs/01-visao-geral/01-plano-de-implementacao.md) |
| Qualidade e critérios de aceite | [`01-visao-geral/02-qualidade-e-criterios.md`](./docs/01-visao-geral/02-qualidade-e-criterios.md) |
| Visão da solução | [`02-arquitetura/01-visao-geral-da-solucao.md`](./docs/02-arquitetura/01-visao-geral-da-solucao.md) |
| Agente, tools e estratégia de busca | [`02-arquitetura/02-estrategia-de-agente-e-tools.md`](./docs/02-arquitetura/02-estrategia-de-agente-e-tools.md) |
| Cenários de runtime | [`02-arquitetura/03-cenarios-de-runtime.md`](./docs/02-arquitetura/03-cenarios-de-runtime.md) |
| Contratos das tools | [`02-arquitetura/04-contratos-das-tools.md`](./docs/02-arquitetura/04-contratos-das-tools.md) |
| Infraestrutura e deploy | [`03-operacao/01-infraestrutura-e-deploy.md`](./docs/03-operacao/01-infraestrutura-e-deploy.md) |
| Configuração e execução local | [`03-operacao/02-configuracao-e-execucao-local.md`](./docs/03-operacao/02-configuracao-e-execucao-local.md) |
| Autenticação da UI | [`03-operacao/03-autenticacao-da-ui.md`](./docs/03-operacao/03-autenticacao-da-ui.md) |
| Governança de custos de LLM | [`03-operacao/04-governanca-de-custos-llm.md`](./docs/03-operacao/04-governanca-de-custos-llm.md) |
| Modelagem do banco | [`04-dados/01-modelagem-logica-do-banco.md`](./docs/04-dados/01-modelagem-logica-do-banco.md) |
| Identidade de canal e conversa | [`04-dados/02-identidade-de-canal-e-conversa.md`](./docs/04-dados/02-identidade-de-canal-e-conversa.md) |
| Estratégia de testes | [`05-engenharia/01-estrategia-de-testes.md`](./docs/05-engenharia/01-estrategia-de-testes.md) |
| Matriz de rastreabilidade | [`05-engenharia/02-matriz-de-rastreabilidade.md`](./docs/05-engenharia/02-matriz-de-rastreabilidade.md) |
| Decisões arquiteturais (ADRs) | [`06-decisoes/adr/`](./docs/06-decisoes/adr/) |
| Benchmarks de mercado | [`07-referencias/01-benchmarks-de-mercado.md`](./docs/07-referencias/01-benchmarks-de-mercado.md) |

---

## Stack

Python 3.11+ · Streamlit 1.64 · PydanticAI 2.46 · Pydantic 2.13 · SQLAlchemy 2.0 · psycopg 3 · Alembic · PostgreSQL 16 · python-telegram-bot 22 · APScheduler 3.11 · pytest · ruff · Docker Compose

As versões têm teto de major em `requirements.txt` de propósito: sem isso o pip resolvia `pydantic-ai` 0.0.x → 2.x e `streamlit-authenticator` 0.3 → 0.4, cujas APIs são incompatíveis com este código.

---

## Próximos passos

- Validar o canal Telegram ponta a ponta com um bot real.
- Streaming de resposta no chat.
- Testes automatizados da UI.
- Preços reais por modelo na tabela de custo.
- Ações de escrita no dashboard (agendar ligação, disparar follow-up).
- Busca vetorial com `pgvector` como evolução do ranking textual.
