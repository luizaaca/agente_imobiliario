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
- `operacao`
- `bairro`
- `zona`
- `cidade`
- `estado`
- `preco`
- `quartos`
- `suites`
- `banheiros`
- `vaga_garagem`
- `area_m2`
- `condominio`
- `iptu_anual`
- `descricao`
- `tags`
- `perfil_indicado`
- `disponivel`
- `imagem_url`
- `search_vector`
- `created_at`
- `updated_at`

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

### 3.7 Índices
- Além das chaves primárias, o schema cria só os índices que uma regra ou uma
  consulta concreta pede: o GIN do texto completo, o que sustenta o painel de
  consumo, e os únicos que impõem regra de negócio.
- No volume da POC as demais consultas varrem a tabela e terminam abaixo de
  um milissegundo. Medido com `EXPLAIN ANALYZE` no banco de desenvolvimento
  (300 imóveis, 400 mensagens): a busca estruturada por finalidade, preço e
  quartos leva 0,46 ms, e o histórico de um lead, 0,12 ms. Índice por coluna
  entra quando o volume pedir, medido do mesmo jeito, e não por antecipação.

### 3.8 Defaults
- Os defaults de `status` em `mensagens`, de `cidade`, `estado` e `disponivel`
  em `imoveis`, e de `is_primary` em `lead_channel_identities` são aplicados
  pelo SQLAlchemy, e não pelo banco. Os de data (`now()`) e o de
  `llm_usage.status` (`'ok'`) são do banco.

### 3.9 Origem do schema
- O schema inteiro vem de uma migration única,
  `alembic/versions/29abbb20023f_schema_inicial.py`, aplicada no Compose pelo
  serviço `migrate` e na suíte de testes a cada execução. Tudo o que esta
  modelagem descreve como existente foi conferido contra o banco criado por ela.

---

## 4. Tabela `leads`

### 4.1 Finalidade
Representa o lead e seu estado consolidado de qualificação.

### 4.2 Colunas

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

### 4.3 Constraints

```sql
CHECK (orcamento_min >= 0)
CHECK (orcamento_max >= 0)
CHECK (quartos >= 0)
CHECK (score >= 0 AND score <= 10)
CHECK (status IN ('novo', 'em_qualificacao', 'qualificado', 'agendado', 'inativo'))
CHECK (intencao IN ('compra', 'aluguel', 'investimento'))
CHECK (urgencia IN ('baixa', 'media', 'alta'))
```

Todas aceitam `NULL`: no PostgreSQL um `CHECK` que resulta em `NULL` passa, e
as colunas opcionais continuam opcionais.

### 4.4 Índices

Só a chave primária (ver §3.7).

### 4.5 Observações
- `telefone` não é `UNIQUE`: a identidade da pessoa num canal fica em `lead_channel_identities`, e duas fichas com o mesmo telefone são um caso de merge, não um erro de gravação.
- `updated_at` é atualizado pelo `onupdate` do SQLAlchemy; um `UPDATE` feito direto no banco não o altera.

---

## 5. Tabela `mensagens`

### 5.1 Finalidade
Persistir o histórico de mensagens associado a um lead, com rastreabilidade mínima de canal e estado operacional.

### 5.2 Decisão desta etapa
Nesta etapa, a tabela `mensagens` deixa de ser apenas um histórico textual mínimo e passa a incorporar metadados suficientes para:

- distinguir origem/canal da mensagem;
- rastrear mensagens recebidas, geradas e enviadas;
- suportar Telegram, Streamlit e follow-up automático;
- manter a modelagem simples, sem exigir ainda uma entidade explícita de `conversation` / `session`.

### 5.3 Colunas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Não |  | FK para `leads.id` |
| `channel` | `VARCHAR(30)` | Não |  | `telegram` ou `streamlit` — no follow-up, o canal da identidade primária do lead |
| `channel_identity_id` | `BIGINT` | Sim |  | Reservada para apontar a identidade de canal; sem FK e não preenchida |
| `role` | `VARCHAR(20)` | Não |  | `user`, `assistant`, `system`, `tool` |
| `message_type` | `VARCHAR(30)` | Não |  | Ex.: `chat`, `followup`, `system_notice`, `handover` |
| `content` | `TEXT` | Não |  | Conteúdo textual da mensagem |
| `status` | `VARCHAR(20)` | Não | `'created'` (ORM) | Ex.: `received`, `generated`, `sent`, `failed` |
| `external_message_id` | `VARCHAR(100)` | Sim |  | ID externo do canal, quando existir |
| `in_reply_to_message_id` | `BIGINT` | Sim |  | Auto-relacionamento opcional para encadeamento simples |
| `metadata_json` | `JSON` | Sim |  | O que cada chamada de ferramenta fez: IDs apresentados, consultas do agente de busca |
| `timestamp` | `TIMESTAMPTZ` | Não | `now()` | Momento principal do registro |
| `sent_at` | `TIMESTAMPTZ` | Sim |  | Momento efetivo de envio, quando aplicável |

