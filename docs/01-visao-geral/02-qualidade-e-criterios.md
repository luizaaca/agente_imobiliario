# SDD Complementar — Qualidade, Critérios e Governança Técnica

**Complementa o [`01-plano-de-implementacao.md`](./01-plano-de-implementacao.md)**

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
| QP-01 | Tempo de resposta do chat simulador | turno de conversa em até **8s p95** em ambiente de demonstração; turno com busca segue QP-05 |
| QP-02 | Tempo de resposta do Telegram | mensagem de retorno em até **10s p95** |
| QP-03 | Consulta ao catálogo | cada `SELECT` sobre `imoveis` em até **2s p95**, com teto de 3s no `statement_timeout` |
| QP-04 | Dashboard | carregamento inicial em até **3s p95** com volume de dados da POC |
| QP-05 | Turno com busca | resposta em até **45s p95**, incluindo as requisições do agente de busca |

Os dois tempos de resposta medem coisas diferentes, e é por isso que são
metas separadas.

Um turno de conversa é uma ida ao provider, e cabe nos 8 segundos. Um turno com
busca são três idas do agente conversacional mais as do agente de busca, que
investiga o catálogo antes de responder — e cada consulta dele é uma ida a mais.
Medido em conversas reais: 28, 28, 36 e 40 segundos, dos quais 18 a 30 só na
busca.

O número é alto e é o que esta arquitetura entrega. A troca está registrada no
[ADR 0007](../06-decisoes/adr/0007-agente-de-busca-dedicado.md): a busca é uma
investigação, e não uma consulta única, e é ela que produz "não há
varanda gourmet em zona sul até 900 mil, mas há três com varanda e
churrasqueira" em vez de uma lista vazia.

`LLM_MODEL_BUSCA` é a alavanca de quem precisar do tempo menor: a busca pode
rodar num modelo mais rápido sem tocar no que escreve para o cliente.

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
| QS-02 | Controle de acesso | toda a UI protegida por autenticação obrigatória; o papel do usuário define quais menus aparecem, o que organiza a tela e não substitui autorização |
| QS-03 | Logs | não registrar tokens, senhas ou dados sensíveis desnecessários — por isso o `httpx` fica em `WARNING` no bot: em `INFO` ele grava a URL da API do Telegram, que carrega o token |
| QS-04 | Minimização de dados | armazenar apenas dados necessários para atendimento, qualificação e demonstração |
| QS-05 | SQL gerado por LLM | executado por role somente-leitura restrita a `imoveis`, em transação read-only com tempo limite |

### 3.4 Operabilidade

| ID | Requisito | Meta da POC |
|---|---|---|
| QO-01 | Logs estruturados | logs com `timestamp`, `level`, `event`, `lead_id` quando aplicável |
| QO-02 | Rastreabilidade | cada interação relevante deve ser correlacionável por `lead_id` |
| QO-03 | Diagnóstico | falhas de tool, banco e LLM devem ser distinguíveis nos logs |
| QO-04 | Deploy local | ambiente deve subir com `docker compose up --build`, com teto no log de cada container |

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
- **Métrica:** resposta em até **8s p95** num turno de conversa; turno com busca segue o QP-05

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
- **Resposta esperada:** o agente de busca reformula a consulta; não havendo nada, o retorno traz os números do catálogo — quantos existem do que foi pedido, qual o mais barato, em que bairros há
- **Métrica:** sem erro técnico; a resposta ao lead cita o que existe de verdade, sem oferecer outra coisa no lugar

### CQ-06 — Provider indisponível durante a busca
- **Fonte:** provider OpenAI-compatible fora do ar
- **Estímulo:** agente conversacional chama `buscar_imoveis`
- **Ambiente:** operação normal, catálogo disponível
- **Resposta esperada:** a tool monta filtros a partir da ficha estruturada do lead e consulta o catálogo sem LLM, devolvendo imóveis
- **Métrica:** a busca degrada em qualidade, não em disponibilidade — lista vazia por indisponibilidade do provider é falha

### CQ-07 — Instrução hostil no texto do lead
- **Fonte:** lead que escreve uma instrução dirigida ao sistema, que chega ao agente de busca pelo perfil narrativo
- **Estímulo:** tentativa de fazer o SQL gerado alcançar outra tabela
- **Ambiente:** operação normal
- **Resposta esperada:** a consulta é recusada pela validação ou pela role, o erro volta ao agente de busca como texto, e nenhum dado fora de `imoveis` é lido
- **Métrica:** zero leitura fora da tabela `imoveis`; a recusa aparece nos logs com o statement rejeitado

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
- O sistema deve retornar opções coerentes com o perfil informado.
- O sistema nunca deve trocar operação, tipo ou finalidade pedidos por outros.
- Preço, metragem e demais números apresentados devem vir do banco, nunca de texto gerado por modelo.
- Quando não houver aderência, deve informar o que o catálogo tem, com números.
- Imóvel já apresentado na conversa não deve voltar como novidade.

