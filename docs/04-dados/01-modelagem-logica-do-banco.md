# Modelagem Lógica do Banco

**Objetivo:** consolidar em um único documento a visão conceitual das entidades da POC e a modelagem lógica de persistência, incluindo tipos SQL, nulabilidade, constraints, índices, identidade de canal, histórico de mensagens, tentativas de follow-up, score e status.

---

## 1. Visão conceitual das entidades

### 1.1 Entidades principais

#### Lead
- `id`
- `nome`
- `telefone`
- `status`
- `intencao`
- `tipologia_interesse`
- `orcamento_min`
- `orcamento_max`
- `forma_pagamento`
- `regiao_interesse`
- `bairro_interesse`
- `quartos`
- `urgencia`
- `motivo_busca`
- `perfil`
- `canal_origem`
- `amenidades_desejadas`
- `score`
- `perfil_narrativo`
- `resumo`
- `created_at`
- `updated_at`

#### Mensagem
- `id`
- `lead_id`
- `channel`
- `channel_identity_id`
- `role`
- `message_type`
- `content`
- `status`
- `external_message_id`
- `in_reply_to_message_id`
- `metadata_json`
- `timestamp`
- `sent_at`

#### Agendamento
- `id`
- `lead_id`
- `tipo`
- `data_hora`
- `observacoes`
- `status`

#### Imóvel
- `id`
- `titulo`
- `tipo`
- `finalidade`
- `bairro`
- `zona`
- `preco`
- `quartos`
- `area_m2`
- `vaga_garagem`
- `descricao`
- `tags`
- `perfil_indicado`

#### LLMUsage
- `id`
- `lead_id`
- `conversation_turn`
- `model`
- `tokens_input`
- `tokens_output`
- `tokens_total`
- `estimated_cost_usd`
- `operation`
- `created_at`

#### LeadChannelIdentity
- `id`
- `lead_id`
- `channel`
- `external_user_id`
- `external_chat_id`
- `is_primary`
- `created_at`
- `last_seen_at`

#### FollowUpAttempt
- `id`
- `lead_id`
- `message_id`
- `regua`
- `attempt_number`
- `status`
- `failure_reason`
- `scheduled_for`
- `executed_at`
- `created_at`

### 1.2 Enums recomendados
- `LeadStatus`: `novo`, `em_qualificacao`, `qualificado`, `agendado`, `inativo`
- `LeadIntent`: `compra`, `aluguel`, `investimento`
- `Urgencia`: `baixa`, `media`, `alta`

---

## 2. O campo `perfil_narrativo`: o produto principal do SDR

Inspirado nas práticas das principais ferramentas de mercado (Lais.ai, Maya/Plaza, Squad/Inner AI), o schema do Lead inclui um campo textual narrativo **escrito e mantido pela LLM** ao longo da conversa.

**O que é:** Um texto estruturado em blocos semânticos que acumula tudo que se sabe sobre o lead — incluindo nuances que campos estruturados não capturam: objeções ("achou a cozinha do AP-007 pequena"), preferências implícitas, imóveis rejeitados com motivo, contexto de vida e próximos passos sugeridos.

### Exemplo ilustrativo

```text
## Perfil do Lead: Maria Santos
Atualizado em: 2026-09-08 15:32

### Contexto e Motivação
Casada, dois filhos (8 e 12 anos). Mora de aluguel no Butantã.
Contrato vence em dezembro — quer comprar para não renovar.
Marido trabalha remoto, ela presencial na Faria Lima.

### Preferências Declaradas
- Apartamento 3 dormitórios (1 suíte), preferencialmente com varanda
- Bairros: Pinheiros, Vila Madalena ou Perdizes (aceita Pompeia)
- 2 vagas de garagem (têm 2 carros)
- Pet-friendly obrigatório (golden retriever)

### Capacidade Financeira
- Orçamento: R$ 800k a R$ 1.100k
- Financiamento bancário (pré-aprovação Itaú ~R$ 750k)
- Entrada: R$ 200k + FGTS do marido (~R$ 80k)

### Restrições e Objeções
- Não quer térreo (segurança e cachorro)
- Rejeitou AP-007 (Vila Madalena, R$ 920k): cozinha muito pequena
- Teto de condomínio: R$ 1.200/mês

### Imóveis de Interesse
- AP-003 (Pinheiros, 3q, R$ 980k): gostou, visita agendada ✅
- AP-011 (Perdizes, 3q, R$ 870k): quer ver fotos da varanda

### Urgência
- Alta: precisa resolver até nov/2026
```

