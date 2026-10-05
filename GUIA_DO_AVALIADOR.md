# Guia do avaliador

Um percurso de 30 a 40 minutos pela POC do **Agente SDR Imobiliário** — POSTECH/FIAP Tech Challenge, Fase 5 —, na ordem em que as coisas fazem sentido: subir, entrar, ver a arquitetura, conversar com o agente nos três cenários do enunciado, olhar o lado do corretor e conferir a qualidade.

Cada passo diz **o que fazer** e **o que observar**. O [README](README.md) tem os detalhes de instalação e configuração; aqui está o caminho.

> **As respostas do agente variam a cada execução.** É um modelo de linguagem: as mensagens sugeridas abaixo levam aos comportamentos descritos, mas não às mesmas palavras. Se a conversa tomar outro rumo, responda como um cliente responderia — o agente acompanha.

---

## 0. Antes de começar (5 min)

Você precisa de:

- **Docker** — ou, sem Docker, Python 3.11+ e um PostgreSQL 16 (ver [Opção 2 do README](README.md#opção-2--local));
- **uma chave de LLM** de um provider compatível com a API da OpenAI (OpenAI, Azure AI Foundry, Groq, Gemini ou Ollama local) e o nome de um modelo dele;
- **opcional, para o Telegram:** um token de bot, criado em um minuto com o @BotFather — passo a passo em [Telegram, no README](README.md#telegram).

Clone a versão entregue e crie o `.env`:

```bash
git clone --branch v0.1.0 https://github.com/luizaaca/agente_imobiliario.git
```

```bash
cd agente_imobiliario
```

```bash
cp .env.example .env
```

No `.env`, preencha:

| Variável | Para quê |
|---|---|
| `LLM_API_KEY`, `LLM_MODEL` | o agente conversar — sem elas a aplicação sobe, mas o chat fica desativado |
| `LLM_BASE_URL` | só se o provider não for a OpenAI |
| `TELEGRAM_BOT_TOKEN` | o canal Telegram — opcional |
| `AUTH_COOKIE_KEY` | opcional: sem ela a sessão cai a cada reinício e aparece um aviso amarelo. Gere com `python -c "import secrets; print(secrets.token_urlsafe(48))"` |

Suba — com o Telegram, acrescente o profile:

```bash
docker compose --profile telegram up -d --build
```

Sem token de bot, use só `docker compose up -d --build`. A primeira build leva alguns minutos. **O que observar:** `docker compose ps` mostra `postgres`, `app` e — com o profile — `telegram-bot` no ar, e o serviço `migrate` terminado com sucesso: ele aplicou o schema e carregou **300 imóveis** no catálogo.

---

## 1. Primeiro acesso (2 min)

Abra **http://localhost:8501** e entre como **`admin` / `admin123`**.

| Usuário | Senha | O que vê |
|---|---|---|
| `admin` | `admin123` | tudo: o **Simulador de Chat**, o custo de LLM e as ferramentas que o agente chamou |
| `corretor1` | `corretor123` | a tela enxuta de quem só atende leads |

**Avalie como `admin`.** Entre como `corretor1` no fim, se quiser comparar.

**O que observar:**
- **Dashboard** zerado, sem erro: é uma instalação nova — os leads nascem das conversas dos próximos passos.
- O menu **Ajuda** mostra o estado desta instalação: se o chat está configurado, o seu papel, se a sessão é estável. Se o chat aparecer como não configurado, falta chave de LLM no `.env`.

---

## 2. Arquitetura (5 min)

Antes de conversar com o agente, vale ter o mapa:

| Para entender | Leia |
|---|---|
| Componentes e processos | [README — Arquitetura](README.md#arquitetura) e [Visão geral da solução](docs/02-arquitetura/01-visao-geral-da-solucao.md) |
| Os agentes e as ferramentas | [Estratégia de agente e tools](docs/02-arquitetura/02-estrategia-de-agente-e-tools.md) |
| Por que cada escolha | [ADRs](docs/06-decisoes/adr/), em especial o [0007 — agente de busca dedicado](docs/06-decisoes/adr/0007-agente-de-busca-dedicado.md) e o [0005 — perfil narrativo](docs/06-decisoes/adr/0005-perfil-narrativo-como-artefato-central.md) |

Em uma frase: dois processos — o painel Streamlit e o bot do Telegram com o agendador de follow-up — sobre a mesma camada de domínio e o mesmo PostgreSQL. **O agente nunca toca o banco**: chama ferramentas, que chamam serviços. **O canal não tem regra de negócio**: trocar Telegram por WhatsApp é trocar um adaptador.

**A IA utilizada são quatro agentes de LLM**, cada um com uma responsabilidade:

| Agente | Papel |
|---|---|
| **Marina** | conversa com o cliente; tem nove ferramentas — buscar e detalhar imóveis, registrar a qualificação, atualizar o perfil, agendar, listar, confirmar e cancelar visitas, encerrar passando ao corretor |
| **Agente de busca** | recebe o pedido em linguagem natural e escreve SQL sobre o catálogo, numa role do PostgreSQL só com leitura na tabela de imóveis |
| **Consolidador do perfil** | mantém o **perfil narrativo**: contexto de vida, preferências e as recusas com o motivo de cada uma |
| **Agente de follow-up** | escreve as mensagens de retomada, com o contexto da conversa |

---

## 3. Cenário 1 — compra (8 min)

Pelo **Telegram**, se você configurou o bot — é o canal real. Senão, pelo **Simulador de Chat** do painel, com **+** para uma conversa nova: é a mesma Marina.

No Telegram, procure o bot pelo nome de usuário e toque em **Iniciar**. Depois, uma mensagem por vez:

| Você envia | O que observar |
|---|---|
| *(Iniciar, no Telegram)* ou `oi` | Ela se apresenta como alguém da equipe da imobiliária — sem se anunciar como robô — e pede o contato. No Telegram ela já chama pelo nome do seu perfil e pede só o telefone. |
| `Estou procurando apartamento na zona sul` | A frase do enunciado. Ela mostra que entendeu e conduz a qualificação **uma pergunta por mensagem** — conversa, não formulário. |
| `11 98765-4321` | Telefone registrado — é por ele que o corretor liga. |
| `Até 900 mil, com 2 ou 3 quartos` | Ela busca e apresenta **um destaque e alternativas**, com o ID de cada imóvel e o que a descrição tem de concreto. A pergunta do fim se liga a um dos imóveis e puxa algo da sua vida. |
| `Trabalho de casa, moro com minha esposa e nossa filha de 5 anos` | O que você conta sem ser perguntado reaparece ligado a um imóvel na resposta seguinte. |
| `A gente precisa mudar até março` | Urgência identificada — é o dado que mais pesa na prioridade do lead. |
| `Esse primeiro ficou caro` | Recusa pelo motivo: ela registra que **o preço** pesou — não o bairro, não o tipo — e não volta a oferecer aquele imóvel. |
| `Gostei do [ID de um deles]. Dá pra visitar sábado às 10h?` | A visita é marcada, com o imóvel na observação. |

**Perguntas que valem fazer no meio do caminho**, para ver o agente sob pressão:
- `Você é um robô?` — ela diz a verdade e segue a conversa;
- `Esse tem vaga de garagem?` sobre um imóvel já mostrado — ela responde da ficha, sem buscar de novo;
- `Tem casa com 5 suítes na zona sul por 300 mil?` — quando nada atende, ela diz o que o catálogo tem, sem oferecer outra coisa como se fosse o pedido.

---

## 4. O lado do corretor (5 min)

No painel, menu **Leads**.

**O que observar:** o lead do Cenário 1 aparece com status **agendado** e score de 7 ou mais — visita marcada garante piso de 7, e ele entra entre os **leads quentes**. No Telegram, ele vem com o nome do seu perfil.

Abra a ficha (ícone de lápis) e passe pelas abas:

| Aba | O que observar |
|---|---|
| **Ficha** | os campos que a conversa preencheu sozinha: intenção, orçamento, região, quartos, urgência, telefone |
| **Resumo** | o **resumo executivo**, gerado quando o atendimento terminou — aqui, pela visita —, com o perfil narrativo dentro. É o que o corretor lê antes de ligar |
| **Canal** | a identidade do lead no Telegram ou no simulador |
| **Conversa** | o histórico completo, com as ferramentas que a Marina chamou e, em cada busca, as consultas SQL que o agente de busca escreveu — a decisão do agente é auditável |
| **Agendamentos** | a visita marcada, editável |

---

## 5. Cenário 2 — investimento (5 min)

**Simulador de Chat**, conversa nova (**+**):

| Você envia | O que observar |
|---|---|
| `Quero investir em imóveis para renda` | A frase do enunciado. Intenção **investimento**, perfil **investidor**. |
| `Tenho uns 500 mil, penso em algo pequeno para alugar` | O ticket entra na ficha; a busca traz imóveis à venda adequados a investidor. |
| `Espero uns 0,6% ao mês de aluguel` | A expectativa de retorno vai para o perfil narrativo. |
| `Prefiro falar com um especialista antes de decidir` | Ela encerra o atendimento e encaminha ao corretor, gerando o resumo executivo. |

**O que observar:** no topo do simulador, os **tokens e o custo estimado** desta conversa. Na ficha deste lead, a aba **Resumo** traz o perfil de investidor, o ticket e a expectativa de retorno — o especialista não precisa perguntar de novo.

---

## 6. Cenário 3 — follow-up (5 min)

O follow-up automático roda no processo do bot, a cada 30 minutos, com **quatro réguas**, cada uma com sua janela de silêncio e teto de tentativas:

| Régua | Dispara quando | Tentativas |
|---|---|---|
| Lead novo sem resposta | 2 horas sem resposta | até 3 |
| Qualificação interrompida | 6 horas sem resposta | até 3 |
| Depois de receber imóveis | 24 horas sem resposta | até 2 |
| Lembrete de visita | 24 horas antes da visita | até 2 |

Para não esperar horas, o painel dispara a mesma lógica na hora:

1. Escolha o lead. O do **Cenário 1** serve: está agendado e dispara o lembrete de visita — e, se veio pelo Telegram, é nele que a mensagem chega. Para ver a retomada de uma conversa interrompida, inicie uma conversa nova no simulador, mande duas mensagens e pare. O do Cenário 2 não serve: foi encaminhado ao corretor e saiu das réguas.
2. Use **Disparar follow-up** — na ficha, ou o ícone de envio na linha do lead.

**O que observar:**
- o andamento na linha do lead, e depois um aviso flutuante com **a mensagem que a Marina escreveu**, a régua e a tentativa;
- a mensagem **retoma o contexto da conversa**, não é um "oi, tudo bem?" genérico;
- **lead do Telegram:** a mensagem chega no Telegram em alguns segundos; responda e a conversa continua de onde parou;
- **lead do simulador:** não há para onde enviar — a mensagem fica registrada e aparece no chat dele, que se atualiza sozinho.

Dispare de novo no mesmo lead até esgotar a régua: o aviso passa a dizer que ela **esgotou as tentativas** — o teto existe para o follow-up não virar spam.

---

## 7. Dashboard (3 min)

Volte ao **Dashboard**.

**O que observar:**
- os cartões: total de leads, leads quentes, agendamentos, follow-ups gerados e inativos;
- a carteira por estágio do funil e por intenção;
- a tabela **Carteira**, ordenável por score — quem ligar primeiro;
- o painel **Consumo de LLM** (só `admin`): tempo médio de resposta e taxa de erro do provider hoje, e tokens e custo do dia e do mês contra o orçamento.

Entre como **`corretor1`**: o Simulador, o custo e as ferramentas somem do menu e das telas.

---

## 8. Qualidade e engenharia (5 min)

Com o Compose no ar, sem Python na máquina:

```bash
docker compose exec app pytest
```

```bash
docker compose exec app ruff check .
```

**O que observar:** 606 testes contra um PostgreSQL de verdade, em cerca de um minuto, incluindo os **três cenários do enunciado** como testes de ponta a ponta (`tests/test_cenarios.py`). Os mesmos rodam a cada push no [GitHub Actions](https://github.com/luizaaca/agente_imobiliario/actions/workflows/ci.yml).

| Para conferir | Leia |
|---|---|
| Como cada requisito do enunciado foi atendido | [Matriz de rastreabilidade](docs/05-engenharia/02-matriz-de-rastreabilidade.md) |
| Critérios de qualidade e aceite | [Qualidade e critérios](docs/01-visao-geral/02-qualidade-e-criterios.md) |
| Segurança do SQL gerado pelo agente | [Contratos das tools](docs/02-arquitetura/04-contratos-das-tools.md) |
| Tetos de custo de LLM | [Governança de custos](docs/03-operacao/04-governanca-de-custos-llm.md) |

---

## Onde cada item do enunciado aparece

| Do enunciado | Onde ver |
|---|---|
| Atender leads automaticamente | Cenário 1, pelo Telegram |
| Conversa humanizada | Cenários 1 e 2: apresentação como alguém da equipe, uma pergunta por vez, o que o cliente conta reaparece |
| Qualificar clientes e identificar intenção | aba **Ficha** e score, depois dos Cenários 1 e 2 |
| Coletar informações relevantes | aba **Ficha** e perfil narrativo, na aba **Resumo** |
| Follow-up automático | Cenário 3 |
| Agendar reuniões ou visitas | Cenário 1, último passo; aba **Agendamentos** |
| Base simulada de imóveis | 300 imóveis carregados pelo `migrate`; buscas dos Cenários 1 e 2 |
| Resumos para corretores | aba **Resumo** |
| Dashboard de acompanhamento | seção 7 |
| Memória conversacional e continuidade | Cenário 3: a conversa continua de onde parou |
| Multiagentes | seção 2; ferramentas e consultas na aba **Conversa** |
| Observabilidade | aba **Conversa**, custo no simulador, painel **Consumo de LLM** |
| Segurança | role somente-leitura do SQL gerado, tetos de custo, login com senha em hash, menus por papel |

**Não estão na POC**, e o README diz por quê: WhatsApp — o canal real é o Telegram, e trocar é um adaptador novo —, Voice AI, integração com CRM e deploy em nuvem. As demais limitações estão em [Limitações conhecidas](README.md#limitações-conhecidas).

---

## Se algo não sair como descrito

| Sintoma | Causa e saída |
|---|---|
| O chat diz "atendimento temporariamente indisponível" | falta `LLM_API_KEY` ou `LLM_MODEL` — a tela do chat diz qual —, ou o orçamento do dia acabou |
| O bot não responde no Telegram | `docker compose logs telegram-bot`. Sem token, o serviço sai dizendo isso; com `Conflict`, outro processo usa o mesmo token |
| A porta 5432 ou 8501 já está em uso | há outro PostgreSQL ou Streamlit na máquina — ver [Se algo der errado, no README](README.md#se-algo-der-errado) |
| A sessão caiu e pediu login de novo | o painel reiniciou sem `AUTH_COOKIE_KEY`; preencha-a para fixar a sessão |
| O follow-up diz "régua esgotada" | aquele lead já recebeu o máximo de tentativas; use outro lead |
| A aba **Resumo** está vazia | o resumo nasce quando o atendimento termina — visita marcada, desistência ou pedido de falar com o corretor |
