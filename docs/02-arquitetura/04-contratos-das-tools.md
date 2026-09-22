# Contratos das Tools do Agente

**Objetivo:** definir os contratos funcionais das tools expostas ao agente SDR, incluindo responsabilidades, entradas, saídas, efeitos colaterais e erros tratáveis.

---

## 1. Princípios gerais

Todas as tools devem seguir os princípios abaixo:

- responsabilidade única;
- input validado por schema;
- retorno estruturado;
- efeitos colaterais explícitos;
- erros previsíveis e tratáveis;
- logs com contexto suficiente para auditoria.

O agente decide **quando** chamar uma tool; a tool define **como** executar a operação com segurança.

**`lead_id` não é parâmetro de nenhuma tool.** Ele vem das dependências do run
(`ctx.deps.lead_id`), fixadas pelo canal ao montar o turno. O modelo não tem
como apontar uma tool para outro lead, nem por engano nem por injeção de
prompt: escrever num lead que não é o da conversa simplesmente não é
expressável. O mesmo vale para o canal.

---

## 2. `buscar_imoveis`

### Objetivo
Entregar ao agente de busca o que a pessoa procura e devolver os imóveis
escolhidos. É o instrumento de qualificação do agente: mostrar imóvel é o que
faz a pessoa revelar orçamento, tamanho e bairro sem que ninguém pergunte.

### Input esperado
- `pedido` — até 400 caracteres, em texto livre, na linguagem em que a pessoa
  pediu. Tudo cabe aqui: o que ela quer, onde, por quanto, para quê, e o que
  ela já recusou.

É o único parâmetro. O agente conversacional não traduz o pedido para filtros,
não escolhe ordenação e não decide quantos imóveis quer — essas são decisões de
quem busca, tomadas com o catálogo à vista.

### Output esperado
- a ficha de cada imóvel escolhido, com ID, preço, metragem, quartos, suítes,
  banheiros e vagas; o condomínio, quando cadastrado, somado ao aluguel para
  virar o custo do mês e posto ao lado do preço de venda, onde não se soma;
- **a descrição inteira**, sem abreviar. É ali que estão o lazer do condomínio,
  o acabamento e a distância da estação — o que faz alguém querer ver o imóvel,
  e o que responde a pergunta seguinte. As 300 descrições do catálogo têm entre
  284 e 515 caracteres; qualquer corte cabível deixaria de fora a parte que
  vende;
- uma linha de justificativa por imóvel, escrita pelo agente de busca;
- quando o pedido exato não tinha resposta, a frase em português do que
  precisou mudar;
- quando não há nada, o diagnóstico do catálogo (ver abaixo).

Os números vêm do banco, relidos por ID e formatados em código. A justificativa
é do agente de busca. Nenhum valor monetário no retorno foi escrito por um
modelo.

### Efeitos colaterais
- uma ou mais chamadas ao provider, registradas em `llm_usage` com
  `operation="busca"`;
- os IDs apresentados são gravados no `metadata_json` da mensagem da tool, de
  onde `detalhar_imoveis` os relê, e entram também no cache da conversa (ver abaixo);
- o rastro das consultas do agente de busca vai para o mesmo `metadata_json`,
  de onde a aba **Conversa** da ficha e o simulador o mostram num painel por
  chamada, fechado.

Nenhuma escrita no catálogo. A role usada pelo agente de busca não teria
permissão para isso.

### Regras
- nunca retornar imóveis incompatíveis de forma gritante apenas para “preencher lista”;
- ausência de resultado é resposta válida, não erro;
- imóvel já apresentado nesta conversa não volta como novidade;
- o que a pessoa procura não é trocado por outra coisa (ver abaixo).

### Erros tratáveis
- provider fora do ar ou resposta vazia — degrada para a busca estruturada, sem LLM;
- SQL inválido gerado pelo agente de busca — volta a ele como texto, para reescrever;
- falha de banco;
- catálogo indisponível.

### O que a busca nunca troca
`operacao`, `tipo` e `finalidade` não são negociáveis. A flexibilidade da busca
é de **lugar e condição** — outro bairro, teto 30% maior, sem exigir a vaga —,
nunca de trocar a coisa procurada por outra.