### 5.4 Constraints

```sql
CHECK (role IN ('user', 'assistant', 'system', 'tool'))
CHECK (message_type IN ('chat', 'followup', 'system_notice', 'handover'))
CHECK (status IN ('created', 'received', 'generated', 'sent', 'failed'))
```

### 5.5 Chaves estrangeiras

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
FOREIGN KEY (in_reply_to_message_id) REFERENCES mensagens(id)
```

### 5.6 Índices

Só a chave primária (ver §3.7). O histórico é lido por `lead_id` e ordenado
por `id`, e não por `timestamp`: uma chamada de ferramenta e o retorno dela
caem no mesmo segundo, e o empate embaralharia o par.

### 5.7 Justificativa dos novos campos

#### `channel`
Permite distinguir a origem da mensagem sem depender apenas do `canal_origem` do lead.

#### `channel_identity_id`
Reservada para ligar a mensagem à identidade de canal exata. Hoje o canal da
mensagem (`channel`) e a identidade primária do lead bastam, e a coluna fica
vazia.

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

### 5.8 Observações
- Ainda não estamos introduzindo uma entidade explícita de `conversation` / `session`.
- O histórico continua sendo persistido por `lead_id`, com rastreabilidade de canal.
- A política de `ON DELETE` continua adiada para a etapa de retenção e identidade de canal.

---

## 6. Tabela `agendamentos`

### 6.1 Finalidade
Persistir visitas e reuniões associadas a um lead.

### 6.2 Colunas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Não |  | FK para `leads.id` |
| `tipo` | `VARCHAR(20)` | Não |  | `visita` ou `reuniao` |
| `data_hora` | `TIMESTAMPTZ` | Não |  | Data/hora do compromisso |
| `observacoes` | `TEXT` | Sim |  | O que o corretor lê antes de ir, inclusive os imóveis que a pessoa quer ver, com ID |
| `status` | `VARCHAR(20)` | Não |  | `pendente`, `confirmado`, `cancelado`, `realizado` |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |

Não há vínculo com `imoveis`. Quem visita raramente visita um imóvel só, e uma
FK única obrigaria a escolher um deles e perder o resto — os imóveis de
interesse vão escritos na `observacoes`, que é o que o corretor lê junto do
perfil narrativo e do resumo executivo.

### 6.3 Constraints

```sql
CHECK (tipo IN ('visita', 'reuniao'))
CHECK (status IN ('pendente', 'confirmado', 'cancelado', 'realizado'))
```

### 6.4 Chave estrangeira

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
```

### 6.5 Índices

```sql
-- Um compromisso de pe por lead.
CREATE UNIQUE INDEX uq_agendamentos_ativo_por_lead
ON agendamentos (lead_id)
WHERE status IN ('pendente', 'confirmado');
```

O índice único é parcial de propósito: `cancelado` e `realizado` se repetem à
vontade, porque são o histórico de onde o corretor tira que a pessoa já
desmarcou uma vez. A regra fica no banco, e não só no código: uma checagem na
aplicação cede a dois turnos gravando ao mesmo tempo, e a um modelo que erra
qual compromisso trocar. Com a unicidade garantida aqui, as tools de confirmar
e cancelar não recebem qual compromisso: o dono é o lead do turno.

---

## 7. Tabela `llm_usage`

### 7.1 Finalidade
Registrar consumo de LLM para auditoria, controle de custo e métricas operacionais.

### 7.2 Colunas

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
| `operation` | `VARCHAR(30)` | Não |  | `chat`, `followup`, `perfil` ou `busca` |
| `status` | `VARCHAR(20)` | Não | `'ok'` | `ok` ou `erro`: a tabela é o livro-caixa de toda chamada, inclusive as que falharam |
| `error_type` | `VARCHAR(80)` | Sim |  | Classe da exceção, quando `status='erro'` |
| `latency_ms` | `INTEGER` | Sim |  | Tempo da chamada ao provider |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |

### 7.3 Constraints

```sql
CHECK (tokens_input >= 0)
CHECK (tokens_output >= 0)
CHECK (tokens_total >= 0)
```

