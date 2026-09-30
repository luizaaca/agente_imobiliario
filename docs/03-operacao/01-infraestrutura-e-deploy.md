# Infraestrutura, Containers e Deploy

**Objetivo:** consolidar as decisões e instruções de infraestrutura da POC, cobrindo banco de dados, containers, dependências e opções de deploy.

---

## 1. Visão Geral

A POC roda em **dois processos** (Streamlit + Telegram Bot) que compartilham o mesmo banco PostgreSQL. Para desenvolvimento local, tudo é levantado com `docker-compose up`. Para produção, a mesma estrutura pode ser publicada em qualquer serviço que suporte containers.

---

## 2. PostgreSQL

### Connection string

```env
# Desenvolvimento local (Docker Compose)
DATABASE_URL=postgresql://sdr:sdr_dev_pass@localhost:5432/agente_sdr

# Produção (Neon / Supabase / Railway)
DATABASE_URL=postgresql://user:pass@host.neon.tech/dbname?sslmode=require
```

### Driver

```
psycopg[binary]>=3.1
```

O `psycopg` v3 é o driver PostgreSQL moderno para Python, com suporte a asyncio nativo. A variante `[binary]` inclui a libpq pré-compilada (evita dependência de sistema).

### Configuração do SQLAlchemy

```python
# src/db/session.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")

# Ajuste para compatibilidade com SQLAlchemy (alguns provedores usam postgres:// em vez de postgresql://)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

### Migrations com Alembic

Para gerenciar o schema em produção (sem dropar e recriar tabelas):

```bash
pip install alembic
alembic init alembic
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

Configuração mínima no `alembic/env.py`:
```python
from src.db.models import Base
target_metadata = Base.metadata
```

---

## 3. Docker Compose

### `docker-compose.yml`

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: agente_sdr
      POSTGRES_USER: sdr
      POSTGRES_PASSWORD: ${DB_PASSWORD:-sdr_dev_pass}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sdr -d agente_sdr"]
      interval: 5s
      timeout: 5s
      retries: 5

  app:
    build:
      context: .
      dockerfile: Dockerfile
    command: streamlit run app.py --server.port=8501 --server.address=0.0.0.0
    ports:
      - "8501:8501"
    env_file: .env
    environment:
      DATABASE_URL: postgresql://sdr:${DB_PASSWORD:-sdr_dev_pass}@postgres:5432/agente_sdr
    depends_on:
      postgres:
        condition: service_healthy

  telegram-bot:
    build:
      context: .
      dockerfile: Dockerfile
    command: python run_telegram.py
    env_file: .env
    environment:
      DATABASE_URL: postgresql://sdr:${DB_PASSWORD:-sdr_dev_pass}@postgres:5432/agente_sdr
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  pgdata:
```

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Dependências de sistema para psycopg (se não usar [binary])
# RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Porta padrão do Streamlit
EXPOSE 8501

# Comando padrão (sobrescrito pelo docker-compose)
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### `.env.example`

```env
# === LLM ===
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
LLM_BASE_URL=  # vazio usa o endpoint padrao do LLM_PROVIDER
LLM_MODEL_BUSCA=  # vazio usa o LLM_MODEL

# === Banco de Dados ===
DB_PASSWORD=sdr_dev_pass
DB_PASSWORD_BUSCA=busca_ro_dev_pass  # role somente-leitura do agente de busca
DATABASE_URL=postgresql://sdr:sdr_dev_pass@localhost:5432/agente_sdr

# === Telegram ===
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...

# === Autenticação ===
AUTH_COOKIE_KEY=gerar_uma_chave_aleatoria_aqui

# === LLM Custos ===
LLM_DAILY_TOKEN_BUDGET=1500000
LLM_MONTHLY_TOKEN_BUDGET=10000000
LLM_MAX_TURNS_PER_CONVERSATION=30
LLM_MAX_TOKENS_PER_CONVERSATION=400000

