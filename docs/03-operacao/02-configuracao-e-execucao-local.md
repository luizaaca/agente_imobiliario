# Configuração e Execução Local

**Objetivo:** concentrar as instruções operacionais do ambiente local, incluindo pré-requisitos, variáveis de ambiente e formas de execução da POC durante desenvolvimento e demonstração.

---

## 1. Pré-requisitos

Para executar a POC localmente, o ambiente deve ter:

- Docker e Docker Compose (v2, o comando `docker compose`)
- Python 3.11+, só para rodar fora dos containers ou rodar os testes
- arquivo `.env`, opcional: sem ele o Compose sobe com defaults, e a
  aplicação avisa na tela o que falta para o chat funcionar

---

## 2. Variáveis de ambiente principais

As variáveis esperadas incluem:

- `DATABASE_URL`
- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLM_API_KEY`
- `LLM_BASE_URL` (opcional; obrigatoria no `LLM_PROVIDER=custom`)
- `LLM_MODEL_BUSCA` (opcional; vazio usa o `LLM_MODEL`)
- `DB_PASSWORD_BUSCA` (senha da role somente-leitura do agente de busca)
- `TELEGRAM_BOT_TOKEN` (só para o canal Telegram)
- `AUTH_COOKIE_KEY` (vazia, cada processo sorteia uma chave e as sessões caem no restart)
- `LLM_DAILY_TOKEN_BUDGET`, `LLM_MONTHLY_TOKEN_BUDGET`,
  `LLM_MAX_TURNS_PER_CONVERSATION`, `LLM_MAX_TOKENS_PER_CONVERSATION`
  (tetos de custo, com defaults)
- `FOLLOWUP_INTERVAL_MINUTES` (intervalo do ciclo automático de follow-up;
  padrão 30)
- `LOGFIRE_TOKEN` (opcional)

Os detalhes completos de infraestrutura e exemplos de configuração estão em [`01-infraestrutura-e-deploy.md`](./01-infraestrutura-e-deploy.md).

---

## 3. Modos de execução

### 3.1 Docker Compose

Modo recomendado para desenvolvimento reproduzível. O serviço `migrate`
aplica a migration e carrega o catálogo antes de a aplicação subir.

```bash
# Banco, migrate e Streamlit
docker compose up -d --build

# Os mesmos, mais o bot do Telegram e o scheduler de follow-up
docker compose --profile telegram up -d --build
```

### 3.2 Processos separados

Modo útil para desenvolvimento iterativo, com o banco ainda no Compose e a
`DATABASE_URL` do `.env` apontando para `127.0.0.1:5432`:

```bash
docker compose up -d postgres migrate
streamlit run app.py
python run_telegram.py
```

### 3.3 Supervisor local

Modo conveniente para demonstração:

```bash
python run_all.py
```

---

## 4. Recomendações operacionais

- usar Docker Compose quando o objetivo for validar integração ponta a ponta;
- para ver um ciclo de follow-up sem esperar o intervalo, rodar
  `docker compose exec app python -m scripts.run_followup_once`;
- usar processos separados quando o objetivo for depurar UI ou bot isoladamente;
- validar o `.env` antes da demo para evitar falhas por configuração ausente;
- manter o banco populado com dados de demonstração coerentes.

---

## 5. Relação com outros documentos

- infraestrutura e deploy: [`01-infraestrutura-e-deploy.md`](./01-infraestrutura-e-deploy.md)
- autenticação da UI: [`03-autenticacao-da-ui.md`](./03-autenticacao-da-ui.md)
- governança de custos LLM: [`04-governanca-de-custos-llm.md`](./04-governanca-de-custos-llm.md)