### 7.4 Chave estrangeira

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
```

### 7.5 Índices

```sql
-- O painel de consumo filtra por periodo e separa as falhas.
CREATE INDEX ix_llm_usage_created_at_status ON llm_usage (created_at, status);
```

---

## 8. Tabela `imoveis`

### 8.1 Finalidade
Catálogo de imóveis disponíveis para busca, recomendação e referência pelo agente SDR.

### 8.2 Fonte de dados

O catálogo será populado **integralmente por geração sintética**, sem dependência de datasets externos. A POC assume que os imóveis de demonstração são produzidos a partir de regras determinísticas e geração assistida por LLM, com foco em:

- cobertura equilibrada de bairros, tipologias e faixas de preço;
- descrições textuais ricas para demonstrar FTS com boa qualidade;
- consistência entre atributos estruturados e narrativa do imóvel;
- controle total sobre volume, distribuição e qualidade dos registros.

Essa abordagem garante massa de dados própria e perfeitamente aderente às necessidades de busca do MVP, sem depender de fontes externas.

#### Mapeamento esperado

Todos os campos do catálogo devem ser produzidos pela etapa de geração sintética.

| Coluna | Estratégia / observação |
|---|---|
| `preco` | Gerar faixa de preço em BRL e persistir em `NUMERIC(12,2)` |
| `area_m2` | Gerar área com distribuição coerente com o tipo e padrão do imóvel |
| `quartos` | Gerar quantidade compatível com área, tipologia e perfil do imóvel |
| `suites` | Gerar opcionalmente, de forma coerente com padrão e quantidade de quartos |
| `banheiros` | Gerar quantidade compatível com tipologia, área e padrão do imóvel |
| `vaga_garagem` | Gerar opcionalmente conforme perfil, bairro e faixa de preço |
| `bairro` | Sortear a partir de lista curada da POC |
| `zona` | Derivar do bairro ou definir diretamente no gerador |
| `cidade` | Usar valor padrão da POC: `São Paulo` |
| `estado` | Usar valor padrão da POC: `SP` |
| `condominio` | Gerar valor ou `NULL` quando a tipologia permitir |
| `iptu_anual` | Gerar valor ou `NULL` quando fizer sentido |
| `tipo` | Gerar entre valores residenciais (`apartamento`, `casa`, `studio`, `cobertura`, `casa_condominio`, `sobrado`, `flat`, `loft`) e comerciais (`sala_comercial`, `consultorio`, `escritorio`, `andar_corporativo`, `predio_comercial`, `loja`, `galpao`, `terreno_comercial`) |
| `finalidade` | Gerar entre valores como `residencial`, `comercial` |
| `operacao` | Gerar entre valores como `venda`, `aluguel` |
| `titulo` | Compor a partir dos outros campos |
| `descricao` | Gerar com base nos demais atributos sintéticos |
| `tags` | Gerar a partir dos outros campos |
| `perfil_indicado` | Inferir por regras de negócio a partir dos atributos sintéticos |
| `disponivel` | Definir conforme cenário da POC; default recomendado `true` |
| `imagem_url` | Usar placeholder por tipo ou perfil do imóvel |

### 8.3 Colunas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `titulo` | `VARCHAR(200)` | Não |  | Gerado sinteticamente a partir dos metadados |
| `tipo` | `VARCHAR(30)` | Não |  | Ex.: `apartamento`, `studio`, `cobertura`, `casa`, `casa_condominio`, `sobrado`, `flat`, `loft`, `sala_comercial`, `consultorio`, `escritorio`, `andar_corporativo`, `predio_comercial`, `loja`, `galpao`, `terreno_comercial` |
| `finalidade` | `VARCHAR(20)` | Não |  | Ex.: `residencial`, `comercial` |
| `operacao` | `VARCHAR(20)` | Não |  | Ex.: `venda`, `aluguel` |
| `bairro` | `VARCHAR(100)` | Não |  | Bairro do imóvel |
| `zona` | `VARCHAR(50)` | Sim |  | Ex.: `zona_sul`, `zona_oeste`, `centro`, `zona_norte`, `zona_leste` |
| `cidade` | `VARCHAR(100)` | Não | `'São Paulo'` (ORM) | Cidade |
| `estado` | `VARCHAR(2)` | Não | `'SP'` (ORM) | UF |
| `preco` | `NUMERIC(12,2)` | Não |  | Preço em BRL |
| `quartos` | `SMALLINT` | Não |  | Quantidade de quartos / salas privativas (0 para comercial) |
| `suites` | `SMALLINT` | Sim |  | Quantidade de suítes (se disponível; 0 para comercial) |
| `banheiros` | `SMALLINT` | Sim |  | Quantidade de banheiros |
| `vaga_garagem` | `SMALLINT` | Sim |  | Vagas de garagem |
| `area_m2` | `NUMERIC(10,2)` | Não |  | Área em m² |
| `condominio` | `NUMERIC(10,2)` | Sim |  | Valor do condomínio mensal |
| `iptu_anual` | `NUMERIC(10,2)` | Sim |  | IPTU anual |
| `descricao` | `TEXT` | Sim |  | Descrição textual rica (essencial para FTS) |
| `tags` | `TEXT` | Sim |  | Tags ou amenidades em texto livre (separadas por vírgula) |
| `perfil_indicado` | `VARCHAR(30)` | Sim |  | Ex.: `residencial_familia`, `alto_padrao`, `investidor`, `corporativo`, `pequena_empresa`, `saude_consultorio`, `varejo_comercio`, `logistica_industrial` |
| `disponivel` | `BOOLEAN` | Não | `true` (ORM) | Se o imóvel está disponível |
| `imagem_url` | `VARCHAR(500)` | Sim |  | URL da imagem principal (placeholder na POC) |
| `search_vector` | `TSVECTOR` | Sim |  | Vetor de busca FTS, gerado automaticamente |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |
| `updated_at` | `TIMESTAMPTZ` | Não | `now()` | Última atualização |

### 8.4 Constraints

```sql
CHECK (finalidade IN ('residencial', 'comercial'))
CHECK (operacao IN ('venda', 'aluguel'))
CHECK (preco > 0)
CHECK (area_m2 > 0)
CHECK (quartos >= 0)
CHECK (suites >= 0)
CHECK (banheiros >= 0)
CHECK (vaga_garagem >= 0)
CHECK (condominio >= 0)
CHECK (iptu_anual >= 0)
```

`tipo` não tem `CHECK`. O vocabulário vive em `FINALIDADE_POR_TIPO`
(`src/services/catalog_service.py`), que também diz a finalidade de cada tipo,
e `tests/test_catalog_service.py` o compara com o `SELECT DISTINCT` da coluna —
um tipo novo no catálogo quebra a suíte em vez de passar despercebido.

### 8.5 Índices

```sql
CREATE INDEX ix_imoveis_search_vector ON imoveis USING GIN (search_vector);
```

Os filtros numéricos e de categoria não têm índice próprio (ver §3.7): com 300
imóveis, a varredura sequencial termina em menos de meio milissegundo.

### 8.6 Full-Text Search (FTS)

O FTS é o mecanismo de ranking textual do catálogo.

#### `search_vector` é coluna gerada

```sql
search_vector TSVECTOR GENERATED ALWAYS AS (
    to_tsvector('portuguese'::regconfig,
        coalesce(titulo, '')    || ' ' ||
        coalesce(descricao, '') || ' ' ||
        coalesce(tags, '')      || ' ' ||
        coalesce(bairro, '')    || ' ' ||
        coalesce(tipo, '')
    )
) STORED
```

Coluna gerada, e não trigger: o PostgreSQL recalcula o vetor em todo `INSERT` e
`UPDATE` que toque uma das cinco colunas, sem código nosso no caminho. Não há
trigger para desabilitar por engano, nem carga em massa que escape dele — o
vetor não tem como ficar defasado.

A expressão vive em `SEARCH_VECTOR_EXPR`, repetida no modelo
(`src/db/models.py`) e na migration. O texto precisa ser idêntico nos dois:
qualquer divergência faz o `autogenerate` do Alembic acusar drift de schema.

O índice que a atende é `ix_imoveis_search_vector`, GIN sobre a coluna.

#### O que está e o que não está no vetor

| No vetor | Fora do vetor |
|---|---|
| `titulo`, `descricao`, `tags`, `bairro`, `tipo` | `zona`, `finalidade`, `perfil_indicado`, `operacao`, e todos os numéricos |

O que ficou de fora tem coluna própria e se filtra com `WHERE`. A distinção
importa na hora de escrever consulta: procurar `zona_norte` no vetor não devolve
nada, e procurar "comercial" como texto traz apartamento que usa a palavra na
descrição e perde sala que não a usa.

#### `updated_at`

Mantido pela aplicação, com `onupdate` do SQLAlchemy — não há trigger. Um
`UPDATE` feito fora do ORM, direto no banco, não atualiza a coluna.

#### Busca em camadas (caminho de degradação)

Quem consulta o catálogo é o agente de busca, com SQL próprio (§8.9). Com o
provider fora do ar, o `CatalogService` faz a busca estruturada no formato
abaixo, afrouxando um critério por vez quando nada casa:

```sql
-- Camada 1: filtros estruturados
SELECT * FROM imoveis
WHERE disponivel = true
  AND finalidade = $1
  AND preco BETWEEN $2 AND $3
  AND bairro ILIKE $4
  AND quartos >= $5

