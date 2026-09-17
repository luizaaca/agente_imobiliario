# SDD Complementar — Qualidade, Critérios e Governança Técnica

**Complementa o [`PLANO_DE_IMPLEMENTACAO.md`](./PLANO_DE_IMPLEMENTACAO.md)**

---

## 1. Objetivo deste documento

Este documento complementa o plano principal com os elementos de especificação técnica que normalmente faltam em planos de alto nível:

- requisitos não funcionais;
- critérios de aceite mensuráveis;
- diretrizes de segurança e privacidade;
- observabilidade;
- governança de custos e operação;
- critérios de pronto para a POC.

A proposta é manter a documentação **enxuta, objetiva e executável**, seguindo boas práticas modernas de arquitetura e engenharia de software.

---

## 2. Escopo desta especificação complementar

Este documento cobre os aspectos transversais da solução:

- qualidade do sistema;
- comportamento esperado em cenários críticos;
- limites operacionais da POC;
- critérios de validação.

Não substitui os subplanos de agente, modelagem, infraestrutura, autenticação e custos; ele os organiza sob a ótica de **qualidade e engenharia**.

---

## 3. Requisitos de qualidade

### 3.1 Performance

| ID | Requisito | Meta da POC |
|---|---|---|
| QP-01 | Tempo de resposta do chat simulador | resposta inicial em até **8s p95** em ambiente de demonstração |
| QP-02 | Tempo de resposta do Telegram | mensagem de retorno em até **10s p95** |
| QP-03 | Busca de imóveis | consulta estruturada + ranking textual em até **2s p95** para base de demonstração |
| QP-04 | Dashboard | carregamento inicial em até **3s p95** com volume de dados da POC |

### 3.2 Confiabilidade

| ID | Requisito | Meta da POC |
|---|---|---|
| QC-01 | Falha do provider LLM não deve derrubar a aplicação | erro tratado com mensagem amigável e log estruturado |
| QC-02 | Persistência de mensagens e leads | nenhuma interação confirmada ao usuário pode ser perdida sem registro de erro |
| QC-03 | Scheduler de follow-up | execução idempotente por janela, evitando duplicidade de follow-up |
| QC-04 | Inicialização dos processos | Streamlit e bot devem subir independentemente; falha de um não deve corromper o banco |

### 3.3 Segurança e privacidade

| ID | Requisito | Meta da POC |
|---|---|---|
| QS-01 | Segredos | todas as credenciais devem vir de `.env` ou variáveis de ambiente |
| QS-02 | Controle de acesso | dashboard protegido por autenticação obrigatória |
| QS-03 | Logs | não registrar tokens, senhas ou dados sensíveis desnecessários |
| QS-04 | Minimização de dados | armazenar apenas dados necessários para atendimento, qualificação e demonstração |

### 3.4 Operabilidade

| ID | Requisito | Meta da POC |
|---|---|---|
| QO-01 | Logs estruturados | logs com `timestamp`, `level`, `event`, `lead_id` quando aplicável |
| QO-02 | Rastreabilidade | cada interação relevante deve ser correlacionável por `lead_id` |
| QO-03 | Diagnóstico | falhas de tool, banco e LLM devem ser distinguíveis nos logs |
| QO-04 | Deploy local | ambiente deve subir com `docker-compose up --build` |

### 3.5 Testabilidade

| ID | Requisito | Meta da POC |
|---|---|---|
| QT-01 | Serviços de domínio | devem ser testáveis sem UI |
| QT-02 | Tools do agente | devem possuir testes de contrato |
| QT-03 | Regressão dos cenários obrigatórios | os 3 cenários do desafio devem ter validação automatizada ou roteiro reproduzível |
| QT-04 | Dependências externas | provider LLM e Telegram devem poder ser mockados |

### 3.6 Custo

| ID | Requisito | Meta da POC |
|---|---|---|
| QK-01 | Limite por conversa | respeitar teto configurável de tokens/turnos |
| QK-02 | Limite diário | bloquear ou degradar graciosamente ao atingir orçamento diário |
| QK-03 | Observabilidade de custo | registrar consumo por interação e por lead |

---

## 4. Cenários de qualidade mensuráveis

### CQ-01 — Resposta sob uso normal
- **Fonte:** lead no chat Streamlit
- **Estímulo:** envia mensagem de qualificação inicial
- **Ambiente:** ambiente local de demonstração com banco populado
- **Resposta esperada:** sistema persiste a mensagem, consulta contexto e responde
- **Métrica:** resposta em até **8s p95**

### CQ-02 — Falha do provider LLM
- **Fonte:** provider OpenAI-compatible indisponível
- **Estímulo:** agente tenta gerar resposta
- **Ambiente:** operação normal
- **Resposta esperada:** sistema registra erro, não quebra a sessão e retorna mensagem amigável ao usuário
- **Métrica:** erro tratado sem crash do processo

### CQ-03 — Follow-up duplicado
- **Fonte:** scheduler executado duas vezes na mesma janela
- **Estímulo:** lead elegível para follow-up
- **Ambiente:** operação normal
- **Resposta esperada:** no máximo um follow-up por janela/regra
- **Métrica:** zero duplicidade para mesma régua e janela temporal

### CQ-04 — Crescimento de contexto conversacional
- **Fonte:** conversa longa com múltiplas preferências e objeções
- **Estímulo:** lead troca várias mensagens
- **Ambiente:** operação normal
- **Resposta esperada:** `perfil_narrativo` é atualizado sem perder coerência e sem explodir custo
- **Métrica:** atualização incremental + respeito aos limites configurados

