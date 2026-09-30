# Infraestrutura, Containers e Deploy

**Objetivo:** consolidar as decisões e instruções de infraestrutura da POC, cobrindo banco de dados, containers, dependências e opções de deploy.

---

## 1. Visão Geral

A POC roda em **dois processos** — o Streamlit e o bot do Telegram, que leva
junto o scheduler de follow-up — sobre o mesmo PostgreSQL. Localmente, tudo
sobe pelo Docker Compose; o bot fica atrás do profile `telegram`, porque sem
`TELEGRAM_BOT_TOKEN` ele só subiria para falhar. Para produção, a mesma
estrutura pode ser publicada em qualquer serviço que rode containers.

---

## 2. PostgreSQL

### Connection string

```env
# Desenvolvimento, com a aplicação rodando fora do Docker
DATABASE_URL=postgresql+psycopg://sdr:sdr_dev_pass@127.0.0.1:5432/agente_sdr

# Dentro do Compose, montada no próprio docker-compose.yml
DATABASE_URL=postgresql+psycopg://sdr:${DB_PASSWORD}@postgres:5432/agente_sdr

# Produção (Neon / Supabase / Railway)
DATABASE_URL=postgresql+psycopg://user:pass@host.neon.tech/dbname?sslmode=require
```

`127.0.0.1`, e não `localhost`: em máquinas onde o `localhost` resolve
primeiro para `::1`, o publish IPv6 do container não roteia e a conexão trava.

### Driver

O driver é o `psycopg` 3 (`psycopg[binary]`, que já traz a libpq
pré-compilada). URLs que chegam como `postgres://` ou `postgresql://` são
normalizadas para `postgresql+psycopg://` em `src/config.py`
(`Settings.database_url_safe`); sem o prefixo explícito, o SQLAlchemy
procuraria o `psycopg2`, que não é instalado.

### Engines

`src/db/session.py` cria duas engines sobre o mesmo banco:

| Engine | Credencial | Uso |
|---|---|---|
| `engine` | a da `DATABASE_URL` | toda a aplicação, via `get_db()` |
| `engine_busca` | role `busca_ro`, senha em `DB_PASSWORD_BUSCA` | só o SQL escrito pelo agente de busca, via `conexao_de_busca()` |

As duas usam `pool_pre_ping` e `connect_timeout` de 10 s. A conexão de busca
abre toda transação como `READ ONLY`, com `statement_timeout` de 3 s, e
termina sempre em rollback. A role `busca_ro` só tem `SELECT` em `imoveis` —
é ela, e não o código, a fronteira que impede o SQL gerado por LLM de
alcançar leads, telefones e conversas.

### Migrations

O schema vem de uma migration única, `alembic/versions/29abbb20023f_schema_inicial.py`,
que cria as tabelas, os índices (inclusive o de texto completo e o que
garante um compromisso ativo por lead) e a role `busca_ro`. No Compose, quem
a aplica é o serviço `migrate`, antes de `app` e `telegram-bot` subirem. Fora
dele:

```bash
alembic upgrade head
python -m scripts.seed_imoveis
```

A suíte de testes monta o banco pelo mesmo caminho: recria um banco de teste
por sessão e aplica `alembic upgrade head`, e não `create_all`, para que a
migration seja exercitada a cada execução.

---

## 3. Docker Compose

### `docker-compose.yml`

Quatro serviços:

| Serviço | Papel | Sobe quando |
|---|---|---|
| `postgres` | banco, com volume `pgdata` | sempre |
| `migrate` | aplica a migration e carrega o catálogo, e termina | depois do `postgres` saudável |
| `app` | Streamlit na porta 8501 | depois do `migrate` terminar com sucesso |
| `telegram-bot` | bot (long polling) e scheduler de follow-up | só com `--profile telegram`, depois do `migrate` |

As variáveis entram por interpolação: o Compose lê o `.env` ao lado do
arquivo e preenche os `${VAR}`, com defaults que deixam um clone recém-feito
subir sem `.env`. Não há `env_file` — nada do `.env` é injetado inteiro no
container, e o arquivo documenta exatamente o que cada serviço consome. Uma
variável do shell vence a do `.env`.