-- Camada 2: ranking textual sobre o que restou
ORDER BY ts_rank(search_vector, websearch_to_tsquery('portuguese', $6)) DESC
LIMIT $7;
```

`websearch_to_tsquery`, e não `plainto_tsquery`: ela aceita `or`, `-` e aspas
vindos do texto cru sem levantar erro de sintaxe, o que é o que se precisa
quando a consulta é montada a partir do que um modelo escreveu.

### 8.7 Observações sobre o script de seed

O script `scripts/seed_imoveis.py` deve atuar **somente como mecanismo de ingestão na base**. A geração dos registros acontece antes dele, em etapa separada de produção do catálogo sintético.

Responsabilidades do script de seed:

1. Ler o artefato já gerado do catálogo sintético (por exemplo, JSON ou CSV interno da aplicação).
2. Validar campos obrigatórios e consistência mínima antes da carga.
3. Normalizar formatos finais quando necessário (tipos, finalidade, bairro, casas decimais).
4. Inserir no PostgreSQL via SQLAlchemy.
5. Registrar métricas básicas da carga (quantidade inserida, rejeitada, atualizada, se aplicável).
6. Alvo: **≥ 200 imóveis** com descrições ricas o suficiente para demonstração do FTS.

> Como o catálogo será 100% sintético, a qualidade de **todos os campos** passa a ser responsabilidade direta da etapa de geração. O script de seed apenas valida e persiste os registros na base.

### 8.8 Volume esperado

| Cenário | Volume |
|---|---|
| POC / Demo | 200–500 imóveis |
| Piloto | 1.000–5.000 imóveis |
| Produção | 10.000+ imóveis |

> Os índices e a estratégia de FTS são suficientes para todos os cenários acima.

### 8.9 Acesso somente-leitura para o agente de busca

O agente de busca (ver [estratégia de agente e tools](../02-arquitetura/02-estrategia-de-agente-e-tools.md))
consulta o catálogo por SQL que ele mesmo escreve. Este banco é o mesmo que
guarda leads, telefones e o histórico das conversas, e o contexto desse agente
inclui o perfil narrativo — texto derivado do que o lead digitou. Uma instrução
escondida numa mensagem de lead é, portanto, um caminho até `SELECT telefone
FROM leads` se nada o barrar.

São quatro camadas. A primeira é o limite de verdade; as outras três são
profundidade.

| Camada | O que faz |
|---|---|
| Role `busca_ro` | `GRANT SELECT` apenas em `imoveis`. Sem acesso às demais tabelas, sem escrita em nenhuma |
| Transação | `SET TRANSACTION READ ONLY` e `statement_timeout` de 3 segundos |
| Validação do statement | exatamente um comando, iniciado por `SELECT` ou `WITH`; recusa `pg_*`, `information_schema` e qualquer tabela fora de `imoveis` |
| Teto de linhas | `LIMIT` injetado quando ausente |

A role é criada por migration, com a aplicação e o catálogo. Duas cautelas:

- **role no PostgreSQL é global ao cluster**, não ao banco. A migration consulta
  `pg_roles` e faz `ALTER ROLE` quando ela já existe, em vez de `CREATE` —
  senão falharia no segundo banco, que é exatamente o que a suíte de testes faz
  ao criar o seu. Os `GRANT`s são por banco e rodam em cada um;
- a senha vem de `DB_PASSWORD_BUSCA`, nunca do arquivo da migration, e é
  escapada pelo próprio servidor com `quote_literal`.

O timeout de 3 segundos é generoso para o volume da POC: a busca mais pesada
hoje é um `Bitmap Index Scan` sobre o índice GIN, na casa do milissegundo. Ele
existe para o caso que ninguém previu — um `CROSS JOIN` acidental, um `ORDER BY`
sobre expressão não indexada — e não para o caso normal.

### 8.10 Permissões da aplicação

A aplicação continua usando a role principal, com leitura e escrita. A
separação vale apenas para o SQL gerado por LLM: é o único código do sistema
que ninguém revisou antes de executar.

---

## 9. Convenções transversais

### 9.1 Nomes de tabelas
Usar nomes no plural e em minúsculas:
- `leads`
- `mensagens`
- `agendamentos`
- `imoveis`
- `llm_usage`

### 9.2 Chaves estrangeiras
Usar padrão `<entidade>_id`.

### 9.3 Auditoria mínima
Nesta etapa, toda tabela operacional principal deve ter ao menos:
- PK estável
- timestamp de criação

`leads` deve ter também `updated_at`.

### 9.4 Observabilidade e rastreabilidade
A modelagem deve permitir correlação mínima por:
- `lead_id`
- tempo (`timestamp` / `created_at`)
- operação (`llm_usage.operation`)

---

## 10. Tabela `lead_channel_identities`

### 10.1 Finalidade
Representar identidades externas de canal vinculadas a um lead.

Resolve o vínculo entre o identificador de um canal (o `chat_id` do Telegram,
o identificador de cada conversa do simulador) e o `lead_id`, sem transformar
o identificador do canal na identidade definitiva da pessoa.

### 10.2 Colunas

| Coluna | Tipo SQL | Null | Default | Observações |
|---|---|---:|---|---|
| `id` | `BIGSERIAL` | Não | auto | PK |
| `lead_id` | `BIGINT` | Não |  | FK para `leads.id` |
| `channel` | `VARCHAR(30)` | Não |  | Ex.: `telegram`, `streamlit` |
| `external_user_id` | `VARCHAR(100)` | Sim |  | Identificador externo do usuário, quando existir |
| `external_chat_id` | `VARCHAR(100)` | Sim |  | Identificador externo do chat, quando existir |
| `is_primary` | `BOOLEAN` | Não | `false` (ORM) | A identidade por onde o follow-up alcança o lead |
| `created_at` | `TIMESTAMPTZ` | Não | `now()` | Criação |
| `last_seen_at` | `TIMESTAMPTZ` | Sim |  | Última atividade observada |

### 10.3 Chave estrangeira

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
```

