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
| `gpt-4o-mini` | $0.15 | $0.60 | ~$0.01-0.03 |
| `gpt-4o` | $2.50 | $10.00 | ~$0.10-0.30 |
| `gemini-2.5-flash` | $0.15 | $0.60 | ~$0.01-0.03 |
| `gemini-2.5-pro` | $1.25 | $10.00 | ~$0.08-0.25 |
| `claude-sonnet-4` | $3.00 | $15.00 | ~$0.15-0.40 |

> **Estimativa para a POC:** 100 conversas × 20 turnos com `gpt-4o-mini` ≈ **$1 a $3 total**.

---

## 3. Estratégia de controle em 3 camadas

### Camada 1: Limites por conversa

Evita que uma única conversa consuma tokens desproporcionalmente.

| Limite | Valor Padrão | Variável de Ambiente | Comportamento ao atingir |
|---|---|---|---|
| Máximo de turnos | 30 | `LLM_MAX_TURNS_PER_CONVERSATION` | Agente faz handover para corretor humano |
| Máximo de tokens acumulados | 150.000 | `LLM_MAX_TOKENS_PER_CONVERSATION` | Handover + gera resumo final automaticamente |

**Mensagem de handover:**
> "Obrigado por todas as informações! Para dar continuidade com o melhor atendimento, vou direcionar você para um dos nossos corretores especialistas. Ele já terá todo o seu perfil e preferências. 😊"

### Camada 2: Limites globais (por período)

Evita que o custo total saia do controle.

| Limite | Valor Padrão | Variável de Ambiente | Comportamento ao atingir |
|---|---|---|---|
| Budget diário (tokens) | 500.000 | `LLM_DAILY_TOKEN_BUDGET` | Alerta no dashboard + mensagem de indisponibilidade em qualquer turno, inclusive nas conversas já em andamento |
| Budget mensal (tokens) | 3.000.000 | `LLM_MONTHLY_TOKEN_BUDGET` | Alerta no dashboard + mensagem de indisponibilidade em qualquer turno |

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
Medido nas conversas reais: a base reenviada em toda requisição (instruções,
schemas das tools e histórico) dá cerca de 5.100 tokens, e um turno em que o
agente busca imóveis são três requisições — pedido, resultado da tool, resposta
—, cada uma carregando a base inteira. Na prática, 10 a 15 mil tokens por turno
com busca, e cerca de 5 mil num turno de conversa simples.

**Mensagem de indisponibilidade:**
> "Nosso atendimento digital está temporariamente indisponível. Um corretor entrará em contato em breve pelo número cadastrado."

### Camada 3: Tracking e observabilidade

Registrar cada chamada para auditoria, otimização e exibição no dashboard.

---

## 4. Modelagem da tabela `llm_usage`

```python
# src/db/models.py (adicionar ao modelo existente)

class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)  # nullable para operações sem lead (ex: resumo batch)
    conversation_turn = Column(Integer, nullable=True)
    model = Column(String, nullable=False)
    tokens_input = Column(Integer, nullable=False)
    tokens_output = Column(Integer, nullable=False)
    tokens_total = Column(Integer, nullable=False)
    estimated_cost_usd = Column(Float, nullable=True)
    operation = Column(String, nullable=False)  # chat, followup, resumo, busca
    created_at = Column(DateTime, server_default=func.now())
```

### Valores de `operation`

| Valor | Quando é gravado |
|---|---|
| `chat` | resposta conversacional ao lead, em qualquer canal |
| `followup` | mensagem de follow-up, automática ou disparada pelo corretor |

São os dois únicos, porque são as duas únicas chamadas ao provider que
existem. O resumo do corretor é montado por template a partir do que já está
no banco, o perfil narrativo é escrito pelo próprio turno de chat via tool, e
o ranking da busca é do PostgreSQL — nenhum dos três chama LLM por fora.

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

