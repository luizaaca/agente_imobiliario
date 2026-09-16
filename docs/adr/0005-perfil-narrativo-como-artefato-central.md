# ADR 0005 — Tratar `perfil_narrativo` como artefato central do SDR

- **Status:** Aceito
- **Data:** 2026-09-16

## Contexto

Campos estruturados tradicionais não capturam bem nuances importantes do atendimento imobiliário, como:
- objeções específicas;
- preferências implícitas;
- contexto familiar e motivacional;
- rejeições de imóveis com motivo.

A proposta da POC é que o valor do SDR não esteja apenas em responder, mas em entregar contexto acionável ao corretor.

## Decisão

Adotar um campo textual incremental chamado **`perfil_narrativo`** como artefato central do SDR, atualizado ao longo da conversa e reutilizado como contexto do agente e insumo para o corretor.

## Alternativas consideradas

### 1. Apenas campos estruturados
- **Prós:** simplicidade e facilidade de consulta.
- **Contras:** perda de nuances importantes.

### 2. Apenas histórico bruto de mensagens
- **Prós:** fidelidade total.
- **Contras:** baixa usabilidade para corretor e para o próprio agente.

## Consequências

### Positivas
- melhora handover para o corretor;
- preserva contexto rico;
- aumenta qualidade do follow-up e da recomendação.

### Negativas
- exige governança para evitar crescimento descontrolado do texto;
- pode introduzir inconsistências se não houver estratégia de atualização.

## Impacto arquitetural

O agente deve receber o `perfil_narrativo` como contexto e atualizá-lo incrementalmente por tool dedicada.