```yaml
x-ambiente-da-aplicacao: &ambiente-da-aplicacao
  DATABASE_URL: postgresql+psycopg://sdr:${DB_PASSWORD:-sdr_dev_pass}@postgres:5432/agente_sdr
  # Role somente-leitura que executa o SQL do agente de busca. Precisa bater
  # com a senha que a migration usou ao criar a role, no servico `migrate`.
  DB_PASSWORD_BUSCA: ${DB_PASSWORD_BUSCA:-busca_ro_dev_pass}
  LLM_PROVIDER: ${LLM_PROVIDER:-openai}
  # Sem default: o nome do modelo e especifico do deployment de quem roda.
  # Vazia, a aplicacao lista LLM_MODEL entre as variaveis ausentes.
  LLM_MODEL: ${LLM_MODEL:-}
  # Vazio usa o LLM_MODEL. Ver .env.example.
  LLM_MODEL_BUSCA: ${LLM_MODEL_BUSCA:-}
  LLM_API_KEY: ${LLM_API_KEY:-}
  LLM_BASE_URL: ${LLM_BASE_URL:-}
  # Sem default: um valor fixo aqui seria publico e daria para forjar cookie
  # de admin. Vazia, a aplicacao sorteia uma chave por processo e avisa.
  AUTH_COOKIE_KEY: ${AUTH_COOKIE_KEY:-}
  LLM_DAILY_TOKEN_BUDGET: ${LLM_DAILY_TOKEN_BUDGET:-1500000}
  LLM_MONTHLY_TOKEN_BUDGET: ${LLM_MONTHLY_TOKEN_BUDGET:-10000000}
  LLM_MAX_TURNS_PER_CONVERSATION: ${LLM_MAX_TURNS_PER_CONVERSATION:-30}
  LLM_MAX_TOKENS_PER_CONVERSATION: ${LLM_MAX_TOKENS_PER_CONVERSATION:-400000}
  # Intervalo do ciclo automatico de follow-up, lido pelo scheduler do
  # `telegram-bot`. Baixar para 1 serve para ver o ciclo rodar numa demo.
  FOLLOWUP_INTERVAL_MINUTES: ${FOLLOWUP_INTERVAL_MINUTES:-30}
  LOGFIRE_TOKEN: ${LOGFIRE_TOKEN:-}

# Teto do log de cada container. Sem isso o Docker guarda o log sem limite
# enquanto o container estiver de pe: o `telegram-bot` escreve a cada poucos
# segundos e cresceria ate encher o disco. Com o teto, ficam no maximo tres
# arquivos de 10 MB por container, e o mais antigo e descartado.
x-log-limitado: &log-limitado
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"

services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    logging: *log-limitado
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

  # Job de inicializacao: aplica as migrations e carrega o catalogo.
  # `app` e `telegram-bot` so sobem depois que este servico termina com sucesso.
  # Nao precisa de chave de LLM: so fala com o banco.
  migrate:
    build:
      context: .
      dockerfile: Dockerfile
    command: sh -c "alembic upgrade head && python -m scripts.seed_imoveis"
    logging: *log-limitado
    environment:
      DATABASE_URL: postgresql+psycopg://sdr:${DB_PASSWORD:-sdr_dev_pass}@postgres:5432/agente_sdr
      # A migration cria a role `busca_ro` com esta senha. Se ela divergir da
      # que `app` usa, a busca sobe e so falha na primeira consulta.
      DB_PASSWORD_BUSCA: ${DB_PASSWORD_BUSCA:-busca_ro_dev_pass}
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

  app:
    build:
      context: .
      dockerfile: Dockerfile
    command: streamlit run app.py --server.port=8501 --server.address=0.0.0.0
    logging: *log-limitado
    ports:
      - "8501:8501"
    environment: *ambiente-da-aplicacao
    depends_on:
      migrate:
        condition: service_completed_successfully

  # Fora do conjunto padrao de proposito: sem TELEGRAM_BOT_TOKEN o bot sobe so
  # para falhar. Para levantar: `docker compose --profile telegram up`.
  # O profile ADICIONA este servico aos demais; nao sobe o bot sozinho.
  telegram-bot:
    profiles: [telegram]
    build:
      context: .
      dockerfile: Dockerfile
    command: python run_telegram.py
    logging: *log-limitado
    environment:
      <<: *ambiente-da-aplicacao
      # Sem `:?` de proposito: a interpolacao roda no arquivo inteiro ANTES de
      # filtrar profiles, entao exigir a variavel aqui quebraria tambem o
      # `docker compose up` padrao, que nem sobe este servico. Quem avisa e o
      # proprio run_telegram.py, que sai com erro explicito.
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:-}
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  pgdata:
```

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