### 10.4 Constraints e índices

Nenhum `CHECK` e nenhum índice além da chave primária. A busca por
(`channel`, `external_chat_id`) acontece uma vez por mensagem recebida, numa
tabela com uma linha por conversa.

O par (`channel`, `external_chat_id`) **não é único no banco**, e a aplicação
só o protege em parte: `get_or_create_lead` procura antes de criar, e
`definir_identidade` reaproveita a identidade que o lead já tem naquele canal —
mas não confere se outro lead já usa o mesmo identificador. Ligar pela ficha um
`chat_id` que pertence a outra pessoa faria as duas fichas apontarem para o
mesmo chat.

### 10.8 Regras de negócio da POC refletidas na modelagem

- um lead pode ter mais de uma identidade de canal;
- uma identidade de canal pertence a um único lead por vez;
- o `chat_id` do Telegram é tratado como identidade de canal, não como identidade definitiva da pessoa;
- a identidade primária é por onde o follow-up alcança o lead; ligar um canal pela ficha a torna a primária;
- duplicidade de leads ainda pode existir, mas a modelagem permite reconciliação futura.

### 10.9 Observações

- o simulador do Streamlit também grava aqui: cada conversa nova recebe um identificador próprio, e com ele um lead.
- a política de merge de leads duplicadas fica fora do escopo da POC.

