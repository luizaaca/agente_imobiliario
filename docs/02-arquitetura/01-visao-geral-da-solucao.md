# Visão Geral da Solução

Este documento funciona como índice arquitetural curto da solução e aponta para os documentos detalhados por tema.

---

## 1. Objetivo

Organizar a documentação técnica da POC em uma estrutura estável, navegável e orientada por assunto.

---

## 2. Mapa arquitetural

- Estratégia do agente e tools: [`02-estrategia-de-agente-e-tools.md`](./02-estrategia-de-agente-e-tools.md)
- Cenários de runtime: [`03-cenarios-de-runtime.md`](./03-cenarios-de-runtime.md)
- Contratos das tools: [`04-contratos-das-tools.md`](./04-contratos-das-tools.md)
- Modelagem de dados: [`../04-dados/01-modelagem-logica-do-banco.md`](../04-dados/01-modelagem-logica-do-banco.md)
- Decisões arquiteturais: [`../06-decisoes/adr/`](../06-decisoes/adr/)

---

## 3. Princípios estruturantes

- canais são adaptadores;
- agente orquestra a conversa;
- services concentram regras de negócio;
- persistência fica desacoplada da interface;
- follow-up é controlado por serviço de domínio, com uso pontual de LLM para composição textual.

---

## 4. Relação com o plano principal

O plano completo de execução permanece em [`../01-visao-geral/01-plano-de-implementacao.md`](../01-visao-geral/01-plano-de-implementacao.md).