### 5.4 Follow-up
- O follow-up deve usar contexto do histórico e do `perfil_narrativo`.
- O sistema deve respeitar limite de tentativas por régua.
- O follow-up não deve ser disparado em duplicidade na mesma janela.

### 5.5 Agendamento
- O sistema só deve sugerir agendamento quando houver sinal mínimo de aderência/interesse.
- O agendamento deve ser persistido com data, tipo e observações — numa visita, com os imóveis que a pessoa quer ver e o ID de cada um.
- Cada lead tem no máximo um compromisso ativo; trocar de horário é remarcar.
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
- `LLM_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL` e chaves de autenticação não devem ser commitados;
- usar `.env.example` para documentação e `.env` local para execução.

---

## 7. Observabilidade

### 7.1 Eventos mínimos a registrar

| Evento mínimo | `event=` emitido |
|---|---|
| criação de lead | `lead_criado` |
| recebimento de mensagem | `mensagem_registrada` com `role=user` |
| resposta do agente | `mensagem_registrada` com `role=assistant` |
| execução de tool | `tool_iniciada` e `tool_finalizada` |
| falha de tool | `tool_finalizada` com `status=erro` |
| agendamento criado | `agendamento_criado` |
| follow-up disparado | `followup_processado`, `followup_tentativa_registrada` |
| erro de provider LLM | `llm_call_failed` |
| consumo de tokens/custo | `llm_usage_registrado` |

Nenhuma linha de log carrega o conteúdo da mensagem: o texto é dado pessoal e
o que se registra dele é só o tamanho (§6.2).

### 7.2 Campos nos logs

Toda linha emitida pela aplicação começa por `event=<nome>` e segue em pares
`chave=valor`, para ser filtrável com `grep` sem precisar de um coletor:

| Campo | Quando aparece |
|---|---|
| `timestamp`, `level` | sempre, postos pelo `logging` |
| `event` | sempre |
| `lead_id` | sempre que a operação tem um lead |
| `channel` | nas operações de conversa |
| `correlation_id` | amarra as tools de um turno à chamada que as disparou |
| `tool_name` | nas execuções de tool |
| `status` | `ok` ou `erro`, nas operações que podem falhar |
| `duracao_ms` | nas execuções de tool |
| `tipo_erro` | classe da exceção, quando houve falha |

### 7.3 Métricas operacionais mínimas

Todas visíveis no dashboard do corretor:

| Métrica | Onde aparece |
|---|---|
| total de leads | KPI no topo |
| leads por status | KPIs de leads quentes e inativos, e filtro de status da lista |
| follow-ups disparados | KPI no topo, contando as tentativas que geraram mensagem — uma geração que falhou fica registrada para o teto da régua, mas não entra; o *tooltip* separa quantas saíram por um canal com envio ativo |
| agendamentos criados | KPI no topo |
| taxa de erro do agente | painel **Consumo de LLM**, sobre as chamadas do dia |
| custo/token por dia | painel **Consumo de LLM**, por dia e por mês |
| tempo médio de resposta | painel **Consumo de LLM**, média das chamadas bem-sucedidas do dia |

Taxa de erro e tempo médio aparecem como `—` enquanto não houve chamada
nenhuma no dia: um zero afirmaria que está tudo bem quando nada foi
exercitado.

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

- Estratégia do agente: [`02-estrategia-de-agente-e-tools.md`](../02-arquitetura/02-estrategia-de-agente-e-tools.md)
- Modelagem de dados: [`01-modelagem-logica-do-banco.md`](../04-dados/01-modelagem-logica-do-banco.md)
- Infraestrutura: [`01-infraestrutura-e-deploy.md`](../03-operacao/01-infraestrutura-e-deploy.md)
- Autenticação: [`03-autenticacao-da-ui.md`](../03-operacao/03-autenticacao-da-ui.md)
- Custos LLM: [`04-governanca-de-custos-llm.md`](../03-operacao/04-governanca-de-custos-llm.md)
- ADRs: [`adr/`](../06-decisoes/adr/)
- Runtime: [`03-cenarios-de-runtime.md`](../02-arquitetura/03-cenarios-de-runtime.md)
- Contratos: [`04-contratos-das-tools.md`](../02-arquitetura/04-contratos-das-tools.md)
- Testes: [`01-estrategia-de-testes.md`](../05-engenharia/01-estrategia-de-testes.md)
- Rastreabilidade: [`02-matriz-de-rastreabilidade.md`](../05-engenharia/02-matriz-de-rastreabilidade.md)