Isto veio de uma falha real: a pessoa pediu galpão e recebeu salas comerciais
apresentadas como se fossem o que ela tinha pedido.

Como `tipo` determina `finalidade` (não existe galpão residencial), pedir um
par contraditório não devolve lista vazia: devolve a contradição, para o agente
se corrigir.

A regra vale tanto para o agente de busca, nas instruções dele, quanto para o
caminho de degradação, onde é o `CatalogService` que a garante mantendo os três
fora da escada de relaxamento.

### Lista vazia é resposta, não erro
Quando não há nada, o retorno traz os números do catálogo: quantos existem do
que foi pedido, qual o mais barato, em que bairros há. É com eles que o agente
diz o que existe de verdade, em vez de pedir desculpa no vazio ou oferecer
outra coisa.

### Uma operação por lista
Venda e aluguel não se misturam numa lista só: ordenada por preço, os aluguéis
(a partir de R$ 1.500) enterram as vendas (a partir de R$ 240 mil) e a pessoa
vê metade do que pediu. Quando ela aceita as duas, quem consulta duas vezes e
apresenta separado é o agente de busca — o agente conversacional escreve um
pedido só.

Na falta de indicação no pedido, vale a `intencao` já gravada do lead.

### O que não se repete
Os IDs apresentados ficam num cache em memória, por conversa, com validade de
uma hora, e são entregues ao agente de busca como o que ele não deve reoferecer.

O cache é deliberadamente volátil: dura o tempo de uma conversa, e é por
processo — Streamlit e bot do Telegram rodam separados. Uma conversa retomada no
dia seguinte pode rever os mesmos imóveis, o que é aceitável; o que não era
aceitável é a pessoa receber o mesmo apartamento três vezes no mesmo
atendimento.

Isso vale para o que é oferecido como novidade. Perguntar sobre um imóvel já
mostrado — *"aquele da Mooca, quanto era mesmo?"* — é outra coisa, e continua
funcionando.

---

## 2a. `detalhar_imoveis`

### Objetivo
Reler do catálogo a ficha completa dos imóveis já apresentados nesta conversa.

### Input esperado
- `imovel_ids` — opcional. Vazio devolve os últimos apresentados a este lead; com IDs, devolve apenas aqueles.

O caso comum é chamar **sem** IDs. O agente conversacional frequentemente não os tem: o retorno da busca é abreviado em 900 caracteres ao voltar ao histórico, e numa conversa real isso derrubou três dos seis IDs mostrados.

### Output esperado
A mesma ficha de `buscar_imoveis` — preço, metragem, cômodos, vagas e, no aluguel, o custo total do mês. Sem justificativa, porque não houve escolha a justificar.

Quando nenhum imóvel foi apresentado ainda, a resposta manda usar `buscar_imoveis`. Quando um ID pedido não existe ou está indisponível, o retorno diz quais falharam e proíbe falar deles com a pessoa.

### Efeitos colaterais
Nenhum. Uma leitura indexada por chave primária, sem LLM.

### Regras
- é esta a ferramenta para qualquer pergunta sobre imóvel já mostrado: preço, vaga, metragem, suíte, condomínio, lazer do prédio, acabamento — a ficha volta completa, com a descrição inteira;
- `buscar_imoveis` só quando o que a pessoa procura mudou;
- no máximo dez fichas quando chamada sem IDs — a lista inteira de uma conversa longa seriam milhares de tokens para responder "quantas vagas tem".

### Erros tratáveis
- nenhum imóvel apresentado ainda;
- ID inexistente ou indisponível;
- falha de banco.

### Por que ela existe
Sem ela, uma pergunta sobre a lista recém-apresentada só se respondia buscando
tudo de novo. Medido numa conversa real: *"o que os condomínios oferecem,
piscina, vagas?"* disparou uma busca completa de **25.523 tokens de entrada e
29 segundos**, que ainda trouxe imóveis diferentes dos que a pessoa tinha visto.

É também por aqui que o `imovel_id` de `agendar_reuniao` é recuperado quando o
truncamento do histórico o levou embora.