### Distinção entre `perfil_narrativo` e `resumo`

| Aspecto | `perfil_narrativo` | `resumo` |
|---|---|---|
| **Quando é gerado** | Progressivamente, a cada interação significativa | No final da qualificação ou sob demanda |
| **Quem consome** | O próprio agente (como contexto) + corretor | O corretor como briefing executivo |
| **Tamanho típico** | Médio-longo (300-800 palavras) | Curto-médio (100-300 palavras) |
| **Conteúdo** | Tudo que se sabe, com nuances e objeções | Síntese: perfil, score, recomendação e próximos passos |
| **Atualização** | Contínua (incremental) | Pontual (snapshot) |

---

## 3. Decisões-base da modelagem lógica

### 3.1 Identificadores
- Usar `BIGSERIAL` para chaves primárias.
- Usar `BIGINT` para chaves estrangeiras.

### 3.2 Datas e horários
- Usar `TIMESTAMP WITH TIME ZONE` em todos os campos temporais persistidos.
- Usar `DEFAULT now()` quando fizer sentido para criação automática.

### 3.3 Valores monetários
- Usar `NUMERIC(12,2)` para valores financeiros.

### 3.4 Score
- Usar `NUMERIC(4,2)` para permitir granularidade sem exagero.
- Faixa válida da POC: $0 \leq score \leq 10$.

### 3.5 Campos categóricos
- Para a POC, usar `VARCHAR` + `CHECK`, em vez de enums nativos do PostgreSQL.
- Motivo: simplifica migrations e reduz atrito de evolução durante o hackathon.

### 3.6 Texto longo
- Usar `TEXT` para conteúdo narrativo, mensagens, observações e resumos.

---

## 4. Tabela `leads`

### 2.1 Finalidade
Representa o lead e seu estado consolidado de qualificação.

### 2.2 Colunas propostas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `nome` | `VARCHAR(120)` | Sim |  | Nome do lead |
| `telefone` | `VARCHAR(30)` | Sim |  | Telefone ou identificador equivalente |
| `status` | `VARCHAR(30)` | Não |  | Ex.: `novo`, `em_qualificacao`, `qualificado`, `agendado`, `inativo` |
| `intencao` | `VARCHAR(30)` | Sim |  | Ex.: `compra`, `aluguel`, `investimento` |
| `tipologia_interesse` | `VARCHAR(30)` | Sim |  | Ex.: `apto`, `casa`, `studio` |
| `orcamento_min` | `NUMERIC(12,2)` | Sim |  | Valor mínimo |
| `orcamento_max` | `NUMERIC(12,2)` | Sim |  | Valor máximo |
| `forma_pagamento` | `VARCHAR(30)` | Sim |  | Ex.: `avista`, `financiamento`, `fgts`, `permuta` |
| `regiao_interesse` | `VARCHAR(80)` | Sim |  | Região macro |
| `bairro_interesse` | `VARCHAR(80)` | Sim |  | Bairro principal |
| `quartos` | `SMALLINT` | Sim |  | Quantidade desejada |
| `urgencia` | `VARCHAR(20)` | Sim |  | Ex.: `baixa`, `media`, `alta` |
| `motivo_busca` | `VARCHAR(120)` | Sim |  | Motivação principal |
| `perfil` | `VARCHAR(30)` | Sim |  | Ex.: `residencial`, `investidor` |
| `canal_origem` | `VARCHAR(30)` | Sim |  | Ex.: `telegram`, `streamlit`, `portal` |
| `amenidades_desejadas` | `TEXT` | Sim |  | Lista textual ou serialização simples |
| `score` | `NUMERIC(4,2)` | Sim |  | Faixa 0–10 |
| `perfil_narrativo` | `TEXT` | Sim |  | Artefato principal do SDR |
| `resumo` | `TEXT` | Sim |  | Briefing executivo |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |
| `updated_at` | `TIMESTAMPTZ` | Não | `now()` | Última atualização |