O `.dockerignore` mantém fora do contexto de build o `.venv`, o `.git`, os
caches, o `.env`, e o que não serve para rodar a aplicação: `docs/`, `seed/`,
`tests/` e os arquivos Markdown.

### `.env.example`

```env
# Copie para .env e preencha os valores marcados com PREENCHER.
#
# O .env e opcional: o compose sobe sem ele, usando os defaults, e a
# aplicacao avisa na tela o que falta para o chat funcionar. Estas mesmas
# variaveis podem vir do shell ou dos secrets de um pipeline de CD — o
# ambiente vence o .env quando as duas origens existem.

# === LLM ===
# Os nomes sao genericos de proposito: a POC fala com todo provider pela API
# OpenAI-compatible, entao a credencial nao e "da OpenAI" — e do provider que
# voce escolher. Ver a secao Configuracao do README.
#
# LLM_PROVIDER escolhe a base URL padrao e se a chave e obrigatoria:
#   openai | groq | gemini  -> endpoint conhecido, chave obrigatoria
#   ollama                  -> endpoint local, dispensa chave
#   custom                  -> exige LLM_BASE_URL (use este para Azure, vLLM,
#                              LM Studio, OpenRouter e afins)
# LLM_BASE_URL, quando preenchida, vence a padrao do provider.
LLM_PROVIDER=openai
# PREENCHER: nome do modelo ou do deployment. Nao ha valor padrao — no
# Azure e o nome do deployment, e um chute daria 404 do provider em vez de
# uma mensagem dizendo o que configurar.
LLM_MODEL=
# PREENCHER: chave do provider escolhido (dispensavel so no ollama)
LLM_API_KEY=
# Endpoint OpenAI-compatible. Vazio usa o padrao do provider; obrigatorio no custom.
LLM_BASE_URL=
# Modelo do agente de busca. Vazio usa o LLM_MODEL. Existe para poder trocar
# so a busca por um modelo mais rapido: ela roda dentro do turno, e a
# latencia dela se soma a da resposta que a pessoa espera.
LLM_MODEL_BUSCA=


# === Banco de Dados ===
DB_PASSWORD=sdr_dev_pass
# O projeto usa psycopg 3; `postgresql://` tambem funciona (normalizado em src/config.py)
# Use 127.0.0.1, nao localhost: nesta maquina o localhost resolve para ::1
# primeiro e o publish IPv6 do container nao roteia, travando a conexao.
DATABASE_URL=postgresql+psycopg://sdr:sdr_dev_pass@127.0.0.1:5432/agente_sdr
# Senha da role `busca_ro`, que executa o SQL escrito pelo agente de busca.
# Ela so tem SELECT em `imoveis` — e a fronteira que impede o SQL gerado por
# LLM de alcancar leads, telefones e conversas. Criada pela migration.
DB_PASSWORD_BUSCA=busca_ro_dev_pass

# === Telegram ===
# PREENCHER so para testar o canal Telegram. Deixe vazio caso contrario:
# um valor falso faz o bot subir e falhar na autenticacao.
TELEGRAM_BOT_TOKEN=