### De onde vêm os IDs
Do `metadata_json` das mensagens de ferramenta, onde cada busca grava o que
apresentou — inclusive a busca do caminho de degradação, que não usa LLM.

No banco, e não em memória: Streamlit e bot do Telegram rodam em processos
separados (ADR 0004), e o registro precisa sobreviver a restart e valer para os
dois.

---

## 2b. `listar_agendamentos`

### Objetivo
Devolver os compromissos de pé do lead, com o ID de cada um.

### Input esperado
Nenhum: o lead vem das dependências.

### Output esperado
O mesmo texto que abre as instruções — id, tipo, data e imóvel de cada
compromisso, ou a linha "nenhum".

### Efeitos colaterais
Nenhum.

### Por que existe, se a lista já está nas instruções
Posição. As instruções abrem a requisição; o histórico vem depois delas. Numa
conversa em que o agente já respondeu várias vezes que não achava os IDs, o
modelo seguiu o padrão recente e contradisse a própria lista — chegou a chamar
outra tool como substituto e a relatar honestamente que aquilo não trazia os
IDs. A tool devolve a mesma verdade na posição mais recente da
conversa, que é onde o modelo olha.

---

## 3. `registrar_qualificacao`

### Objetivo
Persistir ou atualizar dados estruturados do lead.

### Input esperado
Campos estruturados do lead, como:
- `nome`
- `telefone`
- `intencao`
- `perfil`
- `orcamento_min`
- `orcamento_max`
- `bairro_interesse`
- `regiao_interesse`
- `quartos`
- `urgencia`
- `motivo_busca`
- `forma_pagamento`
- `amenidades_desejadas`

### Nome e telefone
O telefone e normalizado para `(11) 98765-4321`: aceita com ou sem DDI, com ou
sem pontuacao, fixo de dez digitos ou celular de onze. Sem DDD a tool recusa com
`ModelRetry` pedindo o DDD — gravar um numero incompleto so se descobre errado
na hora em que o corretor liga.

Quando pedir cada um e regra da persona, nao da tool: o nome cedo, na conversa;
o telefone na hora de marcar a visita, que e quando ha um motivo que a pessoa
entende. `agendar_reuniao` acrescenta ao proprio retorno a cobranca do que
faltar, porque o retorno da tool e a ultima coisa que o modelo le antes de
escrever.

### Output esperado
- lead atualizado;
- campos alterados;
- status atual do lead.

### Efeitos colaterais
Atualização persistente do lead no banco.

### Regras
- não apagar informação útil sem motivo explícito;
- mudanças relevantes devem atualizar `updated_at`;
- alterações conflitantes devem privilegiar o dado mais recente, com rastreabilidade.

### Erros tratáveis
- lead inexistente;
- payload inválido;
- falha de persistência.

---

## 4. `atualizar_perfil_lead`

### Objetivo
Acrescentar ao `perfil_narrativo` do lead o que a conversa acabou de revelar.

### Input esperado
- `novidades` — a novidade do turno, em uma ou duas frases. **Só a novidade**: o perfil já gravado é preservado pela tool e não deve ser repetido aqui.

### Output esperado
Confirmação de persistência.

### Efeitos colaterais
- leitura do `perfil_narrativo` atual;
- chamada ao consolidador de perfil (`src/agent/perfil_agent.py`), que funde os dois textos;
- escrita do resultado no campo `perfil_narrativo` do lead;
- registro do custo em `llm_usage` com `operation="perfil"`.

### Regras
- registrar preferências, objeções, rejeições e contexto de vida relevantes;
- dado padronizado (orçamento, bairro, quartos, telefone) não entra aqui: vai em `registrar_qualificacao`;
- o consolidador preserva tudo que já estava no perfil, e só sobrescreve o que a novidade contradiz;
- o perfil não é transcrição bruta da conversa: é o texto que o corretor lê antes de ligar.

### Erros tratáveis
- lead inexistente;
- falha ou resposta vazia do consolidador — a novidade é emendada ao fim do perfil sem consolidação, e nada se perde;
- falha de persistência.

---

## 5. `agendar_reuniao`