### 2.3 Constraints recomendadas

```sql
CHECK (orcamento_min IS NULL OR orcamento_min >= 0)
CHECK (orcamento_max IS NULL OR orcamento_max >= 0)
CHECK (orcamento_min IS NULL OR orcamento_max IS NULL OR orcamento_min <= orcamento_max)
CHECK (quartos IS NULL OR quartos >= 0)
CHECK (score IS NULL OR (score >= 0 AND score <= 10))
CHECK (status IN ('novo', 'em_qualificacao', 'qualificado', 'agendado', 'inativo'))
CHECK (intencao IS NULL OR intencao IN ('compra', 'aluguel', 'investimento'))
CHECK (urgencia IS NULL OR urgencia IN ('baixa', 'media', 'alta'))
```

### 2.4 Índices recomendados

```sql
CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_leads_intencao ON leads(intencao);
CREATE INDEX idx_leads_score ON leads(score);
CREATE INDEX idx_leads_created_at ON leads(created_at);
CREATE INDEX idx_leads_status_score ON leads(status, score DESC);
CREATE INDEX idx_leads_bairro_interesse ON leads(bairro_interesse);
```

### 2.5 Observações
- `telefone` não deve ser `UNIQUE` nesta etapa, pois o identificador de canal ainda será tratado em lacuna específica.
- `updated_at` deverá ser atualizado pela camada de aplicação ou por mecanismo automático futuro.

---

## 3. Tabela `mensagens`

### 3.1 Finalidade
Persistir o histórico de mensagens associado a um lead, com rastreabilidade mínima de canal e estado operacional.

### 3.2 Decisão desta etapa
Nesta etapa, a tabela `mensagens` deixa de ser apenas um histórico textual mínimo e passa a incorporar metadados suficientes para:

- distinguir origem/canal da mensagem;
- rastrear mensagens recebidas, geradas e enviadas;
- suportar Telegram, Streamlit e follow-up automático;
- manter a modelagem simples, sem exigir ainda uma entidade explícita de `conversation` / `session`.

### 3.3 Colunas propostas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Não |  | FK para `leads.id` |
| `channel` | `VARCHAR(30)` | Não |  | Ex.: `telegram`, `streamlit`, `followup_system` |
| `channel_identity_id` | `BIGINT` | Sim |  | FK futura para identidade de canal; opcional nesta fase |
| `role` | `VARCHAR(20)` | Não |  | `user`, `assistant`, `system`, `tool` |
| `message_type` | `VARCHAR(30)` | Não |  | Ex.: `chat`, `followup`, `system_notice`, `handover` |
| `content` | `TEXT` | Não |  | Conteúdo textual da mensagem |
| `status` | `VARCHAR(20)` | Não | `'created'` | Ex.: `received`, `generated`, `sent`, `failed` |
| `external_message_id` | `VARCHAR(100)` | Sim |  | ID externo do canal, quando existir |
| `in_reply_to_message_id` | `BIGINT` | Sim |  | Auto-relacionamento opcional para encadeamento simples |
| `metadata_json` | `JSONB` | Sim |  | Metadados leves do canal/operação |
| `timestamp` | `TIMESTAMPTZ` | Não | `now()` | Momento principal do registro |
| `sent_at` | `TIMESTAMPTZ` | Sim |  | Momento efetivo de envio, quando aplicável |

### 3.4 Constraints recomendadas

```sql
CHECK (role IN ('user', 'assistant', 'system', 'tool'))
CHECK (message_type IN ('chat', 'followup', 'system_notice', 'handover'))
CHECK (status IN ('created', 'received', 'generated', 'sent', 'failed'))
CHECK (length(trim(content)) > 0)
```

