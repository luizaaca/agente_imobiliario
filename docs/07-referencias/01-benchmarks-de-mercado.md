# Benchmarks de Mercado

**Objetivo:** registrar as referências de mercado que informaram as decisões de design da prova de conceito e explicitar os padrões convergentes incorporados à solução.

---

## 1. Contexto

A arquitetura e as decisões de design deste projeto foram informadas pela análise de três plataformas comerciais que atuam como SDR imobiliário com IA no Brasil. Embora a prova de conceito não tenha a mesma amplitude dessas ferramentas, compreender o estado da arte orientou escolhas críticas — especialmente a adoção do `perfil_narrativo` como artefato central.

---

## 2. Análise de Plataformas

### Lais.ai (Lastro)
- **Site:** [lais.ai](https://lais.ai)
- **Escala:** 1.000+ clientes, 5M+ pessoas atendidas, 150+ integrações com CRMs imobiliários.
- **Financiamento:** Série A de R$ 85M liderada pela Prosus (Canary, QED Investors, FJ Labs).
- **Relevância para o projeto:** Referência em qualificação progressiva via conversa natural, resumo executivo gerado por IA com pontos-chave/objeções/rejeições, integração em tempo real com catálogo de imóveis, e réguas de follow-up contextuais (não genéricas). Possui módulo DataLais de inteligência de mercado agregada.

### Maya (Plaza Technologies)
- **Site:** [useplaza.com.br](https://useplaza.com.br)
- **Fundadores:** Julio Viana (ex-InfoProp/Grupo ZAP), Pedro de Cicco, Vicente Alencar Jr.
- **Financiamento:** Pre-seed de R$ 5,5M (Magma Partners, Latitud).
- **Relevância para o projeto:** Referência em dossier de lead enviado diretamente via WhatsApp ao corretor (nome, telefone, orçamento, imóvel de interesse, link para conversa completa), matching em tempo real com portfólio, e Plaza Score com análise de crédito integrada (Serasa/BigDataCorp). Possui módulo Maya ADM para operações pós-locação.

### Squad (Inner AI)
- **Site:** [squad.com](https://squad.com)
- **Fundadores:** Pedro Salles Leite (ex-CTO QuintoAndar), Eduardo Mitelman.
- **Financiamento:** Seed de R$ 42M+, valuation de R$ 500M.
- **Relevância para o projeto:** Referência em arquitetura multi-agente com memória compartilhada ("Digital Employees"), CRM embutido com pipeline visual, follow-up autônomo e proativo com réguas por etapa do funil, e "Sales Coach" que audita diálogos e aponta pendências.

---

## 3. Padrões convergentes adotados na POC

As três plataformas convergem em práticas que orientaram diretamente o design desta solução:

| Padrão | Como foi incorporado |
|---|---|
| Qualificação progressiva e contextual | Estratégia conversacional do agente (agora em [`02-estrategia-de-agente-e-tools.md`](../02-arquitetura/02-estrategia-de-agente-e-tools.md)) |
| Perfil textual rico gerado pela LLM | Campo `perfil_narrativo` no schema do lead (agora em [`01-modelagem-logica-do-banco.md`](../04-dados/01-modelagem-logica-do-banco.md)) |
| Rejeições como dado valioso | Captura de objeções e imóveis descartados no perfil narrativo |
| Dossier como produto principal do SDR | Destaque do perfil narrativo no dashboard (Fase 5) |
| Follow-up contextual com réguas por etapa | Réguas diferenciadas na Fase 4 |
| Scoring transparente | Critérios explícitos na Fase 3 |