---

## 11. Decisão sobre `conversation` / `session`

### 11.1 Decisão adotada para a POC
**Não criar, nesta fase, uma tabela obrigatória de `conversations` ou `sessions`.**

### 11.2 Justificativa
Para a POC, a combinação abaixo é suficiente:

- `Lead` como entidade principal de negócio;
- `lead_channel_identities` para resolver identidade de canal;
- `mensagens` enriquecida com rastreabilidade de canal, tipo, status e encadeamento simples.

Essa combinação atende os objetivos atuais sem introduzir complexidade prematura.

### 11.3 O que substitui uma entidade de conversa nesta fase
Na ausência de uma tabela explícita de `conversation` / `session`, a POC usará:

- `lead_id` como eixo principal do histórico;
- `channel` e `channel_identity_id` para distinguir origem;
- `timestamp` para ordenação temporal;
- `in_reply_to_message_id` para encadeamento simples quando necessário.

### 11.4 Benefícios desta decisão
- reduz complexidade de schema e implementação;
- evita modelagem excessiva para o escopo do hackathon;
- mantém o histórico suficientemente rastreável;
- preserva espaço para evolução futura sem bloquear a POC.

### 11.5 Limitações aceitas
- não haverá agrupamento formal de múltiplas threads por lead;
- retomadas independentes de contexto não terão entidade própria;
- auditoria por “sessão” ficará implícita, não explícita;
- métricas por conversa dependerão de convenções de aplicação, não de uma tabela dedicada.

### 11.6 Quando reavaliar esta decisão
Uma entidade `conversation` / `session` deve ser reconsiderada se a solução evoluir para qualquer um dos cenários abaixo:

1. múltiplos canais simultâneos por lead;
2. múltiplas threads independentes por canal;
3. necessidade de auditoria formal por sessão;
4. retomadas de contexto paralelas;
5. analytics específicos por conversa;
6. necessidade de associar artefatos, eventos ou custos a uma thread específica.

### 11.7 Impacto em `llm_usage`
O campo `conversation_turn` em `llm_usage` permanece válido na POC como contador lógico de turnos por lead, mesmo sem uma tabela explícita de `conversation`.

---

## 12. Tabela `followup_attempts`

### 12.1 Finalidade
Registrar cada tentativa operacional de follow-up, gravada pelo `followup_runner` — no ciclo automático, no disparo manual e no despacho do que ficou pendente.

Esta tabela existe para separar claramente:

- a **mensagem** gerada/enviada, que pertence ao histórico em `mensagens`;
- a **tentativa operacional**, que pertence ao controle da régua de follow-up.

### 12.2 Colunas

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

### 12.3 Constraints

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

### 12.4 Chaves estrangeiras