### 3.5 Chaves estrangeiras

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
FOREIGN KEY (in_reply_to_message_id) REFERENCES mensagens(id)
```

> `channel_identity_id` será formalizado quando a lacuna de identidade de canal for fechada.

### 3.6 Índices recomendados

```sql
CREATE INDEX idx_mensagens_lead_id ON mensagens(lead_id);
CREATE INDEX idx_mensagens_channel ON mensagens(channel);
CREATE INDEX idx_mensagens_status ON mensagens(status);
CREATE INDEX idx_mensagens_message_type ON mensagens(message_type);
CREATE INDEX idx_mensagens_timestamp ON mensagens(timestamp);
CREATE INDEX idx_mensagens_lead_timestamp ON mensagens(lead_id, timestamp);
CREATE INDEX idx_mensagens_external_message_id ON mensagens(external_message_id);
```

### 3.7 Justificativa dos novos campos

#### `channel`
Permite distinguir a origem da mensagem sem depender apenas do `canal_origem` do lead.

#### `channel_identity_id`
Prepara a tabela para a futura entidade de identidade de canal, sem obrigar sua implementação imediata.

#### `message_type`
Evita sobrecarregar `role` com semânticas de negócio. Exemplo:
- `role='assistant'` + `message_type='followup'`
- `role='assistant'` + `message_type='chat'`

#### `status`
Permite rastrear o ciclo operacional da mensagem, especialmente em Telegram e follow-up.

#### `external_message_id`
Permite correlação com o canal externo quando houver ID nativo da mensagem.

#### `in_reply_to_message_id`
Permite encadeamento simples entre mensagens sem exigir ainda uma entidade `conversation`.

#### `metadata_json`
Permite guardar metadados leves sem explodir o schema cedo demais.

### 3.8 Observações
- Ainda não estamos introduzindo uma entidade explícita de `conversation` / `session`.
- O histórico continua sendo persistido por `lead_id`, com rastreabilidade de canal.
- A política de `ON DELETE` continua adiada para a etapa de retenção e identidade de canal.

---

## 4. Tabela `agendamentos`

### 4.1 Finalidade
Persistir visitas e reuniões associadas a um lead.

### 4.2 Colunas propostas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Não |  | FK para `leads.id` |
| `tipo` | `VARCHAR(20)` | Não |  | `visita` ou `reuniao` |
| `data_hora` | `TIMESTAMPTZ` | Não |  | Data/hora do compromisso |
| `observacoes` | `TEXT` | Sim |  | Observações livres |
| `status` | `VARCHAR(20)` | Não |  | `pendente`, `confirmado`, `cancelado`, `realizado` |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |

### 4.3 Constraints recomendadas

```sql
CHECK (tipo IN ('visita', 'reuniao'))
CHECK (status IN ('pendente', 'confirmado', 'cancelado', 'realizado'))
```

### 4.4 Chave estrangeira

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
```

### 4.5 Índices recomendados

```sql
CREATE INDEX idx_agendamentos_lead_id ON agendamentos(lead_id);
CREATE INDEX idx_agendamentos_data_hora ON agendamentos(data_hora);
CREATE INDEX idx_agendamentos_status_data_hora ON agendamentos(status, data_hora);
```

---

## 5. Tabela `llm_usage`

### 5.1 Finalidade
Registrar consumo de LLM para auditoria, controle de custo e métricas operacionais.

### 5.2 Colunas propostas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Sim |  | FK para `leads.id`; pode ser nulo em operações sem lead |
| `conversation_turn` | `INTEGER` | Sim |  | Turno da conversa, quando aplicável |
| `model` | `VARCHAR(80)` | Não |  | Nome do modelo |
| `tokens_input` | `INTEGER` | Não |  | Tokens de entrada |
| `tokens_output` | `INTEGER` | Não |  | Tokens de saída |
| `tokens_total` | `INTEGER` | Não |  | Soma de entrada + saída |
| `estimated_cost_usd` | `NUMERIC(12,6)` | Sim |  | Custo estimado |
| `operation` | `VARCHAR(30)` | Não |  | Ex.: `chat`, `followup`, `resumo`, `perfil`, `busca` |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |

### 5.3 Constraints recomendadas

```sql
CHECK (tokens_input >= 0)
CHECK (tokens_output >= 0)
CHECK (tokens_total >= 0)
CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0)
CHECK (conversation_turn IS NULL OR conversation_turn >= 0)
```