# === Autenticacao ===
# Assina o cookie de sessao. Se ficar vazia, a aplicacao gera uma chave
# aleatoria a cada inicializacao, avisa em log e na tela, e funciona — mas
# a sessao cai a cada restart e nao funciona com mais de uma replica.
# Nao existe valor padrao: um default no codigo seria publico, e com ele
# qualquer um forjaria um cookie de admin sem passar pelo login.
# Gere com: python -c "import secrets; print(secrets.token_urlsafe(48))"
AUTH_COOKIE_KEY=

# === LLM Custos ===
LLM_DAILY_TOKEN_BUDGET=1500000
LLM_MONTHLY_TOKEN_BUDGET=10000000
LLM_MAX_TURNS_PER_CONVERSATION=30
# Acompanha o teto de turnos: 30 turnos com busca frequente passam de 400 mil
# tokens, e um teto menor faria o handover disparar por causa da busca, e nao
# por causa do tamanho da conversa.
LLM_MAX_TOKENS_PER_CONVERSATION=400000

# === Follow-up ===
# De quantos em quantos minutos o ciclo automatico procura leads calados. So
# o intervalo: quem decide se um lead ja pode receber e a janela de silencio
# de cada regua (2h, 6h, 24h). Baixar para 1 serve para ver o ciclo numa demo.
FOLLOWUP_INTERVAL_MINUTES=30

# === Observabilidade (opcional) ===
LOGFIRE_TOKEN=
```

### Comandos de uso

```bash
# Subir app, banco e migrate (primeira vez, ou depois de mudar o código)
docker compose up -d --build

# Subir também o bot do Telegram e o scheduler de follow-up
docker compose --profile telegram up -d --build

# Ver logs
docker compose logs -f app
docker compose logs -f telegram-bot

# Parar tudo
docker compose --profile telegram down

# Resetar banco (cuidado: apaga dados)
docker compose --profile telegram down -v
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
|

---

## 4. Desenvolvimento local sem Docker (alternativa)

Para depurar a UI ou o bot fora dos containers, com o banco ainda no Compose:

```bash
# Banco, migration e catálogo pelo Compose
docker compose up -d postgres migrate

# Streamlit
streamlit run app.py

# Bot do Telegram + scheduler de follow-up
python run_telegram.py

# Ou os dois juntos, por um supervisor simples
python run_all.py
```