```sql
FOREIGN KEY (lead_id) REFERENCES leads(id)
FOREIGN KEY (message_id) REFERENCES mensagens(id)
```

### 12.5 Índices e unicidade

```sql
-- A mesma regua nao dispara duas vezes a mesma tentativa para o mesmo lead.
ALTER TABLE followup_attempts
  ADD CONSTRAINT uq_followup_lead_regua_attempt UNIQUE (lead_id, regua, attempt_number);
```

### 12.6 Prevenção de duplicidade

Em duas camadas. A aplicação conta as tentativas de `lead_id + regua` antes de
gerar, e o próximo `attempt_number` sai dessa contagem. Se duas execuções
concorrentes calcularem o mesmo número, a unicidade acima faz a segunda falhar
com `IntegrityError` — a constraint é a última linha de defesa, e o
`max_instances=1` do scheduler é a primeira.

No despacho do que ficou pendente, a tentativa é reservada como `sent` por um
`UPDATE ... WHERE status = 'generated'` antes de ir à rede: só quem mudou a
linha envia.

### 12.7 Relação com `mensagens`

- se a mensagem for gerada e persistida com sucesso, `message_id` referencia a linha correspondente em `mensagens`;
- se a tentativa falhar antes da persistência da mensagem, `message_id` pode permanecer `NULL`;
- isso permite distinguir falha de geração, falha de envio e tentativa pulada.

### 12.8 Regras de negócio refletidas na modelagem

- a seleção de quem recebe, e em qual régua, pertence ao `FollowUpService`;
- a LLM apenas compõe a mensagem;
- a tentativa operacional precisa existir mesmo quando a mensagem não chega a ser enviada;
- o histórico do lead continua em `mensagens`, mas o controle operacional fica em `followup_attempts`.

### 12.9 Observações

- `failure_reason` deve ser curto e operacional; detalhes extensos podem ir para logs.
- `status='skipped'` cobre casos em que a tentativa foi avaliada, mas não executada por regra de negócio.
- `generated` é o desfecho normal num canal sem envio ativo (Streamlit): a mensagem está no chat do lead. `failed` fica para quando se tentou enviar e deu errado — um canal sem envio não é tentado.
- Num canal com envio, `generated` é uma espera: a mensagem foi gerada sem remetente (painel, script avulso) e o processo do Telegram a envia. Vira `skipped` se passar de 15 minutos, se o lead responder antes, ou se houver outra mais recente para o mesmo lead — só a última sai.

---

## 13. Definição de `score` e `status`

### 13.1 Objetivo
Definir como o lead será classificado operacionalmente na POC, tanto para priorização comercial quanto para automações de follow-up e visualização no dashboard.

---

### 13.2 Campo `score`

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

### 13.3 Critérios de composição do score

O score sai de cinco dimensões, e o que ele ordena é a fila de quem o corretor liga primeiro.

| Dimensão | Peso máximo |
|---|---:|
| Completude da ficha | `3.0` |
| Urgência declarada | `2.0` |
| Definição do pedido | `1.0` |
| Engajamento conversacional | `1.5` |
| Visita marcada | `2.5` |
| **Total** | **10.0** |

Não há cláusula de corte no cálculo. Os pesos somam exatamente 10, e um peso mal somado precisa quebrar em teste — não virar `INSERT` recusado pelo CHECK de faixa com o lead na tela.

### 13.4 Regras por dimensão

#### A. Completude da ficha (`0.0` a `3.0`)

Meio ponto por campo-chave preenchido, seis ao todo:

- intenção;
- orçamento;
- localização (bairro ou região);
- quartos;
- urgência;
- telefone.

Meio ponto por campo em vez de faixas largas: assim todo dado que a conversa arranca move o número, e não só o que cruza um degrau. Telefone está na lista porque o score ordena ligações — uma ficha impecável sem número nunca chega a virar contato.

#### B. Urgência declarada (`0.0` a `2.0`)

- `baixa` → `0.5`
- `media` → `1.0`
- `alta` → `2.0`

Urgência conta nas duas primeiras dimensões de propósito: na completude conta ter o dado, aqui conta o quanto ele aperta. Quem precisa mudar em trinta dias e quem pode esperar um ano contaram a mesma coisa, mas não valem a mesma ligação.

#### C. Definição do pedido (`0.0` a `1.0`)

`tipologia_interesse` preenchido vale `1.0`. Quem já sabe que quer apartamento e não casa passou do "estou só olhando".

#### D. Engajamento conversacional (`0.0` a `1.5`)

Mensagens escritas pela pessoa, sem contar as do agente:

- 1 a 5 → `0.5`
- 6 a 10 → `1.0`
- 11 ou mais → `1.5`

#### E. Visita marcada (`0.0` a `2.5`, com piso de `7.0`)

