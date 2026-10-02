# Governança de Custos de LLM

**Objetivo:** definir limites, rastreamento e mecanismos de controle para manter o consumo de LLM previsível e auditável durante a POC.

---

## 1. O Problema

Cada interação com o agente SDR consome tokens de um provedor pago. Sem controle:
- Um lead curioso pode gerar dezenas de turnos longos, acumulando custo.
- O scheduler de follow-up pode disparar mensagens para muitos leads simultaneamente.
- Um pico inesperado pode gerar fatura alta.

**Meta:** Implementar controles que permitam operar a POC com custo previsível e evitar surpresas.

---

## 2. Referência de custos por provedor

| Modelo | Input (1M tokens) | Output (1M tokens) | Custo estimado por conversa (20 turnos) |
|---|---|---|---|
| `gpt-4o-mini` | $0.15 | $0.60 | ~$0.03-0.06 |
| `gpt-4o` | $2.50 | $10.00 | ~$0.20-0.60 |
| `gemini-2.5-flash` | $0.15 | $0.60 | ~$0.03-0.06 |
| `gemini-2.5-pro` | $1.25 | $10.00 | ~$0.16-0.50 |
| `claude-sonnet-4` | $3.00 | $15.00 | ~$0.30-0.80 |

> **Estimativa para a POC:** 100 conversas × 20 turnos com `gpt-4o-mini` ≈ **$3 a $6 total**, contando os turnos com busca, que custam o dobro de um turno de conversa simples.

---

## 3. Estratégia de controle em 3 camadas

### Camada 1: Limites por conversa

Evita que uma única conversa consuma tokens desproporcionalmente.

| Limite | Valor Padrão | Variável de Ambiente | Comportamento ao atingir |
|---|---|---|---|
| Máximo de turnos | 30 | `LLM_MAX_TURNS_PER_CONVERSATION` | Agente faz handover para corretor humano |
| Máximo de tokens acumulados | 400.000 | `LLM_MAX_TOKENS_PER_CONVERSATION` | Handover + gera resumo final automaticamente |

O teto em tokens acompanha o teto em turnos: 30 turnos em que a pessoa peça
busca com frequência passam de 400 mil tokens, e um teto mais baixo faria o
handover disparar por causa da qualidade da busca, e não por causa do tamanho
da conversa. Quem deve encerrar um atendimento longo é o limite de turnos, que
mede o que interessa.

**Mensagem de handover:**
> "Obrigado por todas as informações! Para dar continuidade com o melhor atendimento, vou direcionar você para um dos nossos corretores especialistas. Ele já terá todo o seu perfil e preferências. 😊"

**O que fica registrado.** O handover acrescenta ao perfil narrativo uma linha
dizendo que quem encerrou foi a trava, e não a pessoa, com a última mensagem
dela entre aspas. Sem isso o perfil termina na última coisa que ela disse antes
do estouro, e o corretor abre uma ficha inativa sem saber por quê — inclusive
quando a pessoa tinha acabado de escrever que não ia seguir.

A linha é emendada sem passar pelo consolidador: chega-se aqui porque o
orçamento de tokens da conversa acabou, e gastar mais uma chamada de LLM para
registrar que não há mais orçamento seria a contradição em pessoa. O resumo
executivo é gerado depois dela, e por isso já sai sabendo como a conversa
terminou.

### Camada 2: Limites globais (por período)

Evita que o custo total saia do controle.

| Limite | Valor Padrão | Variável de Ambiente | Comportamento ao atingir |
|---|---|---|---|
| Budget diário (tokens) | 1.500.000 | `LLM_DAILY_TOKEN_BUDGET` | Alerta no dashboard + mensagem de indisponibilidade em qualquer turno, inclusive nas conversas já em andamento |
| Budget mensal (tokens) | 10.000.000 | `LLM_MONTHLY_TOKEN_BUDGET` | Alerta no dashboard + mensagem de indisponibilidade em qualquer turno |

O teto vale para todo turno, e não só para conversas novas: um limite que só
barra quem chega deixa o custo depender de quantas conversas estavam abertas
no momento em que ele estourou. O ciclo de follow-up checa o mesmo teto antes
de começar a gerar mensagens.

