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
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=  # deixar vazio para OpenAI padrão

# === Banco de Dados ===
DB_PASSWORD=sdr_dev_pass
DATABASE_URL=postgresql://sdr:sdr_dev_pass@localhost:5432/agente_sdr

# === Telegram ===
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...

# === Autenticação ===
AUTH_COOKIE_KEY=gerar_uma_chave_aleatoria_aqui

# === LLM Custos ===
LLM_DAILY_TOKEN_BUDGET=100000
LLM_MONTHLY_TOKEN_BUDGET=3000000
LLM_MAX_TURNS_PER_CONVERSATION=30
LLM_MAX_TOKENS_PER_CONVERSATION=50000

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

## 6. Estrutura de Diretórios Completa

```text
agente_imobiliario/
├── app.py                        # Streamlit (chat simulador + dashboard)
├── run_telegram.py               # Bot Telegram (polling + scheduler)
├── run_all.py                    # Supervisor: inicia ambos os processos
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── requirements.txt
├── docs/
│   └── 01-visao-geral/
│       └── 01-plano-de-implementacao.md
├── data/
│   └── imoveis_catalogo.csv      # Artefato interno com catálogo sintético pronto para carga
├── src/
│   ├── config.py
│   ├── schemas/
│   │   ├── lead.py
│   │   ├── imovel.py
│   │   ├── agendamento.py
│   │   └── agent.py
│   ├── db/
│   │   ├── models.py
│   │   ├── repository.py
│   │   └── session.py
│   ├── services/
│   │   ├── catalog_service.py
│   │   ├── lead_service.py
│   │   ├── scheduling_service.py
│   │   ├── summary_service.py
│   │   └── followup_service.py
│   ├── agent/
│   │   ├── sdr_agent.py
│   │   ├── prompts.py
│   │   └── tools.py
│   ├── channels/
│   │   └── telegram_bot.py       # Adaptador Telegram (handlers + despacho para o agente)
│   ├── scheduler/
│   │   └── followup_scheduler.py # APScheduler com job de follow-up periódico
│   └── ui/
│       ├── chat.py
│       └── dashboard.py
├── config/
│   └── credentials.yaml          # Credenciais bcrypt (autenticação Streamlit)
├── scripts/
│   ├── generate_password_hash.py # Utilitário para gerar hashes de senha
│   └── seed_imoveis.py           # Script para ingerir o catálogo sintético no PostgreSQL
├── alembic/                      # Migrations de schema PostgreSQL
│   └── versions/
└── tests/
    ├── test_catalog_service.py
    ├── test_scoring.py
    ├── test_followup.py
    └── test_agent_tools.py
```

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
  > A imagem constrói e o container sobe, conecta no PostgreSQL da rede do
  > Compose e serve a tela de login. Exigiu criar o `.dockerignore`: sem ele
  > o contexto levava `.venv` e `.git`, e o build nem começava porque o
  > Docker não consegue ler o `.pytest_cache` deste repositório.
- [x] Configurar Alembic para migrations (opcional mas recomendado).
- [ ] Testar com banco PostgreSQL remoto (Neon ou Supabase free tier).
  > Não feito. O desenvolvimento rodou contra o PostgreSQL do Compose.