### 5.4 Chave estrangeira

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
```

### 5.5 Índices recomendados

```sql
CREATE INDEX idx_llm_usage_lead_id ON llm_usage(lead_id);
CREATE INDEX idx_llm_usage_operation ON llm_usage(operation);
CREATE INDEX idx_llm_usage_created_at ON llm_usage(created_at);
CREATE INDEX idx_llm_usage_lead_operation_created_at ON llm_usage(lead_id, operation, created_at);
```

---

## 6. Convenções transversais

### 6.1 Nomes de tabelas
Usar nomes no plural e em minúsculas:
- `leads`
- `mensagens`
- `agendamentos`
- `imoveis`
- `llm_usage`

### 6.2 Chaves estrangeiras
Usar padrão `<entidade>_id`.

### 6.3 Auditoria mínima
Nesta etapa, toda tabela operacional principal deve ter ao menos:
- PK estável
- timestamp de criação

`leads` deve ter também `updated_at`.

### 6.4 Observabilidade e rastreabilidade
A modelagem deve permitir correlação mínima por:
- `lead_id`
- tempo (`timestamp` / `created_at`)
- operação (`llm_usage.operation`)

---

## 7. Tabela `lead_channel_identities`

### 7.1 Finalidade
Representar identidades externas de canal vinculadas a um lead.

Na POC, esta tabela resolve principalmente o vínculo entre:
- `telegram_chat_id`
- `lead_id`

sem transformar o identificador do canal na identidade definitiva da pessoa.

### 7.2 Colunas propostas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Não |  | FK para `leads.id` |
| `channel` | `VARCHAR(30)` | Não |  | Ex.: `telegram`, `streamlit` |
| `external_user_id` | `VARCHAR(100)` | Sim |  | Identificador externo do usuário, quando existir |
| `external_chat_id` | `VARCHAR(100)` | Sim |  | Identificador externo do chat, quando existir |
| `is_primary` | `BOOLEAN` | Não | `false` | Indica identidade principal daquele canal para o lead |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |
| `last_seen_at` | `TIMESTAMPTZ` | Sim |  | Última atividade observada |

### 7.3 Constraints recomendadas

```sql
CHECK (channel IN ('telegram', 'streamlit'))
CHECK (external_user_id IS NOT NULL OR external_chat_id IS NOT NULL)
```

### 7.4 Chave estrangeira

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
```

### 7.5 Índices recomendados

```sql
CREATE INDEX idx_lead_channel_identities_lead_id ON lead_channel_identities(lead_id);
CREATE INDEX idx_lead_channel_identities_channel ON lead_channel_identities(channel);
CREATE INDEX idx_lead_channel_identities_external_user_id ON lead_channel_identities(external_user_id);
CREATE INDEX idx_lead_channel_identities_external_chat_id ON lead_channel_identities(external_chat_id);
CREATE INDEX idx_lead_channel_identities_last_seen_at ON lead_channel_identities(last_seen_at);
```

### 7.6 Unicidade recomendada

Para a POC, recomenda-se garantir unicidade por canal + identificador externo quando o valor existir.

Exemplos conceituais:

```sql
UNIQUE (channel, external_chat_id)
UNIQUE (channel, external_user_id)
```

> Em PostgreSQL real, isso pode exigir índice único parcial para lidar corretamente com `NULL`.

### 7.7 Relação com `mensagens`

A coluna `mensagens.channel_identity_id` passa a referenciar esta tabela.

Chave estrangeira futura:

```sql
FOREIGN KEY (channel_identity_id) REFERENCES lead_channel_identities(id)
```

### 7.8 Regras de negócio da POC refletidas na modelagem

- um lead pode ter mais de uma identidade de canal;
- uma identidade de canal pertence a um único lead por vez;
- `telegram_chat_id` é tratado como identidade de canal, não como identidade definitiva da pessoa;
- duplicidade de leads ainda pode existir, mas a modelagem permite reconciliação futura.

### 7.9 Observações

