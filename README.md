# Agente SDR Imobiliário com IA

[![CI](https://github.com/luizaaca/agente_imobiliario/actions/workflows/ci.yml/badge.svg)](https://github.com/luizaaca/agente_imobiliario/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/luizaaca/agente_imobiliario?label=vers%C3%A3o)](https://github.com/luizaaca/agente_imobiliario/releases)
[![Licença](https://img.shields.io/badge/licen%C3%A7a-PolyForm%20Noncommercial%201.0.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.64-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![PydanticAI](https://img.shields.io/badge/PydanticAI-2.46-E92063?logo=pydantic&logoColor=white)](https://ai.pydantic.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![Telegram](https://img.shields.io/badge/Telegram-bot-26A5E4?logo=telegram&logoColor=white)](#telegram)
[![LLM](https://img.shields.io/badge/LLM-OpenAI--compatible-412991?logo=openai&logoColor=white)](#o-que-llm_provider-faz--e-o-que-n%C3%A3o-faz)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

POC de um **agente conversacional de pré-venda imobiliária** para o POSTECH/FIAP — Tech Challenge (Fase 5).

O agente atende o lead em linguagem natural, qualifica pela conversa, busca imóveis no catálogo, registra visitas e entrega ao corretor um resumo do que foi conversado.

> **Status:** implementação funcional, rodando ponta a ponta no Streamlit contra PostgreSQL e um provider OpenAI-compatible. 605 testes automatizados. O canal Telegram foi percorrido com conversa real, do bot ao dashboard, e os follow-ups, automático e manual, chegaram pelo bot — ver [Limitações](#limitações-conhecidas).

---

## O que funciona hoje

| Capacidade | Estado |
|---|---|
| Chat com o agente, com memória da conversa | funcionando |
| Qualificação progressiva pela conversa (sem formulário) | funcionando |
| Busca no catálogo por um agente dedicado, que escreve SQL sobre uma role somente-leitura | funcionando, 300 imóveis |
| Busca que se afrouxa quando não há resultado exato, e degrada sem LLM se o agente de busca falhar | funcionando |
| Score do lead em 5 dimensões e avanço no funil | funcionando |
| Perfil narrativo incremental | funcionando |
| Agendamento de visita/reunião: um compromisso por lead, com os imóveis de interesse na observação | funcionando |
| Confirmar ou desmarcar a visita pela conversa | funcionando |
| Resumo executivo para o corretor | funcionando |
| Follow-up automático com 4 réguas e limite de tentativas | funcionando; envio ativo só no Telegram |
| Chat que se atualiza sozinho com o que chega por fora (follow-up, Telegram) | funcionando |
| Dashboard: KPIs, distribuição da carteira, tabela ordenável, custo de LLM | funcionando |
| Menu de leads: ficha editável, criação manual, vínculo de canal, conversa, exclusão | funcionando |
| Agendamento pela tela: criar, editar e excluir, com seletor de data e hora | funcionando |
| Disparo manual de follow-up pela tela, mostrando a mensagem gerada | funcionando |
| Menu conforme o papel do usuário (`admin` / `corretor`) | funcionando |
| Página de ajuda com estado da instalação e FAQ | funcionando |
| Budgets de token (conversa, dia, mês) e custo estimado, também por conversa | funcionando |
| Canal Telegram | funcionando; percorrido com conversa real, do bot ao painel, e com follow-ups automático e manual entregues pelo bot |

### O diferencial

O **`perfil_narrativo`** é o artefato central: um texto incremental mantido ao longo da conversa com preferências, objeções, contexto de vida e — o mais valioso — as **rejeições** ("descartou o de Moema por causa do condomínio de R$ 1.800"). É ele que o corretor lê antes de ligar.

---

## Como executar

### Pré-requisitos
- Docker e Docker Compose — é só disso que a Opção 1 precisa
- Python 3.11+ (desenvolvido em 3.13), apenas para a Opção 2
- Uma chave de um provider OpenAI-compatible, apenas para o chat responder

### Opção 1 — Docker Compose (caminho recomendado)

Clone a versão entregue e suba — é um comando:

```bash
git clone --branch v0.1.0 https://github.com/luizaaca/agente_imobiliario.git
```

```bash
cd agente_imobiliario
```

```bash
docker compose up --build
```

Sobem três serviços, nesta ordem: `postgres`, depois `migrate` (que aplica as migrations e **carrega os 300 imóveis do catálogo**, versionado em `data/imoveis_catalogo.csv`) e por fim `app`. A primeira build leva alguns minutos. O Streamlit fica em **http://localhost:8501**.

Assim, sem nenhuma configuração, a aplicação já abre e o painel funciona. Para o agente conversar é preciso uma chave de LLM, e para o canal Telegram, um token de bot — os dois entram pelo `.env`, explicado logo abaixo em [Chaves: o `.env`](#chaves-o-env). O Telegram tem [seção própria](#telegram).

#### Credenciais de acesso

Toda a aplicação está atrás de login. O repositório já traz usuários prontos em `config/credentials.yaml` — só os hashes bcrypt, nunca a senha em texto:

| Usuário | Senha | Papel (`roles`) | Vê o Simulador de Chat, o custo de LLM e as ferramentas que o agente usou? |
|---|---|---|---|
| `admin` | `admin123` | `admin` | sim |
| `corretor1` | `corretor123` | `corretor` | não |

Depois de entrar, o menu **Ajuda** explica de dentro da aplicação o que cada tela faz, como trabalhar um lead e por que a aplicação se comporta como se comporta — inclusive o estado desta instalação (chat configurado ou não, seu papel, se a sessão é estável).

**Entre como `admin` para avaliar a POC inteira.** O simulador de chat é ferramenta de teste, e o consumo de LLM e as chamadas de ferramenta do agente são informação de quem opera, então nada disso aparece para o `corretor` — entre como `corretor1` se quiser ver a tela enxuta de quem só atende leads. Dashboard e menu de Leads são iguais para os dois.

O papel esconde links do menu; **não é controle de acesso**. Ele mora neste YAML versionado, e quem o edita se dá o papel que quiser. Ver [`docs/03-operacao/03-autenticacao-da-ui.md`](docs/03-operacao/03-autenticacao-da-ui.md).

> Este arquivo é versionado **de propósito, e só por ser uma POC de avaliação**: sem ele ninguém entra na aplicação depois de clonar. As senhas são públicas e não protegem nada. Em uso real, gere hashes novos e tire o arquivo do versionamento — a linha já está comentada no `.gitignore`.

#### Adicionar um usuário de teste

**1. Gere o hash da senha.** Se você subiu pelo Compose, não precisa de Python na máquina — rode dentro do container:

```bash
docker compose exec app python -m scripts.generate_password_hash
```

Localmente, com o ambiente virtual ativo, é `python -m scripts.generate_password_hash`. O script pede a senha sem ecoar na tela e imprime algo como `$2b$12$...`.

**2. Acrescente o bloco em `config/credentials.yaml`**, dentro de `credentials.usernames`, no mesmo recuo dos outros:

```yaml
    avaliador:
      name: Avaliador POC
      email: avaliador@exemplo.local
      roles: [admin]
      password: "$2b$12$cole_o_hash_gerado_aqui"
```

O `roles` aceita `[admin]` ou `[corretor]`. Sem ele, o usuário entra com o menu do corretor — ausência de papel não promove ninguém.

**3. Aplique a mudança.** Em execução local, basta recarregar a página: o arquivo é lido a cada carga. No Docker, o `Dockerfile` copia o projeto para dentro da imagem, então é preciso reconstruir — rápido, porque só a última camada muda:

```bash
docker compose up -d --build app
```

#### Chaves: o `.env`

O `.env` é o arquivo onde entram as chaves. Ele é **opcional para subir** — o `docker-compose.yml` tem valor padrão para tudo —, mas **sem ele não há chat nem Telegram**: dashboard e Leads funcionam, inclusive ficha e conversa já registrada, mas o chat fica desativado, o disparo de follow-up não gera mensagem e o bot não sobe.

Crie a partir do exemplo, na raiz do repositório:

```bash
cp .env.example .env
```

| Para quê | Variáveis | Onde conseguir |
|---|---|---|
| **o agente conversar** | `LLM_API_KEY` e `LLM_MODEL`; `LLM_BASE_URL` se o provider não for a OpenAI | o painel do seu provider. Qualquer OpenAI-compatible serve: OpenAI, Azure AI Foundry, Groq, Gemini ou Ollama local — ver [Configuração](#configuração) |
| **o canal Telegram** | `TELEGRAM_BOT_TOKEN` | o @BotFather, no próprio Telegram — passo a passo em [Telegram](#telegram) |
| a sessão não cair a cada reinício | `AUTH_COOKIE_KEY` | gerada por você — ver [Autenticação](#autenticação). Opcional |

Depois de editar, suba de novo — o Compose relê o `.env` a cada `up`:

```bash
docker compose up -d
```

> **Como o `.env` chega aos containers.** O Compose lê o `.env` da raiz sozinho e o usa para preencher os `${VAR}` do `docker-compose.yml`; só as variáveis listadas lá entram nos containers. Por isso a alternativa ao arquivo funciona igual: variáveis do shell, como `LLM_API_KEY=... docker compose up`. A exceção é o `DATABASE_URL`: o que estiver no `.env` não chega aos containers, porque o compose monta a URL apontando para `postgres:5432` — `127.0.0.1` dentro do container seria o próprio container.

#### Se algo der errado

| Sintoma | Causa |
|---|---|
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | já há um PostgreSQL na 5432. Pare o outro, ou mapeie outra porta em um `docker-compose.override.yml` |
| `Bind for 0.0.0.0:8501 failed` | já há um Streamlit rodando na 8501 |
| O chat responde só "atendimento temporariamente indisponível" | falta `LLM_API_KEY` ou `LLM_MODEL` — a própria tela do chat diz quais |
| `checking context: can't stat ... .pytest_cache` | diretório de cache com permissões travadas na cópia local; apague-o e rode de novo |

Para encerrar: `docker compose down`. **Não use `-v`** a menos que queira apagar o banco junto.

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

Preencha no `.env` pelo menos `LLM_API_KEY`, `LLM_MODEL` e `AUTH_COOKIE_KEY`. Depois:

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

O login é o mesmo das [credenciais de acesso](#credenciais-de-acesso) acima.

### Telegram

O canal real do agente. O interessado conversa com a Marina num bot do Telegram, o lead aparece no painel e os follow-ups chegam a ele pelo bot. Cada avaliador usa **o próprio bot**: o token não vai no repositório.

**1. Crie o bot.** No Telegram, abra uma conversa com o **@BotFather** e mande `/newbot`. Ele pede um nome de exibição (por exemplo, `Marina Imóveis`) e um nome de usuário que termine em `bot` (por exemplo, `marina_avaliacao_bot`). No fim, responde com o **token**, no formato `123456789:AAH...`. O token é uma senha: quem o tem controla o bot.

**2. Ponha o token no `.env`**, junto das chaves de LLM — o bot conversa pelo agente, então sem LLM ele sobe mas não responde:

```env
TELEGRAM_BOT_TOKEN=123456789:AAH...
```

**3. Suba com o profile `telegram`.** O bot fica fora do conjunto padrão de propósito — sem token ele subiria só para falhar. O profile **acrescenta** o serviço `telegram-bot` aos demais:

```bash
docker compose --profile telegram up -d --build
```

Para conferir que ele está no ar:

```bash
docker compose logs telegram-bot
```

As linhas que importam são `Scheduler de follow-up iniciado junto ao bot` e `Application started`. Sem token, o serviço sai com uma mensagem dizendo isso.

**4. Converse.** No Telegram, procure o bot pelo nome de usuário e toque em **Iniciar**. A Marina se apresenta, pede o telefone — o nome ela já tira do seu perfil — e segue a conversa: o que você procura, imóveis, visita.

**5. Veja o lead no painel.** Ele aparece em **Leads** com o nome do seu perfil do Telegram, e a aba **Conversa** da ficha mostra o histórico — inclusive as ferramentas que o agente chamou, para quem entra como `admin`.

**6. Receba um follow-up.** Na ficha do lead, ou na linha dele na lista, use **Disparar follow-up**. A mensagem é gerada na hora e o bot a entrega no Telegram em até uns 10 segundos.

**O follow-up automático** roda no mesmo processo do bot, a cada 30 minutos (`FOLLOWUP_INTERVAL_MINUTES`), e só alcança quem está em silêncio há tempo suficiente para a régua: 2 horas para lead novo, 6 horas para qualificação interrompida, 24 horas depois de receber imóveis; o lembrete de visita sai 24 horas antes dela. Numa avaliação curta, o botão do passo 6 é o jeito de vê-lo funcionar. Sem o bot no ar, o ciclo automático não acontece.

**Cuidados**

- **Um token, um processo.** O Telegram entrega as mensagens de um bot a um consumidor só. Rodar o bot no Compose e localmente ao mesmo tempo dá `Conflict: terminated by other getUpdates request`: pare um dos dois.
- **O bot não inicia conversa.** O Telegram não deixa um bot escrever para quem nunca falou com ele, então o follow-up só alcança quem já mandou mensagem ao bot.
- **Token vazado** se revoga no @BotFather com `/revoke`; ponha o novo no `.env` e suba o bot de novo.

Na [Opção 2](#opção-2--local), o bot roda com `python run_telegram.py`, com o mesmo `.env`.

---

## Configuração

Tudo se configura por **variável de ambiente**. Como elas chegam ao processo é escolha de quem executa — a aplicação não distingue:

- um arquivo `.env` na raiz (o Compose o lê sozinho; `cp .env.example .env`);
- variáveis do shell: `LLM_API_KEY=sk-... docker compose up`;
- secrets do pipeline de CD, injetados como `env` do passo.

Quando a mesma variável vem de mais de uma origem, **a do ambiente vence a do `.env`**. Nenhum segredo entra na imagem: as variáveis só existem em tempo de execução.

### Obrigatórias para o chat funcionar

| Variável | Para quê |
|---|---|
| `LLM_PROVIDER` | atalho de endpoint. `openai`, `groq`, `gemini`, `ollama` ou `custom`. Padrão: `openai` |
| `LLM_MODEL` | nome do modelo ou do *deployment*. **Sem padrão** — no Azure é o nome do deployment, e chutar um nome daria um 404 do provider em vez de uma mensagem dizendo o que falta |
| `LLM_API_KEY` | credencial do provider escolhido. Dispensável só no `ollama`, que roda local |
| `LLM_BASE_URL` | endpoint OpenAI-compatible. Obrigatória apenas no `custom`; nos demais, vazia significa usar o endpoint padrão do provider |

Faltando qualquer uma delas, a aplicação **sobe do mesmo jeito**: o dashboard e o catálogo funcionam, e a aba do chat mostra quais variáveis estão ausentes e desativa o campo de mensagem. Não há falha silenciosa nem `compose up` abortado.

> Todas as variáveis usam o prefixo `LLM_` porque a POC fala com todo provider pela API OpenAI-compatible ([ADR 0006](./docs/06-decisoes/adr/0006-provider-openai-compatible-configuravel.md)). A credencial é *do provider que você escolher* em `LLM_PROVIDER`, não da OpenAI.

### O que `LLM_PROVIDER` faz — e o que não faz

Ele **não chega ao SDK**. Só `LLM_API_KEY` e a base URL resolvida chegam. O que ele decide é:

| Valor | Base URL padrão | Chave obrigatória? |
|---|---|---|
| `openai` | `https://api.openai.com/v1` | sim |
| `groq` | `https://api.groq.com/openai/v1` | sim |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` | sim |
| `ollama` | `http://localhost:11434/v1` | **não** — roda local |
| `custom` | nenhuma: **exige `LLM_BASE_URL`** | sim |

**`LLM_BASE_URL`, quando preenchida, vence sempre.** É por isso que um endpoint Azure funciona com qualquer valor de `LLM_PROVIDER`: o destino vem da base URL, não do nome do provider.

**Para Azure AI Foundry, vLLM, LM Studio, OpenRouter e afins, use `custom`.** O comportamento com a `LLM_BASE_URL` preenchida é idêntico ao de `openai`; a diferença aparece quando ela falta:

| Com `LLM_PROVIDER=openai` | Com `LLM_PROVIDER=custom` |
|---|---|
| A aplicação sobe e manda sua chave do Azure para `api.openai.com` | Falha dizendo que `LLM_BASE_URL` está ausente |

A base URL do `openai` é passada explicitamente ao SDK, e não deixada em branco: o SDK da OpenAI lê a variável `OPENAI_BASE_URL` do ambiente por conta própria quando não recebe `base_url`, e uma variável solta redirecionaria as chamadas sem nada no código indicar isso.

### Autenticação

| Variável | Para quê |
|---|---|
| `AUTH_COOKIE_KEY` | assina o cookie de sessão do Streamlit |

**Se estiver ausente, a aplicação gera uma chave aleatória na inicialização**, registra alerta no log e mostra um balão dispensável na tela. Dá para operar assim, com duas limitações:

- **a sessão cai a cada reinício** da aplicação, porque a chave é sorteada de novo e os cookies anteriores deixam de ser válidos;
- **não funciona com mais de uma réplica**: cada processo assinaria com uma chave diferente e o usuário seria deslogado ao cair numa réplica distinta daquela em que entrou.

Para fixar, defina a variável com um valor aleatório e duradouro:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Não existe valor padrão de propósito. Um default no código seria público — e quem o conhece consegue **forjar um cookie e entrar como administrador sem passar pelo login**.

### Demais variáveis

| Variável | Para quê |
|---|---|
| `DATABASE_URL` | PostgreSQL. `postgresql://` é normalizado para `postgresql+psycopg://`. No Compose é montada apontando ao serviço `postgres` |
| `DB_PASSWORD` | senha do PostgreSQL do Compose. Padrão: `sdr_dev_pass` |
| `DB_PASSWORD_BUSCA` | senha da role `busca_ro`, somente-leitura em `imoveis`, que executa o SQL do agente de busca. Padrão: `busca_ro_dev_pass` |
| `LLM_MODEL_BUSCA` | modelo do agente de busca. Vazio usa o `LLM_MODEL` |
| `TELEGRAM_BOT_TOKEN` | só para o canal Telegram. Sem ela, `run_telegram.py` sai com erro explícito |
| `LLM_DAILY_TOKEN_BUDGET`, `LLM_MONTHLY_TOKEN_BUDGET` | tetos de consumo. Atingidos, o agente responde que está indisponível |
| `LLM_MAX_TOKENS_PER_CONVERSATION`, `LLM_MAX_TURNS_PER_CONVERSATION` | quando encerrar a conversa e fazer handover ao corretor |
| `FOLLOWUP_INTERVAL_MINUTES` | de quantos em quantos minutos o ciclo automático de follow-up roda. Padrão: 30 |
| `LOGFIRE_TOKEN` | observabilidade, opcional |

O exemplo completo, com comentários, está em `.env.example`.

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
        src/agent/    agente PydanticAI + 9 tools, agente de busca
        src/services/ regras de domínio
        src/db/       SQLAlchemy + Alembic
                       │
                  PostgreSQL 16
```

O agente nunca toca no banco: ele chama tools, que chamam services. O canal não tem regra de negócio.

### Decisões que valem explicar

**O modelo é resolvido por event loop.** Cada mensagem do Streamlit roda em um `asyncio.run` próprio, que fecha o loop ao terminar. Um cliente HTTP em cache global morria junto com o primeiro loop e derrubava a segunda mensagem com `Event loop is closed`. O `build_model()` mantém um modelo por loop, em `WeakKeyDictionary`.

**A busca textual é coluna gerada, não trigger.** `imoveis.search_vector` é `GENERATED ALWAYS AS (to_tsvector(...)) STORED` com índice GIN: o PostgreSQL mantém o vetor sozinho, sem código de aplicação que possa esquecer de atualizar. A consulta usa `websearch_to_tsquery` com OU entre os termos e ordena por `ts_rank`.

**Quem procura imóvel não é quem conversa.** A Marina manda o pedido em texto livre a um agente de busca dedicado ([ADR 0007](./docs/06-decisoes/adr/0007-agente-de-busca-dedicado.md)), que consulta o catálogo por SQL, afrouxa um critério por vez quando nada casa e devolve os IDs com o porquê de cada um. O SQL roda numa role que só tem `SELECT` em `imoveis`, com a transação em `READ ONLY` e tempo limite. Se esse agente falhar, a tool cai numa busca estruturada sem LLM (`search_relaxando`), que devolve em português o que afrouxou.

**O contexto do lead lista só o que se sabe.** Mandar todo campo com "não informado" ao lado entregava ao modelo um formulário em branco — e ele conduzia a conversa preenchendo campos, um a um.

**Excluir um lead preserva o consumo de LLM.** As linhas de `llm_usage` só perdem o vínculo (`lead_id` fica nulo). Os tokens foram gastos de fato; apagá-los transformaria a exclusão de leads em uma forma de zerar o controle de orçamento.

---

## Testes

Com o Compose no ar, sem Python na máquina:

```bash
docker compose exec app pytest
```

No ambiente da [Opção 2](#opção-2--local), é só `pytest`. São 605 testes, ~1 minuto, e rodam a cada push no [CI](.github/workflows/ci.yml). Cobrem services, contrato das nove tools, agente de busca e a fronteira da role somente-leitura, despacho de follow-up, ciclo de mensagem, budgets, livro-caixa de chamadas ao provider, réguas de follow-up e disparo manual, edição de lead e vínculo de canal, visibilidade de menu por papel, alinhamento dos schemas com o ORM e os **3 cenários obrigatórios** (`tests/test_cenarios.py`): compra residencial, investimento e follow-up automático.

Duas decisões que explicam a suíte:

**PostgreSQL de verdade, em um banco separado (`<banco>_test`), não SQLite.** SQLite ignora o tamanho declarado em `VARCHAR`, então um bug real — a LLM gravando 95 caracteres em uma coluna `VARCHAR(30)` — passaria despercebido. As CHECK constraints e o comportamento transacional também só são fiéis no Postgres.

**O schema da suíte vem de `alembic upgrade head`**, em um banco recriado a cada execução, e não de `create_all()`. É o mesmo caminho que roda em produção: um modelo que ande sem a migration correspondente quebra os testes em vez de passar despercebido.

Lint:

```bash
docker compose exec app ruff check .
```

---

## Catálogo de imóveis

300 imóveis sintéticos em `data/imoveis_catalogo.csv`, carregados por `python -m scripts.seed_imoveis`. O seed é idempotente: usa SAVEPOINT por linha, pula duplicados e ressincroniza a sequência do ID ao final.

O processo de geração do catálogo está documentado em `seed/` (`planejamento_geracao_catalogo.md` e `walkthrough.md`).

---

## Limitações conhecidas

São limitações reais da entrega, não do desenho:

- **Sem streaming de resposta.** O chat espera a resposta completa e então a exibe.
- **A UI tem pouco teste de renderização.** As regras por trás dela têm (visibilidade de menu, edição de lead, vínculo de canal, disparo de follow-up), e toda página roda pelo `AppTest` numa instalação sem nenhum lead, nos dois papéis — é o que garante que a primeira tela de quem clona não quebra. O resto da renderização foi verificado manualmente no navegador; a exceção é o chat, que também roda pelo `AppTest` para provar que mostra o que chegou à conversa por fora dele.
- **O follow-up só envia ativamente pelo Telegram.** Sem canal com push, a mensagem é gerada e registrada com status `generated`, mas não sai. No Streamlit ela aparece no histórico do lead. O que o painel gera para um lead do Telegram fica à espera do processo do bot, que o envia se ainda for recente (até 15 minutos) e se o lead não tiver respondido nesse meio-tempo; senão, a tentativa vira `skipped`.
- **Custo estimado por tabela fixa** (`LLMUsageService.PRICING`). Modelo fora da tabela cai num preço genérico e registra aviso no log — o número aparece no dashboard, mas é um palpite.
- **O tom do agente degrada em conversas longas.** Ele tende a voltar a listar opções e oferecer menus de próximos passos, porque imita as próprias mensagens anteriores no histórico.
- **Lead criado à mão ainda não é atendível ponta a ponta.** O corretor cria a ficha e vincula um canal, e o follow-up passa a alcançá-lo — mas o identificador do canal não é validado na hora de vincular, e no Telegram o bot não consegue iniciar conversa com quem nunca falou com ele.
- **Sem CRM nem calendário externos.** Agendamento é uma linha no banco.
- **Autenticação simples**, por arquivo de credenciais com hash bcrypt. Os papéis `admin` e `corretor` escondem links do menu, mas não são autorização: o YAML é versionado e as páginas não verificam papel dentro de si.
- **Busca vetorial (`pgvector`) não entra na POC** — o FTS do PostgreSQL cobre o caso.

---

## Estrutura do projeto

```text
agente_imobiliario/
├── app.py                  # Streamlit: autenticação, papéis e navegação
├── run_telegram.py         # bot + scheduler de follow-up
├── run_all.py              # sobe os dois em paralelo
├── src/
│   ├── agent/              # agente, tools, prompts, provider, histórico
│   ├── channels/           # adaptador do Telegram
│   ├── db/                 # modelos SQLAlchemy e sessão
│   ├── scheduler/          # ciclo e agendamento do follow-up
│   ├── schemas/            # contratos Pydantic (espelham o ORM)
│   ├── services/           # regras de domínio
│   └── ui/                 # páginas Streamlit (dashboard, leads, chat, ajuda) e papéis
├── alembic/versions/       # migrations
├── data/                   # catálogo de imóveis (CSV)
├── scripts/                # seed, hash de senha, follow-up manual
├── tests/                  # 605 testes
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

- Percorrer o canal Telegram ponta a ponta com uma conversa real.
- Streaming de resposta no chat.
- Testes automatizados da UI.
- Preços reais por modelo na tabela de custo.
- Fechar o ciclo do lead criado à mão: validar o identificador no canal e resolver o caso do Telegram, em que o bot não inicia conversa.
- Busca vetorial com `pgvector` como evolução do ranking textual.

---

## Licença

[PolyForm Noncommercial 1.0.0](LICENSE). O código é aberto para ler, usar, modificar e redistribuir **sem finalidade comercial**: estudo, pesquisa, uso pessoal, avaliação, ensino e organizações sem fins lucrativos. Uso comercial depende de autorização do autor.

Por restringir uso comercial, ela não é uma licença *open source* pela definição da OSI, e sim *source-available*.