# === Observabilidade (opcional) ===
LOGFIRE_TOKEN=
```

### Comandos de uso

```bash
# Subir tudo (primeira vez)
docker-compose up --build

# Subir em background
docker-compose up -d

# Ver logs
docker-compose logs -f app
docker-compose logs -f telegram-bot

# Parar tudo
docker-compose down

# Resetar banco (cuidado: apaga dados)
docker-compose down -v
```

### Logs

Os quatro serviços — `postgres`, `migrate`, `app` e `telegram-bot` — usam o
driver `json-file` com teto: até três arquivos de 10 MB por container
(`max-size: 10m`, `max-file: 3`), declarado uma vez no bloco
`x-log-limitado` do `docker-compose.yml`. Passado o teto, o arquivo mais
antigo é descartado; sem ele, o Docker guardaria o log sem limite enquanto o
container estivesse de pé.

No `telegram-bot`, dois loggers de terceiros ficam em `WARNING`, ajustados
em `run_telegram.py` logo depois do `logging.basicConfig`:

| Logger | O que escreveria em `INFO` |
|---|---|
| `apscheduler.executors` | "Running job" e "executed successfully" a cada execução do despacho pendente, de 10 em 10 segundos |
| `httpx` | uma linha por `getUpdates` do long polling, com a URL da API do Telegram — que carrega o token do bot |

Falhas de job e os logs da aplicação (`event=...`) continuam em `INFO`.

---

## 4. Desenvolvimento local sem Docker (alternativa)

Para desenvolver sem Docker (execução direta):

```bash
# Terminal 1: PostgreSQL via Docker apenas
docker run -d --name sdr-postgres -p 5432:5432 \
  -e POSTGRES_DB=agente_sdr -e POSTGRES_USER=sdr -e POSTGRES_PASSWORD=sdr_dev_pass \
  postgres:16-alpine

# Terminal 2: Streamlit
streamlit run app.py

# Terminal 3: Telegram Bot
python run_telegram.py