```python
# src/services/llm_usage_service.py (conceitual)

from src.config import settings

# Tabela de preços por modelo (USD por 1M tokens)
PRICING = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}

class LLMUsageService:
    def __init__(self, db_session):
        self.db = db_session

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Calcula custo estimado em USD."""
        prices = PRICING.get(model, {"input": 1.0, "output": 3.0})  # fallback conservador
        cost = (tokens_in / 1_000_000) * prices["input"] + (tokens_out / 1_000_000) * prices["output"]
        return round(cost, 6)

    async def record(self, lead_id: int, model: str, tokens_in: int, tokens_out: int, operation: str, turn: int = None):
        """Registra uso no banco."""
        usage = LLMUsage(
            lead_id=lead_id,
            conversation_turn=turn,
            model=model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            tokens_total=tokens_in + tokens_out,
            estimated_cost_usd=self.estimate_cost(model, tokens_in, tokens_out),
            operation=operation,
        )
        self.db.add(usage)
        self.db.commit()

    async def get_conversation_tokens(self, lead_id: int) -> int:
        """Total de tokens consumidos por uma conversa."""
        return self.db.query(func.sum(LLMUsage.tokens_total)).filter(
            LLMUsage.lead_id == lead_id
        ).scalar() or 0

    async def get_conversation_turns(self, lead_id: int) -> int:
        """Total de turnos de chat de uma conversa."""
        return self.db.query(func.count(LLMUsage.id)).filter(
            LLMUsage.lead_id == lead_id,
            LLMUsage.operation == "chat",
        ).scalar() or 0

    async def get_daily_tokens(self) -> int:
        """Total de tokens consumidos hoje."""
        today = datetime.utcnow().date()
        return self.db.query(func.sum(LLMUsage.tokens_total)).filter(
            func.date(LLMUsage.created_at) == today
        ).scalar() or 0

    async def get_monthly_tokens(self) -> int:
        """Total de tokens consumidos no mês atual."""
        now = datetime.utcnow()
        return self.db.query(func.sum(LLMUsage.tokens_total)).filter(
            func.extract("year", LLMUsage.created_at) == now.year,
            func.extract("month", LLMUsage.created_at) == now.month,
        ).scalar() or 0

    async def is_conversation_over_limit(self, lead_id: int) -> bool:
        """Verifica se a conversa excedeu os limites."""
        tokens = await self.get_conversation_tokens(lead_id)
        turns = await self.get_conversation_turns(lead_id)
        return (
            tokens >= settings.LLM_MAX_TOKENS_PER_CONVERSATION or
            turns >= settings.LLM_MAX_TURNS_PER_CONVERSATION
        )

    async def is_daily_budget_exceeded(self) -> bool:
        """Verifica se o budget diário foi excedido."""
        return await self.get_daily_tokens() >= settings.LLM_DAILY_TOKEN_BUDGET

    async def is_monthly_budget_exceeded(self) -> bool:
        """Verifica se o budget mensal foi excedido."""
        return await self.get_monthly_tokens() >= settings.LLM_MONTHLY_TOKEN_BUDGET

    async def get_dashboard_summary(self) -> dict:
        """Dados para exibição no dashboard."""
        return {
            "daily_tokens": await self.get_daily_tokens(),
            "daily_budget": settings.LLM_DAILY_TOKEN_BUDGET,
            "monthly_tokens": await self.get_monthly_tokens(),
            "monthly_budget": settings.LLM_MONTHLY_TOKEN_BUDGET,
            "daily_cost_usd": self._sum_cost_today(),
            "monthly_cost_usd": self._sum_cost_month(),
        }
```

---

## 6. Integração com o agente (PydanticAI)

```python
# src/agent/sdr_agent.py (trecho conceitual)

async def process_message(lead_id: int, user_text: str, deps: dict) -> str:
    usage_service = deps["llm_usage_service"]

    # 1. Checar limites ANTES de chamar a LLM
    if await usage_service.is_daily_budget_exceeded():
        logger.warning("Budget diário de LLM atingido!")
        return MENSAGEM_INDISPONIVEL

    if await usage_service.is_conversation_over_limit(lead_id):
        logger.info(f"Lead {lead_id} atingiu limite de conversa. Fazendo handover.")
        # Gera resumo final e retorna mensagem de handover
        await registrar_handover(lead_id)  # gera o resumo e marca o lead como inativo
        return MENSAGEM_HANDOVER

    # 2. Executar o agente
    result = await sdr_agent.run(user_prompt=user_text, deps=deps)

    # 3. Registrar uso DEPOIS da chamada
    usage = result.usage()
    await usage_service.record(
        lead_id=lead_id,
        model=settings.LLM_MODEL,
        tokens_in=usage.request_tokens,
        tokens_out=usage.response_tokens,
        operation="chat",
        turn=await usage_service.get_conversation_turns(lead_id) + 1,
    )

    return result.data
```

---

## 7. Exibição no dashboard

Adicionar uma seção/card no dashboard do corretor:

```python
# src/ui/dashboard.py (trecho conceitual)

resumo = LLMUsageService().get_dashboard_summary(db)
```

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

## 8. Variáveis de ambiente

```env
# Limites por conversa
LLM_MAX_TURNS_PER_CONVERSATION=30
LLM_MAX_TOKENS_PER_CONVERSATION=150000

# Limites globais
LLM_DAILY_TOKEN_BUDGET=500000
LLM_MONTHLY_TOKEN_BUDGET=3000000
```

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