- `streamlit` pode usar esta tabela futuramente se houver autenticação/identidade persistente por usuário.
- nesta fase, a tabela é especialmente importante para Telegram.
- a política de merge de leads duplicadas continua fora do escopo desta etapa.

---

## 8. Decisão sobre `conversation` / `session`

### 8.1 Decisão adotada para a POC
**Não criar, nesta fase, uma tabela obrigatória de `conversations` ou `sessions`.**

### 8.2 Justificativa
Para a POC, a combinação abaixo é suficiente:

- `Lead` como entidade principal de negócio;
- `lead_channel_identities` para resolver identidade de canal;
- `mensagens` enriquecida com rastreabilidade de canal, tipo, status e encadeamento simples.

Essa combinação atende os objetivos atuais sem introduzir complexidade prematura.

### 8.3 O que substitui uma entidade de conversa nesta fase
Na ausência de uma tabela explícita de `conversation` / `session`, a POC usará:

- `lead_id` como eixo principal do histórico;
- `channel` e `channel_identity_id` para distinguir origem;
- `timestamp` para ordenação temporal;
- `in_reply_to_message_id` para encadeamento simples quando necessário.

### 8.4 Benefícios desta decisão
- reduz complexidade de schema e implementação;
- evita modelagem excessiva para o escopo do hackathon;
- mantém o histórico suficientemente rastreável;
- preserva espaço para evolução futura sem bloquear a POC.

### 8.5 Limitações aceitas
- não haverá agrupamento formal de múltiplas threads por lead;
- retomadas independentes de contexto não terão entidade própria;
- auditoria por “sessão” ficará implícita, não explícita;
- métricas por conversa dependerão de convenções de aplicação, não de uma tabela dedicada.

### 8.6 Quando reavaliar esta decisão
Uma entidade `conversation` / `session` deve ser reconsiderada se a solução evoluir para qualquer um dos cenários abaixo:

1. múltiplos canais simultâneos por lead;
2. múltiplas threads independentes por canal;
3. necessidade de auditoria formal por sessão;
4. retomadas de contexto paralelas;
5. analytics específicos por conversa;
6. necessidade de associar artefatos, eventos ou custos a uma thread específica.

### 8.7 Impacto em `llm_usage`
O campo `conversation_turn` em `llm_usage` permanece válido na POC como contador lógico de turnos por lead, mesmo sem uma tabela explícita de `conversation`.

---

## 9. Tabela `followup_attempts`

### 9.1 Finalidade
Registrar cada tentativa operacional de follow-up executada pelo `FollowUpService`.

Esta tabela existe para separar claramente:

- a **mensagem** gerada/enviada, que pertence ao histórico em `mensagens`;
- a **tentativa operacional**, que pertence ao controle da régua de follow-up.

### 9.2 Colunas propostas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Não |  | FK para `leads.id` |
| `message_id` | `BIGINT` | Sim |  | FK para `mensagens.id`; pode ser nulo se a geração falhar antes da persistência |
| `regua` | `VARCHAR(30)` | Não |  | Ex.: `lead_novo_sem_resposta`, `qualificacao_interrompida`, `pos_envio_imoveis`, `pos_agendamento` |
| `attempt_number` | `SMALLINT` | Não |  | Número da tentativa dentro da régua |
| `status` | `VARCHAR(20)` | Não |  | Ex.: `generated`, `sent`, `failed`, `skipped` |
| `failure_reason` | `VARCHAR(120)` | Sim |  | Motivo resumido da falha ou skip |
| `scheduled_for` | `TIMESTAMPTZ` | Sim |  | Momento planejado da tentativa, quando aplicável |
| `executed_at` | `TIMESTAMPTZ` | Não | `now()` | Momento da execução |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação do registro |

### 9.3 Constraints recomendadas

```sql
CHECK (attempt_number >= 1)
CHECK (status IN ('generated', 'sent', 'failed', 'skipped'))
CHECK (regua IN (
	'lead_novo_sem_resposta',
	'qualificacao_interrompida',
	'pos_envio_imoveis',
	'pos_agendamento'
))
```