# Ou via supervisor:
python run_all.py
```

---

## 5. Deploy em Produção

### Opção A: Railway (recomendado)

1. Criar projeto no [railway.app](https://railway.app).
2. Adicionar serviço PostgreSQL pelo marketplace.
3. Conectar repositório GitHub.
4. Railway detecta o `Dockerfile` ou `docker-compose.yml` automaticamente.
5. Configurar variáveis de ambiente no painel.
6. Railway gera URLs públicas com HTTPS automático.

**Custo estimado:** ~$5-10/mês (app + bot + banco).

### Opção B: Neon (banco) + Render/Fly.io (app)

1. Criar banco PostgreSQL no [neon.tech](https://neon.tech) (free tier: 512 MB, scale-to-zero).
2. Copiar `DATABASE_URL` fornecida pelo Neon.
3. Publicar o Streamlit como Web Service no Render ou Fly.io.
4. Publicar o Telegram Bot como Background Worker.

**Custo estimado:** $0-7/mês (Neon free + Render free tier ou $7/mês).

### Opção C: VPS simples (DigitalOcean / Hetzner)

1. Criar droplet/VPS barata ($4-6/mês).
2. Instalar Docker + Docker Compose.
3. Clonar repo, configurar `.env`, `docker-compose up -d`.
4. Configurar Caddy ou nginx como reverse proxy com HTTPS automático (Let's Encrypt).

**Custo estimado:** $4-6/mês (tudo incluso).

---

## 6. Estrutura de Diretórios

```text
agente_imobiliario/
├── app.py                        # Streamlit: login, navegação e páginas
├── run_telegram.py               # Bot Telegram (polling) + scheduler de follow-up
├── run_all.py                    # Supervisor: inicia ambos os processos
├── Dockerfile
├── docker-compose.yml            # postgres, migrate, app, telegram-bot (profile)
├── alembic.ini
├── pyproject.toml                # configuração do ruff e do pytest
├── .env.example
├── README.md
├── requirements.txt
├── alembic/
│   ├── env.py
│   └── versions/                 # migrations de schema
├── config/
│   └── credentials.yaml          # usuários e hashes bcrypt da UI
├── data/
│   └── imoveis_catalogo.csv      # catálogo sintético pronto para carga
├── seed/                         # geração do catálogo, fora do runtime da aplicação
├── scripts/
│   ├── seed_imoveis.py           # ingere o catálogo no PostgreSQL
│   ├── generate_password_hash.py
│   └── run_followup_once.py      # dispara um ciclo de follow-up manualmente
├── src/
│   ├── config.py                 # settings e checagem de configuração ausente
│   ├── tempo.py                  # fuso e formatação de data/hora
│   ├── db/
│   │   ├── models.py
│   │   └── session.py
│   ├── schemas/
│   │   ├── lead.py
│   │   ├── imovel.py
│   │   ├── agendamento.py
│   │   ├── mensagem.py
│   │   └── agent.py
│   ├── services/                 # regras de domínio, sem Streamlit nem LLM
│   │   ├── catalog_service.py
│   │   ├── lead_service.py
│   │   ├── scheduling_service.py
│   │   ├── summary_service.py
│   │   ├── followup_service.py
│   │   └── llm_usage_service.py
│   ├── agent/
│   │   ├── sdr_agent.py          # agente conversacional e suas tools
│   │   ├── perfil_agent.py       # consolidador do perfil narrativo
│   │   ├── followup_agent.py     # composição da mensagem de follow-up
│   │   ├── prompts.py
│   │   ├── provider.py           # construção do modelo, OpenAI-compatible
│   │   └── history.py            # reidratação do histórico para o PydanticAI
│   ├── channels/
│   │   └── telegram_bot.py       # adaptador Telegram (handlers + despacho)
│   ├── scheduler/
│   │   ├── followup_scheduler.py # APScheduler com job periódico
│   │   └── followup_runner.py    # o ciclo em si, testável sem scheduler
│   └── ui/
│       ├── dashboard.py          # KPIs, carteira e painel de consumo
│       ├── leads.py              # lista e ficha do lead
│       ├── chat.py               # simulador de chat
│       ├── ajuda.py
│       ├── login.py
│       ├── navegacao.py
│       ├── papeis.py             # visibilidade de menu por papel
│       ├── estilo.py
│       ├── tabela.py
│       └── texto.py
├── tests/                        # suíte plana, por assunto
└── docs/
```

> As tools do agente ficam em `sdr_agent.py`, junto do agente que as expõe:
> são poucas e cada uma delega a um service. Um módulo separado só de tools
> acrescentaria um salto de arquivo sem acrescentar fronteira.

---

## 7. Dependências Sugeridas (`requirements.txt`)

```text
streamlit
streamlit-authenticator
pydantic>=2
pydantic-ai
sqlalchemy
psycopg[binary]>=3.1
alembic
python-dotenv
pyyaml
python-dateutil
phonenumbers
python-telegram-bot>=21
apscheduler>=3.10
pytest
freezegun
ruff
logfire
```

---

## 8. Checklist de implementação

- [x] Instalar `psycopg[binary]` e `alembic` no `requirements.txt`.
- [x] Atualizar `src/db/session.py` para ler `DATABASE_URL` do ambiente.
- [x] Remover referências a SQLite e `PRAGMA WAL` do código.
- [x] Criar `Dockerfile`.
- [x] Criar `docker-compose.yml`.
- [x] Criar `.env.example` com todas as variáveis documentadas.
- [x] Testar `docker-compose up --build` localmente.
  > A imagem constrói, o container sobe, conecta no PostgreSQL da rede do
  > Compose e serve a tela de login. O `.dockerignore` mantém `.venv`,
  > `.git` e os caches fora do contexto de build.
- [x] Configurar Alembic para migrations (opcional mas recomendado).
- [ ] Testar com banco PostgreSQL remoto (Neon ou Supabase free tier).
  > O desenvolvimento roda contra o PostgreSQL do Compose.
