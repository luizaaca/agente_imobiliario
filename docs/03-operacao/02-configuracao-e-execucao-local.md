# Configuração e Execução Local

**Objetivo:** concentrar as instruções operacionais do ambiente local, incluindo pré-requisitos, variáveis de ambiente e formas de execução da POC durante desenvolvimento e demonstração.

---

## 1. Pré-requisitos

Para executar a POC localmente, o ambiente deve ter:

- Python 3.11+
- Docker e Docker Compose
- acesso a um banco PostgreSQL local ou remoto
- arquivo `.env` configurado com as credenciais necessárias

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
- `TELEGRAM_BOT_TOKEN`
- `AUTH_COOKIE_KEY`

Os detalhes completos de infraestrutura e exemplos de configuração estão em [`01-infraestrutura-e-deploy.md`](./01-infraestrutura-e-deploy.md).

---

## 3. Modos de execução

### 3.1 Docker Compose

Modo recomendado para desenvolvimento reproduzível:

```bash
docker-compose up --build
```

### 3.2 Processos separados

Modo útil para desenvolvimento iterativo:

```bash
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
- usar processos separados quando o objetivo for depurar UI ou bot isoladamente;
- validar o `.env` antes da demo para evitar falhas por configuração ausente;
- manter o banco populado com dados de demonstração coerentes.

---

## 5. Relação com outros documentos

- infraestrutura e deploy: [`01-infraestrutura-e-deploy.md`](./01-infraestrutura-e-deploy.md)
- autenticação da UI: [`03-autenticacao-da-ui.md`](./03-autenticacao-da-ui.md)
- governança de custos LLM: [`04-governanca-de-custos-llm.md`](./04-governanca-de-custos-llm.md)