O dashboard avisa a partir de 80% do teto, em tokens e em turnos de conversa
restantes. O degrau existe porque o bloqueio é abrupto: quem está conversando
recebe o aviso de indisponibilidade no meio do atendimento, sem que ninguém
tenha visto o limite chegar. Quando ele age, a conversa guarda um
`system_notice` com o motivo — senão o histórico fica com a pergunta da pessoa
e nada depois, o que se lê como um agente que parou de funcionar.

### Quanto custa um turno

A base reenviada em toda requisição — instruções, schemas das tools e histórico
— dá cerca de 4.000 tokens, dos quais aproximadamente 2.000 são os schemas das
oito ferramentas. Um turno é no mínimo uma requisição; com tool, são três
(pedido, resultado da tool, resposta), cada uma carregando a base inteira.

Um turno de conversa simples fica perto de 4 mil tokens. Um turno com busca
soma a isso o agente de busca, que roda de uma a três requisições com prompt
próprio e as linhas que ele leu do catálogo: cerca de 185 caracteres por imóvel,
o que põe 50 imóveis em torno de 2.300 tokens. Na prática, **15 a 20 mil tokens
por turno com busca**.

O teto do que o agente de busca pode ler é conhecido: o catálogo inteiro, 286
imóveis disponíveis em linha compacta, são cerca de 13 mil tokens. A
investigação dele é cara mas limitada, e o que chega ao histórico da conversa é
só a seleção final.

Um parâmetro de texto livre no lugar de um contrato de filtros é o que mantém a
conta nesse patamar. Uma tool de busca com dezenove filtros tipados e descrições
úteis ocupa sozinha cerca de 1.300 tokens de schema — reenviados em toda
requisição de todo turno, inclusive nos turnos em que ninguém busca nada.

**Mensagem de indisponibilidade:**
> "Nosso atendimento digital está temporariamente indisponível. Um corretor entrará em contato em breve pelo número cadastrado."

### Camada 3: Tracking e observabilidade

Registrar cada chamada para auditoria, otimização e exibição no dashboard.

---

## 4. Modelagem da tabela `llm_usage`

```python
# src/db/models.py
class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leads.id"), nullable=True)
    conversation_turn: Mapped[Optional[int]] = mapped_column(nullable=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    tokens_input: Mapped[int] = mapped_column(nullable=False)
    tokens_output: Mapped[int] = mapped_column(nullable=False)
    tokens_total: Mapped[int] = mapped_column(nullable=False)
    estimated_cost_usd: Mapped[Optional[float]] = mapped_column(Numeric(12, 6), nullable=True)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ok")
    error_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
```

`lead_id` é anulável porque excluir um lead não apaga o consumo dele: a linha
perde o vínculo e continua contando nos tetos diário e mensal. Os três totais
de token têm `CHECK >= 0`.

### Valores de `operation`

| Valor | Quando é gravado | Conta como turno? |
|---|---|---|
| `chat` | resposta conversacional ao lead, em qualquer canal | sim |
| `followup` | mensagem de follow-up, automática ou disparada pelo corretor | não |
| `perfil` | consolidação do perfil narrativo, pelo agente dedicado | não |
| `busca` | investigação do catálogo, pelo agente de busca | não |

São as quatro chamadas ao provider que existem. O resumo do corretor é montado
por template a partir do que já está no banco, e não chama LLM.

A coluna da direita separa duas contas diferentes. **Todos** os tokens do lead
entram no orçamento dele, que é o que dispara o handover por
`LLM_MAX_TOKENS_PER_CONVERSATION`. Mas só `chat` conta como **turno**: os
agentes auxiliares trabalham dentro de um turno, não no lugar dele, e contá-los
empurraria a pessoa para o corretor humano mais cedo a cada busca que ela
pedisse.

Separar `busca` de `chat` é o que torna a recuperação de imóveis mensurável. O
consumo do agente de busca **não** é propagado para o run principal: se fosse,
entraria no `usage` do turno e seria gravado como `chat`, misturando o custo de
buscar com o de conversar.

### Status de cada chamada