### Objetivo
Registrar visita ou reunião para handover ao corretor.

### Input esperado
- `tipo` (`visita` ou `reuniao`)
- `data_hora`
- `observacoes` (opcional)
- `imovel_id` (opcional, quando aplicável)

### Output esperado
- agendamento criado;
- status do agendamento;
- dados principais do compromisso.

### Efeitos colaterais
Criação de registro de agendamento e possível atualização do status do lead.

### Regras
- não criar agendamento sem dados mínimos;
- validar formato de data/hora;
- registrar observações relevantes para o corretor;
- **idempotente**: mesmo lead, mesma data e hora, mesmo imóvel e ainda de pé
  devolve o compromisso existente em vez de criar outro. Sem isso, pedir duas
  vezes a mesma visita — o que acontece quando o modelo não acha a ferramenta
  certa, e quando alguém clica duas vezes na tela — põe dois compromissos na
  agenda do corretor para o mesmo horário.

### Erros tratáveis
- lead inexistente;
- data inválida;
- falha de persistência.

---

## 5.1 `confirmar_agendamento` e `cancelar_agendamento`

### Objetivo
Mover um compromisso existente para `confirmado` ou `cancelado`, a partir do
que a pessoa disse na conversa.

### Input esperado
- `agendamento_id` — de um compromisso listado no contexto do lead
- `motivo` (só no cancelamento) — o que a pessoa deu como razão, até 120 caracteres

### Output esperado
- confirmação do novo estado, com tipo e data do compromisso;
- recusa explicativa quando o id não existe, não é deste lead, ou o
  compromisso já está no estado pedido.

### Efeitos colaterais
Mudança de status do agendamento. O cancelamento grava também uma mensagem
`system_notice` com o motivo, para o corretor ver por que a visita caiu.
Sendo o último compromisso de pé, o lead sai de `agendado`.

