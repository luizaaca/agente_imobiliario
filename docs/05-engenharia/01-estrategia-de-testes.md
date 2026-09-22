# Estratégia de Testes

**Objetivo:** definir uma estratégia de testes pragmática para a POC, cobrindo os fluxos mais críticos com foco em confiança para demo, regressão mínima e validação de contratos.

---

## 1. Diretriz geral

Definir uma estratégia de testes pragmática para a POC, cobrindo os fluxos mais críticos sem transformar o projeto em um festival de mocks tristes e lágrimas de CI.

A meta é garantir:
- confiança para demo;
- regressão mínima dos cenários obrigatórios;
- validação dos contratos principais.

---

## 2. Pirâmide de testes proposta

### 2.1 Testes unitários
Cobrem:
- `CatalogService`
- `LeadService`
- `SchedulingService`
- `FollowUpService`
- cálculo de score
- regras de elegibilidade de follow-up

### 2.2 Testes de contrato
Cobrem:
- inputs e outputs das tools do agente;
- schemas Pydantic;
- serialização e persistência dos principais modelos.

### 2.3 Testes de integração
Cobrem:
- services + PostgreSQL;
- fluxo agente → tool → banco;
- scheduler → follow-up service;
- dashboard lendo dados persistidos.

### 2.4 Testes ponta a ponta / roteiros de validação
Cobrem os 3 cenários obrigatórios do desafio.

---

## 3. Escopo mínimo por componente

### 3.1 Catálogo
- filtro por faixa de preço;
- filtro por bairro/região;
- filtro por quartos;
- ranking textual básico;
- comportamento sem resultados.

### 3.1b Agente de busca
- pedido em texto livre que resulta em imóveis aderentes;
- o que foi pedido não é trocado por outra coisa: galpão não volta como sala comercial;
- imóvel já apresentado na conversa não volta como novidade;
- provider fora do ar: a busca degrada para o caminho sem LLM e ainda devolve imóveis;
- os números do retorno conferem com o banco, e não com o texto do modelo;
- contenção do SQL: comando que não é `SELECT`, tabela fora de `imoveis`, múltiplos statements e consulta sem `LIMIT`;
- o consumo é registrado com `operation="busca"`, separado do turno de conversa.

### 3.2 Qualificação e score
- atualização de campos estruturados;
- transição de status;
- cálculo de score com critérios explícitos;
- mudança de intenção no meio da conversa.

### 3.3 Follow-up
- elegibilidade por régua;
- bloqueio por limite de tentativas;
- prevenção de duplicidade;
- geração contextual com histórico.

### 3.4 Agendamento
- criação válida;
- rejeição de payload inválido;
- atualização de status do lead quando aplicável.

### 3.5 Resumo do corretor
- presença dos campos essenciais;
- coerência com score e perfil;
- utilidade prática para handover.

---

## 4. Estratégia para dependências externas

### 4.1 Provider LLM
- usar mock/fake em testes unitários e parte dos testes de integração;
- manter poucos testes manuais com provider real para validação final.

### 4.2 Telegram
- testar handlers com objetos simulados;
- não depender do bot real para a maior parte da suíte.

### 4.3 Banco de dados
- preferir banco PostgreSQL de teste para integração;
- isolar dados por fixture e rollback quando possível.

---

## 5. Casos obrigatórios de regressão

### T1 — Compra residencial
Dado um lead que busca apartamento na zona sul, o sistema deve:
- identificar intenção de compra;
- coletar orçamento, quartos, bairro e urgência;
- buscar imóveis aderentes;
- sugerir agendamento.

### T2 — Investimento
Dado um lead com intenção de investir, o sistema deve:
- mudar para perfil investidor;
- coletar ticket, objetivo de retorno e horizonte;
- sugerir oportunidades coerentes;
- direcionar para especialista.

### T3 — Follow-up automático
Dado um lead inativo antes do agendamento, o sistema deve:
- identificar elegibilidade;
- gerar mensagem contextual;
- registrar o follow-up;
- evitar duplicidade na mesma janela.

---

## 6. Critérios de saída para demo

Antes da demonstração, validar:
- os 3 cenários obrigatórios;
- persistência de leads, mensagens e agendamentos;
- dashboard exibindo dados coerentes;
- autenticação funcionando;
- tracking de custo habilitado;
- falha do provider LLM tratada de forma amigável.

---

## 7. Estrutura de testes

A suíte é plana, organizada por assunto e não por nível da pirâmide:

```text
tests/
├── conftest.py                        # banco de teste, schema por Alembic, TRUNCATE entre testes
│
│   # Serviços de domínio
├── test_catalog_service.py            # filtros, escada de relaxamento, diagnóstico, FTS
├── test_busca_e_ordem.py              # ordenação e desempate
├── test_consulta_catalogo.py          # contenção do SQL gerado por LLM e a role somente-leitura
├── test_lead_service.py               # qualificação, status, histórico
├── test_lead_crud.py                  # operações da ficha
├── test_scheduling_service.py
├── test_followup_service.py
├── test_llm_usage_service.py          # tetos, custo, latência, taxa de erro
│
│   # Agente e tools, com modelo falso
├── test_agent_tools.py                # contrato de cada tool
├── test_busca_agent.py                # agente de busca e memória do que já mostrou
├── test_busca_pela_conversa.py        # busca acionada pelo agente, e os números do banco
├── test_agendamento_pela_conversa.py  # marcar, confirmar, cancelar pela conversa
├── test_contato_do_lead.py
├── test_contexto_do_lead.py
├── test_perfil_narrativo.py           # consolidador e caminho de degradação
├── test_prompt_chega_ao_modelo.py
├── test_provider.py                   # configuração ausente, provider custom
├── test_cenarios.py                   # os casos obrigatórios de regressão da seção 5
├── test_followup_manual.py
│
│   # UI e schemas
├── test_papeis.py                     # visibilidade de menu por papel
├── test_menu_e_chat.py
├── test_selo_de_status.py
├── test_texto_ui.py
├── test_aviso_de_budget.py
└── test_schemas.py
```

A pirâmide da seção 2 descreve **o que cada teste faz**, não onde o arquivo
mora. Como todo teste roda contra um PostgreSQL de verdade (seção 4.3), a
fronteira entre unitário e integração não cai em diretório: `test_lead_service.py`
tem os dois, e separá-los espalharia o mesmo assunto por duas pastas.

Nomear por assunto é o que faz uma falha apontar para onde olhar. Um arquivo
chamado `test_agent_db_flow.py` não diz que comportamento quebrou.

---

## 8. Métricas mínimas de qualidade para a POC

- serviços críticos com testes unitários cobrindo regras principais;
- tools principais com testes de contrato;
- 3 cenários obrigatórios validados;
- zero falhas conhecidas bloqueantes para demo.