### CQ-05 — Busca sem aderência
- **Fonte:** lead com critérios muito restritivos
- **Estímulo:** tool `buscar_imoveis`
- **Ambiente:** base de imóveis da POC
- **Resposta esperada:** sistema informa ausência de aderência e conduz a refinamento de critérios
- **Métrica:** sem erro técnico; resposta útil ao usuário

---

## 5. Critérios de aceite por capacidade

### 5.1 Atendimento conversacional
- O agente deve responder em tom consultivo e profissional.
- O agente não deve despejar questionário completo em uma única mensagem.
- O agente deve sempre buscar a próxima pergunta mais útil.
- O agente deve registrar histórico da conversa.

### 5.2 Qualificação de lead
- O sistema deve capturar ao menos: intenção, faixa de orçamento, localização e urgência quando possível.
- O status do lead deve evoluir conforme a completude e o engajamento.
- O score deve ser explicável no resumo do corretor.

### 5.3 Recomendação de imóveis
- O sistema deve usar filtros estruturados antes do ranking textual.
- O sistema deve retornar opções coerentes com o perfil informado.
- Quando não houver aderência, deve sugerir refinamento de critérios.

### 5.4 Follow-up
- O follow-up deve usar contexto do histórico e do `perfil_narrativo`.
- O sistema deve respeitar limite de tentativas por régua.
- O follow-up não deve ser disparado em duplicidade na mesma janela.

### 5.5 Agendamento
- O sistema só deve sugerir agendamento quando houver sinal mínimo de aderência/interesse.
- O agendamento deve ser persistido com data, tipo e observações.
- O corretor deve conseguir visualizar o agendamento no dashboard.

### 5.6 Resumo para corretor
- O resumo deve conter: perfil, intenção, score, preferências, objeções e próximos passos.
- O resumo deve ser útil para handover humano, não apenas uma transcrição da conversa.

---

## 6. Segurança, privacidade e LGPD mínima para a POC

### 6.1 Dados pessoais tratados
A POC pode tratar os seguintes dados:
- nome;
- telefone ou identificador do canal;
- preferências imobiliárias;
- histórico de mensagens;
- agendamentos.

### 6.2 Princípios mínimos
- coletar apenas o necessário para atendimento e demonstração;
- evitar registrar dados sensíveis desnecessários em texto livre;
- não expor dados pessoais em logs ou prints de erro;
- restringir acesso ao dashboard a usuários autenticados.

### 6.3 Retenção e descarte
Para a POC:
- os dados podem ser mantidos durante o ciclo do projeto e demonstração;
- deve existir possibilidade técnica de exclusão manual de leads para limpeza do ambiente;
- em produção futura, a política de retenção deverá ser formalizada.

### 6.4 Segredos
- `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL` e chaves de autenticação não devem ser commitados;
- usar `.env.example` para documentação e `.env` local para execução.

---

## 7. Observabilidade

### 7.1 Eventos mínimos a registrar
- criação de lead;
- recebimento de mensagem;
- resposta do agente;
- execução de tool;
- falha de tool;
- agendamento criado;
- follow-up disparado;
- erro de provider LLM;
- consumo de tokens/custo.

### 7.2 Campos recomendados nos logs
- `timestamp`
- `level`
- `event`
- `lead_id`
- `channel`
- `conversation_id` (quando existir)
- `tool_name` (quando aplicável)
- `status`
- `error_type` (quando aplicável)

### 7.3 Métricas operacionais mínimas
- total de leads;
- leads por status;
- follow-ups disparados;
- agendamentos criados;
- taxa de erro do agente;
- custo/token por dia;
- tempo médio de resposta.

---

## 8. Critérios de pronto da POC

A POC será considerada pronta quando:

1. os 3 cenários obrigatórios puderem ser demonstrados ponta a ponta;
2. leads, mensagens e agendamentos forem persistidos no PostgreSQL;
3. o dashboard exibir leads, score, resumo e agendamentos;
4. o follow-up automático ou manual funcionar com contexto;
5. houver autenticação no dashboard;
6. o consumo de LLM estiver sendo rastreado;
7. o ambiente puder ser executado localmente com documentação mínima.

---

## 9. Itens explicitamente fora do escopo da POC

- integração com CRM real;
- agenda externa real;
- multiusuário corporativo com RBAC completo;
- observabilidade enterprise completa;
- alta disponibilidade real em produção;
- busca vetorial em produção;
- compliance LGPD completo com processos jurídicos e operacionais.

---

## 10. Relação com outros documentos

- Estratégia do agente: [`SUB_PLANO_AGENTE.md`](./SUB_PLANO_AGENTE.md)
- Modelagem de dados: [`docs/database_logical_model.md`](./docs/database_logical_model.md)
- Infraestrutura: [`SUB_PLANO_INFRA.md`](./SUB_PLANO_INFRA.md)
- Autenticação: [`SUB_PLANO_AUTENTICACAO.md`](./SUB_PLANO_AUTENTICACAO.md)
- Custos LLM: [`SUB_PLANO_CUSTOS_LLM.md`](./SUB_PLANO_CUSTOS_LLM.md)
- ADRs: [`docs/adr/`](./docs/adr/)
- Runtime: [`docs/runtime_scenarios.md`](./docs/runtime_scenarios.md)
- Contratos: [`docs/tool_contracts.md`](./docs/tool_contracts.md)
- Testes: [`docs/test_strategy.md`](./docs/test_strategy.md)
- Rastreabilidade: [`docs/traceability_matrix.md`](./docs/traceability_matrix.md)