### Regras
- só agir sobre decisão explícita: hesitação (*"acho que consigo"*, *"vou
  ver"*) não confirma nem cancela;
- nunca usar `agendar_reuniao` para confirmar — isso cria um segundo
  compromisso em vez de mudar o primeiro;
- remarcar é cancelar o antigo e marcar o novo.

### Erros tratáveis
- `agendamento_id` inexistente ou de outro lead;
- compromisso já cancelado ou realizado.

### Por que o id vem do contexto
As instruções do agente listam os compromissos de pé com id, data **e imóvel**,
do mais próximo ao mais distante, dizendo que aquela é a lista completa e que
IDs citados antes na conversa devem ser ignorados.

São `@agent.instructions`, e não `@agent.system_prompt`, por uma razão de
mecânica: o pydantic-ai só insere o system prompt quando o `message_history`
chega vazio. Como o histórico é reidratado do banco a cada turno, um system
prompt valeria apenas na primeira mensagem da conversa — e desta seção
dependem as duas tools de compromisso.

Cada parte disso resolve uma falha observada:

| Sem isso | O que acontece |
|---|---|
| a lista | o modelo inventa um número ou chama `agendar_reuniao` de novo |
| o imóvel | *"confirma aquele da Mooca"* não tem como virar um id, e o modelo vai procurar a ligação no histórico — onde encontra compromissos já apagados |
| o aviso sobre a conversa | o histórico compete com o contexto, e o modelo às vezes acredita nele |
| a linha "nenhum" quando a agenda está vazia | o silêncio deixa valer o que a conversa disse antes |

A recusa das duas tools também lista os IDs válidos. Só dizer "não existe" faz
o modelo desistir e repassar o problema à pessoa; com as opções na própria
recusa, ele pode acertar na retentativa.

---

## 6. `encerrar_atendimento`

### Objetivo
Fechar o atendimento quando não há mais nada que o agente possa fazer, entregando o briefing executivo ao corretor.

### Input esperado
- `desfecho` — `agendou`, `desistiu` ou `pediu_corretor`;
- `motivo` — em uma frase, o que a pessoa disse. É o que o corretor lê para saber por que a conversa terminou assim.

### Output esperado
Confirmação do encerramento e a instrução de se despedir sem nova pergunta. O resumo em si não volta ao modelo: ele é para a ficha do corretor, e devolvê-lo custaria alguns milhares de tokens sem uso.

### Efeitos colaterais
- anota o motivo no `perfil_narrativo`, pelo consolidador (tool 4);
- gera o `resumo` executivo do lead a partir do `SummaryService`;
- nos desfechos `desistiu` e `pediu_corretor`, move o lead para `inativo`.

### Regras
- **`agendou` exige compromisso de pé.** Sem nenhum na agenda, o atendimento não terminou em agendamento e a chamada é recusada com `ModelRetry`.
- **`desistiu` e `pediu_corretor` exigem agenda limpa.** Com compromisso de pé, marcar `inativo` apagaria o lembrete de confirmação e o corretor iria ao imóvel à toa: a tool recusa e manda cancelar antes.
- `agendou` **não** move o status: o lead fica em `agendado`, que é o único jeito de a régua `pos_agendamento` continuar valendo para ele.
- hesitação, silêncio e "vou pensar" não são desistência — são conversa em aberto, e quem retoma é o follow-up.

### Por que `inativo`, e não um status novo
É o único status fora dos `status_alvo` de todas as réguas de inatividade, então marcá-lo é exatamente o que faz o follow-up parar. E `process_message` devolve o lead a `em_qualificacao` assim que ele voltar a escrever, o que dá de graça o comportamento desejado: para de perseguir, mas não tranca a porta.

### Erros tratáveis
- lead inexistente;
- desfecho incompatível com a agenda (recusado com `ModelRetry`);
- falha de geração ou persistência do resumo.

---

## 7. `gerar_followup`

### Objetivo
Gerar mensagem contextual de reengajamento com base no estágio do funil e histórico.

### Papel arquitetural na POC
Na POC, `gerar_followup` deve ser entendido como uma **capacidade interna de geração textual acionada pelo `FollowUpService`**, e não como uma tool exposta ao agente conversacional com o cliente.

O `FollowUpService` continua responsável por:
- selecionar leads elegíveis;
- aplicar a régua correta;
- verificar tentativas e janela temporal;
- persistir mensagem e tentativa;
- acionar o canal de envio.

A responsabilidade de `gerar_followup` é apenas **compor a mensagem contextual** via LLM.

### Input esperado
- `lead_id`
- `regua_followup`
- histórico recente;
- `perfil_narrativo`;
- número de tentativas anteriores.

### Output esperado
- mensagem de follow-up;
- classificação da régua aplicada;
- indicação se o envio é recomendado.

### Efeitos colaterais
Nenhum obrigatório na geração; o envio e registro ocorrem em camada superior, sob responsabilidade do `FollowUpService`.

### Regras
- respeitar limite de tentativas;
- evitar tom insistente ou genérico;
- usar contexto real da conversa.
- não controlar elegibilidade, envio ou persistência;
- não ser invocado pelo agente conversacional com o cliente na POC.

### Erros tratáveis
- lead inexistente;
- contexto insuficiente;
- falha de geração.

---

## 8. Requisitos transversais de observabilidade

Cada execução de tool emite duas linhas de log, `tool_iniciada` e
`tool_finalizada`, com:

| Campo | Observação |
|---|---|
| `event` | `tool_iniciada` ou `tool_finalizada` |
| `tool_name` | nome da função da tool |
| `lead_id` | da conversa em curso |
| `channel` | `streamlit`, `telegram` |
| `status` | `ok` ou `erro`, em `tool_finalizada` |
| `duracao_ms` | em `tool_finalizada` |
| `tipo_erro` | classe da exceção, quando houve falha |
| `correlation_id` | amarra as tools de um mesmo turno à chamada que as disparou |

A instrumentação é um decorador aplicado às tools, e não código repetido
dentro de cada uma: uma tool nova fica coberta só por recebê-lo. Em caso de
falha a exceção é relançada — quem decide o que devolver ao modelo é a
política de retentativa do pydantic-ai, e o log apenas observa.

---

## 9. Requisitos transversais de teste

Cada tool deve ter, no mínimo:
- teste de sucesso;
- teste de input inválido;
- teste de falha de dependência;
- teste de contrato do retorno.