Com a aplicação fora do Docker, a `DATABASE_URL` do `.env` aponta para
`127.0.0.1:5432`.

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
3. Clonar repo, configurar `.env`, `docker compose --profile telegram up -d --build`.
4. Configurar Caddy ou nginx como reverse proxy com HTTPS automático (Let's Encrypt).

**Custo estimado:** $4-6/mês (tudo incluso).

---

## 6. Estrutura de Diretórios

```text
agente_imobiliario/
├── app.py                        # Streamlit: login, navegação e páginas
├── run_telegram.py               # Bot Telegram (polling) + scheduler de follow-up
├── run_all.py                    # Supervisor: inicia os dois processos
├── Dockerfile
├── docker-compose.yml            # postgres, migrate, app, telegram-bot (profile)
├── alembic.ini
├── pyproject.toml                # configuração do ruff e do pytest
├── .env.example
├── README.md
├── requirements.txt
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 29abbb20023f_schema_inicial.py  # schema inteiro e a role busca_ro
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
│   ├── config.py                 # settings e normalização da URL do banco
│   ├── tempo.py                  # fuso e formatação de data/hora
│   ├── db/
│   │   ├── models.py
│   │   └── session.py            # engine principal e engine somente-leitura da busca
│   ├── schemas/
│   │   ├── lead.py
│   │   ├── imovel.py
│   │   ├── agendamento.py
│   │   ├── mensagem.py
│   │   └── agent.py
│   ├── services/                 # regras de domínio, sem Streamlit nem LLM
│   │   ├── catalog_service.py
│   │   ├── consulta_catalogo.py  # validação e execução do SQL do agente de busca
│   │   ├── lead_service.py
│   │   ├── scheduling_service.py
│   │   ├── summary_service.py
│   │   ├── followup_service.py
│   │   └── llm_usage_service.py
│   ├── agent/
│   │   ├── sdr_agent.py          # agente conversacional e suas tools
│   │   ├── busca_agent.py        # agente que escreve o SQL da busca de imóveis
│   │   ├── perfil_agent.py       # consolidador do perfil narrativo
│   │   ├── followup_agent.py     # composição da mensagem de follow-up
│   │   ├── imoveis_mostrados.py  # o que cada lead já viu, para não repetir
│   │   ├── prompts.py
│   │   ├── provider.py           # construção do modelo, OpenAI-compatible
│   │   └── history.py            # reidratação do histórico para o PydanticAI
│   ├── channels/
│   │   ├── envio.py              # quais canais recebem mensagem por iniciativa nossa
│   │   └── telegram_bot.py       # adaptador Telegram (handlers + remetente)
│   ├── scheduler/
│   │   ├── followup_scheduler.py # APScheduler: ciclo de follow-up e despacho pendente
│   │   └── followup_runner.py    # o ciclo e o despacho em si, testáveis sem scheduler
│   └── ui/
│       ├── dashboard.py          # KPIs, carteira e painel de consumo
│       ├── leads.py              # lista e ficha do lead
│       ├── chat.py               # simulador de chat
│       ├── conversa.py           # a conversa pronta para a tela, e o custo dela
│       ├── ajuda.py
│       ├── login.py
│       ├── navegacao.py
│       ├── papeis.py             # visibilidade de menu e de bastidores por papel
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

## 7. Dependências (`requirements.txt`)

Toda dependência tem teto de major: sem ele, o pip chegou a resolver versões
cujas APIs são incompatíveis com o código.

```text
# Versoes com teto de major: sem isso o pip resolvia pydantic-ai 0.0.x -> 2.x e
# streamlit-authenticator 0.3 -> 0.4, cujas APIs sao incompativeis com o codigo.
#
# pydantic-ai-slim[openai] no lugar de pydantic-ai: a POC so usa o provider
# OpenAI (e compativeis, via OPENAI_BASE_URL). O extra ja traz o SDK `openai`.

# --- Aplicacao ---
streamlit>=1.64,<2
# Declarados mesmo vindo junto do streamlit: o dashboard monta DataFrames
# proprios e desenha os graficos em Altair, entao os imports sao nossos, nao
# transitivos.
pandas>=2.2,<3
altair>=5.5,<7
streamlit-authenticator>=0.4.2,<0.5
pydantic>=2.13,<3
pydantic-ai-slim[openai]>=2.46,<3
sqlalchemy>=2.0,<2.1
psycopg[binary]>=3.3,<4
alembic>=1.20,<2
python-dotenv>=1.2,<2
pyyaml>=6.0,<7
python-dateutil>=2.9,<3
phonenumbers>=9.0,<10
python-telegram-bot>=22.8,<23
apscheduler>=3.11,<4
bcrypt>=5.0,<6
httpx>=0.28,<1
logfire>=5.1,<6

# --- Desenvolvimento / testes ---
pytest>=9.1,<10
freezegun>=1.5,<2
ruff>=0.16,<0.17
```

---

## 8. Checklist de implementação

- [x] Instalar `psycopg[binary]` e `alembic` no `requirements.txt`.
- [x] Atualizar `src/db/session.py` para ler `DATABASE_URL` do ambiente.
- [x] Remover referências a SQLite e `PRAGMA WAL` do código.
- [x] Criar `Dockerfile`.
- [x] Criar `docker-compose.yml`.
- [x] Criar `.env.example` com todas as variáveis documentadas.
- [x] Testar `docker compose up --build` localmente.
  > A imagem constrói, o container sobe, conecta no PostgreSQL da rede do
  > Compose e serve a tela de login. O `.dockerignore` mantém `.venv`,
  > `.git` e os caches fora do contexto de build.
- [x] Configurar Alembic para migrations.
- [ ] Testar com banco PostgreSQL remoto (Neon ou Supabase free tier).
  > O desenvolvimento roda contra o PostgreSQL do Compose.