A tabela é o livro-caixa de **toda** chamada ao provider, não só das que
consumiram token. Uma chamada que falhou entra com `status='erro'`,
`error_type` e zero token: sem essa linha, a taxa de erro do dashboard seria
sempre zero, já que a falha existiria apenas no log. A contagem de turnos da
conversa ignora as falhas — uma instabilidade nossa não pode empurrar o lead
para o handover por limite.

`latency_ms` guarda o tempo da chamada ao provider, e é a base do tempo médio
de resposta exibido no painel.

---

## 5. Serviço de controle de custos

`src/services/llm_usage_service.py`. Todo método recebe a sessão do banco
(`db`) de quem chama, e nenhum é assíncrono.

**Preço.** `PRICING` é a tabela de USD por milhão de tokens, de entrada e de
saída, para os modelos conhecidos (`gpt-4o-mini`, `gpt-4o`,
`gemini-2.5-flash`, `gemini-2.5-pro`, `claude-sonnet-4`). Modelo fora dela usa
`FALLBACK_PRICING` (1,00 / 3,00) e registra `event=preco_desconhecido` no log,
para o custo não parecer mais preciso do que é.

| Método | Para quê |
|---|---|
| `estimate_cost(model, tokens_in, tokens_out)` | custo estimado de uma chamada, em USD |
| `record(lead_id, model, tokens_in, tokens_out, operation, db, turn, latency_ms)` | grava uma chamada bem-sucedida, com o custo já calculado |
| `record_failure(lead_id, model, operation, error_type, latency_ms, db)` | grava uma chamada que falhou, com zero token e `status='erro'` |
| `get_conversation_tokens(lead_id, db)` | total de tokens do lead, de todas as operações |
| `get_conversation_cost(lead_id, db)` | custo estimado do lead, de todas as operações |
| `get_conversation_turns(lead_id, db)` | turnos de `chat` bem-sucedidos do lead |
| `is_conversation_over_limit(lead_id, db)` | tokens ou turnos da conversa no teto |
| `get_daily_tokens` / `get_monthly_tokens` | consumo do dia e do mês |
| `is_daily_budget_exceeded` / `is_monthly_budget_exceeded` | tetos globais atingidos |
| `get_daily_cost` / `get_monthly_cost` | custo estimado do dia e do mês |
| `get_daily_latency_ms` / `get_daily_error_rate` | saúde do agente no dia; `None` quando não houve chamada |
| `get_dashboard_summary(db)` | tudo o que o painel de consumo mostra, numa chamada |

---

## 6. Integração com o agente

Em `process_message` (`src/agent/sdr_agent.py`), antes de chamar o modelo:

1. o histórico é reidratado e a fala recebida é gravada;
2. teto **diário** ou **mensal** atingido: o turno é registrado como bloqueado
   e a pessoa recebe a mensagem de atendimento indisponível;
3. teto **da conversa** atingido: o handover é registrado uma vez só — nota
   no perfil narrativo, resumo executivo gerado, lead em `inativo` — e a
   pessoa recebe a mensagem de handover.

Depois da chamada:

- sucesso: `record(..., operation="chat", turn=<turnos até aqui + 1>, latency_ms=...)`;
- falha do provider: `record_failure(..., operation="chat", ...)`, e a pessoa
  recebe a mensagem de indisponibilidade.

Os agentes auxiliares registram o próprio consumo com a operação deles:
`busca` na tool de busca, `perfil` no consolidador, `followup` no runner de
follow-up.

---

## 7. Exibição no dashboard

O dashboard lê `LLMUsageService().get_dashboard_summary(db)` e mostra o
painel **Consumo de LLM** num expander, só para o `admin`.

O alerta de estouro fica **fora** do expander, na página: dentro de um painel
fechado ele não existe na prática, e quem abrisse o dashboard com o orçamento
esgotado veria uma tela normal, descobrindo o bloqueio só quando o chat
parasse de responder.

Dentro do expander, por período (hoje e mês): tokens consumidos, barra de
progresso contra o teto e custo estimado. No topo dele, a saúde do agente no
dia: **tempo médio de resposta** e **taxa de erro**. Os dois aparecem como
`—`, e não como zero, enquanto não houve chamada nenhuma — zero afirmaria que
está tudo bem quando nada foi exercitado.

