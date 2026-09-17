# Sub-plano: Modelagem de Dados

**Referenciado pelo [PLANO_DE_IMPLEMENTACAO.md](./PLANO_DE_IMPLEMENTACAO.md)**

---

## 1. Entidades principais

> **Complemento importante:** a modelagem lógica detalhada de persistência, incluindo tipos SQL, constraints, índices, identidade de canal, enriquecimento de `mensagens`, tentativas de follow-up, score e status, está em [docs/database_logical_model.md](docs/database_logical_model.md).

> A decisão de negócio/modelagem para identidade de canal e a ausência deliberada de uma entidade explícita de `conversation` / `session` na POC está em [docs/channel_identity_and_conversation_decision.md](docs/channel_identity_and_conversation_decision.md).

### Lead
- `id`
- `nome`
- `telefone`
- `status`
- `intencao`
- `tipologia_interesse` — apto, casa, studio, lote, cobertura, comercial
- `orcamento_min`
- `orcamento_max`
- `forma_pagamento` — à vista, financiamento, FGTS, permuta
- `regiao_interesse`
- `bairro_interesse`
- `quartos`
- `urgencia`
- `motivo_busca` — mudança, investimento, casamento, expansão familiar, etc.
- `perfil` (`residencial`, `investidor`)
- `canal_origem` — portal, meta_ads, site, organico, indicação
- `amenidades_desejadas` — pets, piscina, varanda, elevador, academia
- `score`
- `perfil_narrativo` — **campo TEXT rico e evolutivo, gerado e atualizado pela LLM** (ver detalhamento abaixo)
- `resumo` — briefing executivo final para o corretor
- `created_at`
- `updated_at`

### Mensagem
- `id`
- `lead_id`
- `role` (`user`, `assistant`, `system`, `tool`)
- `content`
- `timestamp`

### Agendamento
- `id`
- `lead_id`
- `tipo` (`visita`, `reuniao`)
- `data_hora`
- `observacoes`
- `status`

### Imóvel (Tabela PostgreSQL / Dataset)
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

---

## 2. Enums recomendados
- `LeadStatus`: `novo`, `em_qualificacao`, `qualificado`, `agendado`, `inativo`
- `LeadIntent`: `compra`, `aluguel`, `investimento`
- `Urgencia`: `baixa`, `media`, `alta`

---

## 3. O campo `perfil_narrativo`: o produto principal do SDR

Inspirado nas práticas das principais ferramentas de mercado (Lais.ai, Maya/Plaza, Squad/Inner AI), o schema do Lead inclui um campo textual narrativo **escrito e mantido pela LLM** ao longo da conversa.

**O que é:** Um texto estruturado em blocos semânticos que acumula tudo que se sabe sobre o lead — incluindo nuances que campos estruturados não capturam: objeções ("achou a cozinha do AP-007 pequena"), preferências implícitas, imóveis rejeitados com motivo, contexto de vida e próximos passos sugeridos.

### Exemplo ilustrativo:

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

### Distinção entre `perfil_narrativo` e `resumo`:

| Aspecto | `perfil_narrativo` | `resumo` |
|---|---|---|
| **Quando é gerado** | Progressivamente, a cada interação significativa | No final da qualificação ou sob demanda |
| **Quem consome** | O próprio agente (como contexto) + corretor | O corretor como briefing executivo |
| **Tamanho típico** | Médio-longo (300-800 palavras) | Curto-médio (100-300 palavras) |
| **Conteúdo** | Tudo que se sabe, com nuances e objeções | Síntese: perfil, score, recomendação e próximos passos |
| **Atualização** | Contínua (incremental) | Pontual (snapshot) |
