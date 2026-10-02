# Identidade de Canal e Estratégia de Conversa

**Objetivo:** registrar a decisão de negócio e de modelagem para identificar leads nos canais de conversa, e como ela se reflete em `lead_channel_identities`, `mensagens` e no follow-up.

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

### 2.2 Identidade do canal
O `chat_id` do Telegram **não é tratado como identidade definitiva da pessoa**.
É uma **identidade de canal vinculada a um lead**. O mesmo vale para o
simulador do Streamlit, onde cada conversa nova recebe um identificador
próprio.

### 2.3 Regra operacional
Quando uma mensagem chega por um canal (`LeadService.get_or_create_lead`):

1. o sistema procura a identidade de canal já conhecida para aquele par
   (`channel`, `external_chat_id`);
2. se encontrar, recupera o `lead_id` associado e atualiza `last_seen_at`;
3. se não encontrar, cria um **lead** em `novo`, com `canal_origem`, e a
   identidade como primária;
4. ao longo da conversa, dados informados pelo cliente enriquecem o cadastro do lead.

O corretor também pode ligar um lead a um canal pela aba **Canal** da ficha
(`LeadService.definir_identidade`) — é o que torna alcançável pelo follow-up
um lead criado à mão. O canal ligado passa a ser o primário.

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

## 4. Como isso está no banco

### 4.1 `leads`
Representa a pessoa/oportunidade comercial e o estado consolidado do
relacionamento. `canal_origem` guarda por onde ela chegou.

### 4.2 `lead_channel_identities`
Um vínculo entre um lead e um identificador externo de canal:

| Campo | Papel |
|---|---|
| `lead_id` | o lead dono da identidade |
| `channel` | `telegram`, `streamlit` |
| `external_user_id`, `external_chat_id` | identificadores no canal; o follow-up envia para o `external_chat_id` |
| `is_primary` | a identidade preferencial do lead para envio ativo |
| `created_at`, `last_seen_at` | quando surgiu e quando falou pela última vez |

Um lead pode ter mais de uma identidade; `get_primary_identity` escolhe a
primária, e na falta dela a mais antiga.

### 4.3 `mensagens`
O histórico é persistido por lead, com o canal de cada mensagem (`channel`),
o tipo (`chat`, `followup`, `system_notice`, `handover`), o status de envio e
um `metadata_json` — onde as chamadas de ferramenta guardam o que fizeram,
inclusive os imóveis apresentados.

### 4.4 Sessão/conversa
Não há entidade `conversation` / `session`: a conversa é o histórico do lead.

---

## 5. Consequência para o follow-up

O follow-up sai pela identidade primária do lead. Só se tenta enviar por
canal com envio ativo — hoje o Telegram (`src/channels/envio.py`). Num lead
do Streamlit, a mensagem gravada aparece no chat dele, e esse é o desfecho
normal, não uma falha. O bot do Telegram não consegue iniciar conversa com
quem nunca falou com ele, então vincular um `chat_id` a um lead criado à mão
só funciona se a pessoa já escreveu ao bot.

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