---

## 7.1 Custo por conversa

O dashboard responde "quanto a aplicação gastou hoje". Quem olha um lead tem
outra pergunta: **quanto custou esta conversa**. A resposta aparece na aba
**Conversa** da ficha do lead e no cabeçalho do simulador, numa linha:

```
148.584 / 400.000 tokens · US$ 0.1585 estimados
```

O numerador soma tudo que o lead consumiu — turnos de chat, idas do agente de
busca ao catálogo e consolidação do perfil. Quem olha uma conversa quer saber
o que ela custou, e não o que cada agente custou dentro dela.

O denominador é `LLM_MAX_TOKENS_PER_CONVERSATION`, o teto que entrega o
atendimento ao corretor no instante em que é atingido. Sem ele, o número diria
quanto se gastou sem dizer o quanto falta, e o handover chegaria sem aviso.

A linha é do `admin`. Para o corretor, `custo_da_conversa` devolve vazio antes
de consultar o banco: a tela dele não paga consulta por um número que não vai
mostrar. Na mesma aba, e pelo mesmo critério, os painéis com o SQL do agente de
busca e o retorno cru de cada ferramenta também só existem para o `admin` —
veja [papéis e o que cada um enxerga](03-autenticacao-da-ui.md#5-papéis-e-o-que-cada-um-enxerga).

---

## 8. Variáveis de ambiente

```env
# Limites por conversa
LLM_MAX_TURNS_PER_CONVERSATION=30
LLM_MAX_TOKENS_PER_CONVERSATION=400000

# Limites globais
LLM_DAILY_TOKEN_BUDGET=1500000
LLM_MONTHLY_TOKEN_BUDGET=10000000

# Modelo do agente de busca. Vazio usa LLM_MODEL.
LLM_MODEL_BUSCA=
```

### `LLM_MODEL_BUSCA`

O agente de busca roda de uma a três requisições **dentro** da chamada da tool,
antes de a pessoa ver qualquer coisa. Essa latência se soma à do turno, e num
canal de mensagem ela é percebida.

A variável existe para poder trocar esse agente por um modelo mais rápido sem
tocar no modelo da conversa, onde a qualidade do texto é o que importa. Vazia,
os dois usam `LLM_MODEL` — que é o padrão, porque a decisão de qual imóvel
mostrar é tão sensível quanto a de como falar dele.

---

## 8.1 Configuração ausente

`LLM_MODEL` e `LLM_API_KEY` não têm valor padrão, e `LLM_BASE_URL` é obrigatória no provider `custom`. A checagem vive em um lugar só, `provider.configuracao_ausente()`, usada tanto pela UI quanto por `_construir_modelo`, para que as duas não divirjam.

Faltando qualquer uma delas, a aplicação sobe normalmente: dashboard e catálogo funcionam, e a aba do chat nomeia as variáveis ausentes e **desabilita o campo de mensagem**, em vez de deixar o usuário escrever para receber apenas "atendimento indisponível".

A mensagem na tela cita só os nomes das variáveis, nunca `.env` ou `docker compose`: a forma de defini-las depende de onde a aplicação está rodando — arquivo, shell ou secrets de pipeline — e o "como" está centralizado na seção **Configuração** do README.

---

## 9. Checklist de implementação

- [x] Criar modelo `LLMUsage` em `src/db/models.py`.
- [x] Criar `src/services/llm_usage_service.py` com as funções de tracking e verificação.
- [x] Definir tabela de preços por modelo em `src/config.py`.
  > Fica em `LLMUsageService.PRICING`, junto de quem a usa.
- [x] Integrar checagem de limites no loop do agente (antes de chamar LLM).
- [x] Integrar `record()` após cada chamada ao agente (usando `result.usage`).
  > Em pydantic-ai 2.x `usage` é property, não método.
- [x] Aplicar mesma lógica no scheduler de follow-up.
- [x] Adicionar variáveis de ambiente ao `.env.example`.
- [x] Adicionar card de consumo no dashboard Streamlit.
- [x] Testar: conversa atinge 30 turnos → mensagem de handover.
- [x] Testar: budget diário esgotado → novas conversas recebem mensagem de indisponibilidade.
