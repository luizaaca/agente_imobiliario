# Decisão de Identidade de Canal e Conversa — POC

**Objetivo:** registrar a decisão de negócio e modelagem para identificar leads no Telegram e orientar as próximas lacunas de modelagem (`mensagens`, sessão/conversa e identidade de canal).

---

## 1. Problema

Na POC, o sistema precisa responder a perguntas como:

- como identificar que uma nova mensagem do Telegram pertence ao mesmo cliente?
- o histórico deve ser vinculado ao chat, à pessoa ou aos dois?
- quando criar uma nova lead e quando reutilizar uma existente?
- como evitar acoplamento excessivo entre identidade da pessoa e identidade do canal?

Essas decisões impactam diretamente:
- a modelagem de `mensagens`;
- a necessidade (ou não) de uma entidade `conversation` nesta fase;
- a modelagem de identidade de canal;
- a estratégia futura de merge de leads duplicadas.

---

## 2. Decisão adotada para a POC

### 2.1 Entidade principal de negócio
A entidade principal de negócio continua sendo o **`Lead`**.

### 2.2 Identidade do Telegram
O `telegram_chat_id` **não será tratado como identidade definitiva da pessoa**.

Na POC, ele será tratado como uma **identidade de canal vinculada a um lead**.

### 2.3 Regra operacional
Quando uma mensagem chegar do Telegram:

1. o sistema procura uma identidade de canal já conhecida para aquele `telegram_chat_id`;
2. se encontrar, recupera o `lead_id` associado;
3. se não encontrar, cria um **lead provisório** e vincula o canal a esse lead;
4. ao longo da conversa, dados informados pelo cliente enriquecem o cadastro do lead.

### 2.4 Histórico
O histórico de mensagens deve ser persistido **por lead**, com rastreabilidade do canal de origem.

### 2.5 Duplicidade
A POC aceita que um mesmo cliente possa gerar leads duplicadas em cenários como:
- troca de conta/chat;
- uso de múltiplos canais;
- ausência de dados suficientes para reconciliação.

A resolução de duplicidade fica como capacidade futura de **merge manual ou assistido**, não como requisito obrigatório da POC.

---

## 3. O que esta decisão evita

Esta decisão evita dois extremos ruins:

### 3.1 Evita acoplar pessoa = chat
Não tratamos `telegram_chat_id` como se fosse a identidade definitiva do cliente.

### 3.2 Evita complexidade excessiva cedo demais
Não introduzimos, neste momento, uma modelagem completa de sessão/conversa multi-thread com reconciliação automática sofisticada.

---

## 4. Consequências para a modelagem

### 4.1 `Lead`
A tabela `leads` continua representando a pessoa/oportunidade comercial.

### 4.2 Identidade de canal
A POC deve prever uma entidade específica para identidade de canal, em vez de depender apenas de um campo solto em `leads`.

### 4.3 `Mensagens`
A tabela `mensagens` deverá ser enriquecida para registrar:
- o canal de origem;
- a identidade de canal associada;
- metadados mínimos de rastreabilidade.

### 4.4 Sessão/conversa
A criação de uma entidade explícita `conversation` / `session` fica **adiada** nesta fase, salvo se a modelagem de `mensagens` mostrar necessidade imediata.

---

## 5. Modelo conceitual recomendado para a POC

### 5.1 `Lead`
Representa a oportunidade comercial e o estado consolidado do relacionamento.

### 5.2 `LeadChannelIdentity` (nome conceitual)
Representa um vínculo entre um lead e um identificador externo de canal.

Campos conceituais sugeridos:
- `id`
- `lead_id`
- `channel`
- `external_user_id` ou `external_chat_id`
- `is_primary`
- `created_at`
- `last_seen_at`

### 5.3 `Mensagem`
Representa uma mensagem persistida no histórico, vinculada ao lead e rastreável por canal.

---

## 6. Regras de negócio mínimas da POC

### 6.1 Criação de lead
- se não houver identidade de canal conhecida, criar lead provisório;
- o lead pode começar com poucos dados.

### 6.2 Enriquecimento progressivo
- nome, telefone, intenção, localização e preferências podem ser preenchidos ao longo da conversa;
- o `perfil_narrativo` continua sendo o artefato principal de contexto.

### 6.3 Busca de lead existente por dados informados
Essa capacidade pode existir, mas **não é obrigatória como fluxo principal da POC**.

### 6.4 Merge de duplicados
- não será automático na POC;
- pode ser tratado futuramente por ação manual ou assistida.

---

## 7. Decisão sobre sessão/conversa nesta fase

### Decisão
**Não criar, por enquanto, uma entidade obrigatória de `conversation` / `session`.**

### Justificativa
Para a POC, a combinação abaixo é suficiente:
- `Lead` como entidade principal;
- identidade de canal separada;
- histórico de mensagens persistido com rastreabilidade de canal.

### Evolução futura possível
Se a solução evoluir para:
- múltiplos canais simultâneos;
- múltiplas threads por lead;
- auditoria mais sofisticada;
- retomadas independentes por contexto;

então uma entidade `conversation` poderá ser introduzida depois.

---

## 8. Decisão resumida

Para a POC:

- **Lead = entidade principal de negócio**
- **Telegram chat = identidade de canal vinculada ao lead**
- **Histórico = persistido por lead com rastreabilidade de canal**
- **Sessão/conversa explícita = adiada nesta fase**
- **Merge de duplicados = futuro, não obrigatório agora**

---

## 9. Próximos impactos documentais

Esta decisão deve orientar as próximas lacunas:

1. enriquecer `mensagens`;
2. modelar identidade de canal;
3. decidir se `conversation_id` entra agora ou não;
4. modelar tentativas de follow-up sem confundir tentativa operacional com mensagem.