### 9.4 Chaves estrangeiras

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
FOREIGN KEY (message_id) REFERENCES mensagens(id)
```

### 9.5 Índices recomendados

```sql
CREATE INDEX idx_followup_attempts_lead_id ON followup_attempts(lead_id);
CREATE INDEX idx_followup_attempts_regua ON followup_attempts(regua);
CREATE INDEX idx_followup_attempts_status ON followup_attempts(status);
CREATE INDEX idx_followup_attempts_executed_at ON followup_attempts(executed_at);
CREATE INDEX idx_followup_attempts_lead_regua_executed_at ON followup_attempts(lead_id, regua, executed_at);
```

### 9.6 Unicidade e prevenção de duplicidade

Para a POC, a prevenção de duplicidade será feita principalmente na camada de aplicação (`FollowUpService`), mas a modelagem deve facilitar essa verificação.

Recomendação conceitual:

- consultar tentativas recentes por `lead_id + regua` antes de disparar nova tentativa;
- usar `attempt_number` como contador lógico por régua.

### 9.7 Relação com `mensagens`

- se a mensagem for gerada e persistida com sucesso, `message_id` referencia a linha correspondente em `mensagens`;
- se a tentativa falhar antes da persistência da mensagem, `message_id` pode permanecer `NULL`;
- isso permite distinguir falha de geração, falha de envio e tentativa pulada.

### 9.8 Regras de negócio refletidas na modelagem

- o controle da régua pertence ao `FollowUpService`;
- a LLM apenas compõe a mensagem;
- a tentativa operacional precisa existir mesmo quando a mensagem não chega a ser enviada;
- o histórico do lead continua em `mensagens`, mas o controle operacional fica em `followup_attempts`.

### 9.9 Observações

- `failure_reason` deve ser curto e operacional; detalhes extensos podem ir para logs.
- `status='skipped'` cobre casos em que a tentativa foi avaliada, mas não executada por regra de negócio.

---

## 10. Definição de `score` e `status`

### 10.1 Objetivo
Definir como o lead será classificado operacionalmente na POC, tanto para priorização comercial quanto para automações de follow-up e visualização no dashboard.

---

### 10.2 Campo `score`

#### Tipo persistido
O campo `leads.score` permanece como:

```sql
NUMERIC(4,2)
```

#### Faixa válida

$$
0 \leq score \leq 10
$$

#### Interpretação operacional sugerida

| Faixa | Interpretação |
|---|---|
| `0.00` a `3.99` | Lead frio / pouco qualificado |
| `4.00` a `6.99` | Lead em qualificação / potencial moderado |
| `7.00` a `8.99` | Lead quente |
| `9.00` a `10.00` | Lead muito quente / alta prioridade |

> Para o dashboard da POC, a regra já documentada de “lead quente = score ≥ 7” permanece válida.

### 10.3 Critérios de composição do score

O score da POC deve ser calculado a partir de cinco dimensões já previstas no plano:

1. completude dos dados;
2. urgência declarada;
3. aderência com catálogo;
4. engajamento conversacional;
5. intenção de agendamento.

#### Distribuição sugerida de pesos

| Dimensão | Peso máximo |
|---|---:|
| Completude dos dados | `3.0` |
| Urgência declarada | `2.0` |
| Aderência com catálogo | `2.0` |
| Engajamento conversacional | `1.5` |
| Intenção de agendamento | `1.5` |
| **Total** | **10.0** |

### 10.4 Regras sugeridas por dimensão

#### A. Completude dos dados (`0.0` a `3.0`)
Pontuar conforme presença de informações-chave:
- intenção;
- orçamento;
- localização;
- quartos;
- urgência.

Exemplo conceitual:
- 0 ou 1 campo relevante: `0.5`
- 2 campos: `1.5`
- 3 ou 4 campos: `2.5`
- 5 campos: `3.0`

#### B. Urgência declarada (`0.0` a `2.0`)
- `baixa` → `0.5`
- `media` → `1.0`
- `alta` → `2.0`

#### C. Aderência com catálogo (`0.0` a `2.0`)
- nenhuma aderência encontrada → `0.0`
- aderência parcial / poucos imóveis razoáveis → `1.0`
- boa aderência / imóveis claramente compatíveis → `2.0`

#### D. Engajamento conversacional (`0.0` a `1.5`)
Sinais possíveis:
- responde perguntas;
- mantém a conversa ativa;
- demonstra interesse real;
- comenta/rejeita opções com motivo.

Exemplo conceitual:
- baixo engajamento → `0.5`
- médio → `1.0`
- alto → `1.5`

#### E. Intenção de agendamento (`0.0` a `1.5`)
- nenhuma intenção → `0.0`
- abertura implícita → `0.5`
- interesse claro em avançar → `1.0`
- pedido explícito de visita/reunião → `1.5`

### 10.5 Persistência do score
- o score será **persistido** em `leads.score`;
- ele representa um **snapshot operacional atual** do lead;
- pode ser recalculado ao longo da conversa e atualizado conforme novas informações surgirem.

### 10.6 Explicabilidade
O resumo do corretor deve explicar o score em linguagem simples, mencionando os principais fatores que o elevaram ou reduziram.

---

### 10.7 Campo `status`

#### Tipo persistido
O campo `leads.status` permanece como:

```sql
VARCHAR(30)
```

#### Valores válidos da POC

```sql
'novo'
'em_qualificacao'
'qualificado'
'agendado'
'inativo'
```

### 10.8 Significado operacional dos status

| Status | Significado |
|---|---|
| `novo` | Lead recém-criado, ainda sem qualificação suficiente |
| `em_qualificacao` | Conversa em andamento, com coleta progressiva de contexto |
| `qualificado` | Lead com contexto suficiente e potencial comercial claro |
| `agendado` | Lead com visita ou reunião registrada |
| `inativo` | Lead sem resposta recente ou fora de tração no momento |

### 10.9 Regras sugeridas de transição

#### `novo` → `em_qualificacao`
Quando houver interação inicial válida e início de coleta de contexto.

#### `em_qualificacao` → `qualificado`
Quando houver contexto suficiente para ação comercial, por exemplo:
- intenção conhecida;
- orçamento ou faixa de preço conhecida;
- localização conhecida;
- score operacional relevante (ex.: `score >= 7` ou critério equivalente de negócio).

#### `qualificado` → `agendado`
Quando existir um registro válido em `agendamentos`.

#### `novo` / `em_qualificacao` / `qualificado` → `inativo`
Quando o lead ficar sem resposta além da janela operacional definida para a régua correspondente.

#### `inativo` → `em_qualificacao`
Quando o lead voltar a interagir e a conversa for retomada.

### 10.10 Regras importantes
- `agendado` tem precedência operacional sobre `qualificado`;
- `inativo` não significa perda definitiva, apenas ausência de tração recente;
- o status deve refletir o estágio atual do funil, não um histórico completo de estados.

### 10.11 Histórico de mudanças
Na POC, **não será criada ainda uma tabela específica de histórico de status/score**.

As mudanças serão refletidas no estado atual do lead e inferidas, quando necessário, por:
- histórico de mensagens;
- agendamentos;
- tentativas de follow-up;
- timestamps do próprio lead.

Se a solução evoluir, uma tabela de histórico de status/score poderá ser introduzida depois.

### 10.12 Impacto no dashboard

O dashboard deve usar:
- `score` para ordenação e priorização;
- `status` para filtros operacionais;
- `score >= 7` para KPI de leads quentes.

### 10.13 Impacto no follow-up

O `FollowUpService` deve considerar o `status` como um dos sinais principais para escolher a régua aplicável.

Exemplos:
- `novo` sem resposta → régua de lead novo;
- `em_qualificacao` → régua de qualificação interrompida;
- `qualificado` após envio de imóveis → régua pós-envio;
- `agendado` → régua de confirmação/lembrete.

---

## 11. Decisões explicitamente adiadas

As decisões abaixo serão tratadas nas próximas lacunas:

1. histórico de mudanças de score/status.

---

## 12. Resultado desta etapa

Com este documento, a POC passa a ter uma **modelagem lógica mínima definida** para as tabelas principais, suficiente para orientar:
- schemas Pydantic;
- modelos SQLAlchemy;
- migrations Alembic;
- testes de persistência.