Vale quando há visita ou reunião de pé na agenda — status `pendente` ou `confirmado`. Cancelada e realizada não contam: a primeira deixou de existir, a segunda já aconteceu e o lead não está mais esperando por ela.

Além dos `2.5`, o lead com compromisso de pé **nunca fica abaixo de `7.0`**. É o evento de conversão do funil, e sem piso próprio ele valeria menos que a completude do cadastro — um lead com visita na agenda empataria com um lead que já parou de responder.

### 13.5 Persistência e recálculo

O score é persistido em `leads.score` e representa o retrato operacional atual do lead. Ele é recalculado:

- ao registrar qualificação nova na conversa (`registrar_qualificacao`);
- ao salvar a ficha do lead na tela;
- a cada mudança na agenda — criar, editar, cancelar, excluir ou dar por realizado um compromisso.

O terceiro caso passa por `SchedulingService.sincronizar_lead_com_a_agenda`, que é também quem acerta o status do lead: os dois fatos que a agenda determina saem do mesmo lugar, e não de cada chamador.

Não é editável à mão: seria um número dizendo uma coisa e os dados dizendo outra.

### 13.6 Explicabilidade
O resumo do corretor deve explicar o score em linguagem simples, mencionando os principais fatores que o elevaram ou reduziram.

---

### 13.7 Campo `status`

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

### 13.8 Significado operacional dos status

| Status | Significado |
|---|---|
| `novo` | Lead recém-criado, ainda sem qualificação suficiente |
| `em_qualificacao` | Conversa em andamento, com coleta progressiva de contexto |
| `qualificado` | Lead com contexto suficiente e potencial comercial claro |
| `agendado` | Lead com visita ou reunião registrada |
| `inativo` | Lead sem resposta recente ou fora de tração no momento |

### 13.9 Regras de transição

#### `novo` → `em_qualificacao`
Quando o lead escreve: `process_message` move para `em_qualificacao` antes de
o turno rodar.

#### `em_qualificacao` → `qualificado`
Quando `LeadService.esta_qualificado` é verdadeiro — há intenção, algum
orçamento (mínimo ou máximo), alguma localização (bairro ou região) e
quantidade de quartos. `avaliar_status` só avança leads em `novo` ou
`em_qualificacao`: quem já está adiante não regride por uma qualificação nova.

#### qualquer estágio ativo → `agendado`
Quando passa a existir compromisso de pé (`pendente` ou `confirmado`).
`SchedulingService.sincronizar_lead_com_a_agenda` faz status e score
concordarem com a agenda nos dois sentidos: sumindo o último compromisso, o
lead volta para `qualificado` ou `em_qualificacao`, conforme os dados dele.
`inativo` fica de fora da sincronização.

#### → `inativo`
Em três casos:
- o lead esgota as tentativas de uma régua de silêncio do follow-up;
- `encerrar_atendimento` com desfecho `desistiu` ou `pediu_corretor`;
- o teto de tokens ou de turnos da conversa, que faz o handover ao corretor.

#### `inativo` → `em_qualificacao`
Quando o lead volta a escrever, pelo mesmo ponto de `process_message`.

### 13.10 Regras importantes
- `agendado` tem precedência operacional sobre `qualificado`;
- `inativo` não significa perda definitiva, apenas ausência de tração recente;
- o status deve refletir o estágio atual do funil, não um histórico completo de estados.

### 13.11 Histórico de mudanças
Na POC, **não será criada ainda uma tabela específica de histórico de status/score**.

As mudanças serão refletidas no estado atual do lead e inferidas, quando necessário, por:
- histórico de mensagens;
- agendamentos;
- tentativas de follow-up;
- timestamps do próprio lead.

Se a solução evoluir, uma tabela de histórico de status/score poderá ser introduzida depois.

### 13.12 Impacto no dashboard

O dashboard deve usar:
- `score` para ordenação e priorização;
- `status` para filtros operacionais;
- `score >= 7` para KPI de leads quentes.

### 13.13 Impacto no follow-up

Cada régua tem um `status_alvo`, e é o status que escolhe a régua:

- `novo` → lead novo sem resposta (2 h de silêncio);
- `em_qualificacao` → qualificação interrompida (6 h);
- `qualificado` → pós-envio de imóveis (24 h);
- `agendado` → pós-agendamento, até 24 h antes do compromisso.

`inativo` não está em régua nenhuma: é o status que faz o follow-up parar.

---

## 14. Decisões adiadas

1. histórico de mudanças de score/status.

---

## 15. Relação com o código

A modelagem descrita aqui é a que existe: modelos em `src/db/models.py`, schemas
Pydantic em `src/schemas/` — que a suíte confere contra o ORM em
`tests/test_schemas.py` — e o schema físico na migration única
`29abbb20023f_schema_inicial.py`.
