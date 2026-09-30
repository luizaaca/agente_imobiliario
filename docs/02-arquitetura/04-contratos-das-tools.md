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
- no máximo oito imóveis, e oito é teto e não meta: a lista traz quantos
  realmente servem, ainda que seja um só. Completar a lista com imóvel de
  outra `operacao`, `tipo` ou `finalidade` seria pior que devolvê-la curta —
  são imóveis que o agente conversacional não pode mostrar. Uma recomendação
  que mistura residencial e comercial é recusada em código, pelo validador de
  saída do agente de busca, e volta a ele como retentativa;
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

É também por aqui que o agente recupera o ID de cada imóvel para escrever na
`observacoes` de `agendar_reuniao`, quando o truncamento do histórico o levou
embora.

### De onde vêm os IDs
Do `metadata_json` das mensagens de ferramenta, onde cada busca grava o que
apresentou — inclusive a busca do caminho de degradação, que não usa LLM.

No banco, e não em memória: Streamlit e bot do Telegram rodam em processos
separados (ADR 0004), e o registro precisa sobreviver a restart e valer para os
dois.

---

## 2b. `listar_agendamentos`

### Objetivo
Devolver o compromisso de pé do lead.

### Input esperado
Nenhum: o lead vem das dependências.

### Output esperado
O mesmo texto que abre as instruções — tipo, data e status do compromisso, ou
a linha "nenhum". Sem id: nenhuma tool recebe qual compromisso, então não há o
que o modelo precise guardar.

### Efeitos colaterais
Nenhum.

### Por que existe, se a informação já está nas instruções
Posição. As instruções abrem a requisição; o histórico vem depois delas. Numa
conversa em que o agente já tinha repetido que não achava o compromisso, o
modelo seguiu o padrão recente e contradisse o próprio contexto. A tool devolve
a mesma verdade na posição mais recente da conversa, que é onde o modelo olha.

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
O telefone é normalizado para `(11) 98765-4321`: aceita com ou sem DDI, com ou
sem pontuação, fixo de dez dígitos ou celular de onze. Sem DDD a tool recusa com
`ModelRetry` pedindo o DDD — gravar um número incompleto só se descobre errado
na hora em que o corretor liga.

Quando pedir cada um é regra da persona, não da tool: os dois cedo, um por
mensagem, e sem insistir se a pessoa não quiser dar. O que ainda faltar quando
a visita é marcada, `agendar_reuniao` cobra no próprio retorno — ali há um
motivo que a pessoa entende, e o retorno da tool é a última coisa que o modelo
lê antes de escrever. O contexto do turno diz se o telefone já foi informado,
sem o número, para o modelo não pedir de novo.

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
- `observacoes` — o que o corretor lê antes de ir
- `remarcar` (default `false`)

### Output esperado
- agendamento criado;
- status do agendamento;
- dados principais do compromisso.

### Efeitos colaterais
Criação do registro, recálculo do score e possível mudança de status do lead —
os três saem de `SchedulingService.sincronizar_lead_com_a_agenda`.

### Regras

**Um compromisso de pé por pessoa.** O corretor vai uma vez e vê com ela os
imóveis que ela quiser; não se marca uma visita por imóvel. A regra é cobrada
por índice único parcial sobre `lead_id` para os status ativos, e não só no
código: uma checagem na aplicação cede a dois turnos gravando ao mesmo tempo, e
a um modelo que erra qual compromisso trocar.

**Marcar sobre um compromisso existente avisa e não marca.** O retorno diz qual
é o compromisso de pé e pede que o agente combine a troca com a pessoa; só com
o sim dela ele chama de novo com `remarcar=true`. Volta como retorno, e não
como `ModelRetry`, porque a correção não está com o modelo: está com a pessoa.
Uma retentativa imediata marcaria por cima de um compromisso que ela talvez
queira manter.

**Remarcar cancela e cria.** Duas linhas, e não uma reescrita: o compromisso
antigo fica no histórico com a nota *"Remarcado para …"* na `observacoes`. Sem
a nota o corretor lê o cancelamento como desistência; sem a linha, ninguém vê
que a pessoa já trocou de data uma vez.

**A `observacoes` é o vínculo com os imóveis.** O agendamento não aponta para
uma linha do catálogo: quem diz o que será visitado é esse texto, com o ID de
cada imóvel — *"Quer ver os imóveis 142 (sobrado na Mooca) e 144 (Tatuapé)"*. É
o que o corretor lê junto do perfil narrativo e do resumo executivo, e por isso
uma `visita` sem observação é recusada com `ModelRetry`, que diz o que
escrever.

Só se cobra que exista. Conferir o conteúdo — se cita imóvel, se o ID é de um
já apresentado — é adivinhar a intenção de um texto livre, e erraria nos dois
sentidos; o preço do falso negativo é recusar um agendamento que a pessoa
acabou de combinar. Uma `reuniao` não precisa de observação: nem todo encontro
é num imóvel do catálogo.

**Idempotente**: mesmo lead, mesmo tipo, mesma data e hora, e ainda de pé
devolve o compromisso existente em vez de recusar. Pedir duas vezes o mesmo
horário é o que o duplo clique na tela faz, e o que o modelo faz quando repete
a chamada sem ter lido o retorno da primeira.

### Erros tratáveis
- lead inexistente;
- data inválida;
- compromisso já marcado (`CompromissoJaMarcado`, traduzido em aviso para o
  agente e em mensagem na tela para o corretor);
- falha de persistência.

---

## 5.1 `confirmar_agendamento` e `cancelar_agendamento`

### Objetivo
Mover o compromisso do lead para `confirmado` ou `cancelado`, a partir do que a
pessoa disse na conversa.

### Input esperado
- `motivo` (só no cancelamento) — o que a pessoa deu como razão, até 120 caracteres

Nenhuma das duas recebe **qual** compromisso. É um de pé por pessoa, e o
serviço o encontra pelo lead do turno.

### Output esperado
- confirmação do novo estado, com tipo e data do compromisso;
- quando não há compromisso de pé, uma recusa que aponta a saída: marcar com
  `agendar_reuniao`, ou dizer à pessoa que o que ela cita já foi cancelado ou
  já aconteceu.

### Efeitos colaterais
Mudança de status do agendamento. O cancelamento grava também uma mensagem
`system_notice` com o motivo, para o corretor ver por que a visita caiu.
Sendo o último compromisso de pé, o lead sai de `agendado`.

### Regras
- só agir sobre decisão explícita: hesitação (*"acho que consigo"*, *"vou
  ver"*) não confirma nem cancela;
- nunca usar `agendar_reuniao` para confirmar — isso avisa que já há
  compromisso, e não muda o que existe;
- remarcar não passa por aqui: é `agendar_reuniao` com `remarcar=true`, que
  cancela o antigo e marca o novo numa chamada só.

### Erros tratáveis
- nenhum compromisso de pé;
- compromisso já no estado pedido.

### Por que nenhuma delas recebe id
Porque um id é algo que o modelo pode errar. Ele tiraria números antigos do
histórico e agiria sobre um compromisso já apagado — e um id de outra pessoa
alcançaria a agenda dela, o que exigiria uma checagem de dono em cada tool. Com
um compromisso por lead, cobrado por índice único, o argumento não tem função:
o dono é o lead do turno, por construção.

O contexto do turno traz o compromisso, sem id, porque a conversa precisa saber
**quando** ele é. São `@agent.instructions`, e não
`@agent.system_prompt`, por uma razão de mecânica: o pydantic-ai só insere o
system prompt quando o `message_history` chega vazio. Como o histórico é
reidratado do banco a cada turno, um system prompt valeria apenas na primeira
mensagem da conversa.

Cada parte disso resolve uma falha observada:

| Sem isso | O que acontece |
|---|---|
| o compromisso no contexto | o modelo responde pelo que a conversa disse, e ela envelhece |
| o aviso de que aquilo vale acima da conversa | o histórico compete com o contexto, e o modelo às vezes acredita nele |
| a linha "nenhum" quando a agenda está vazia | o silêncio deixa valer o que a conversa disse antes |

A recusa das duas tools aponta a saída. Só dizer "não existe" faz o modelo
desistir e repassar o problema à pessoa; com o caminho na própria recusa, ele
segue sozinho.

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

## 7. Geração do follow-up (fora das tools)

### Objetivo
Compor a mensagem contextual de reengajamento de um lead calado.

### Papel arquitetural
Não é tool: o agente conversacional não a vê nem a chama. É um agente próprio,
em `src/agent/followup_agent.py` (`gerar_mensagem_followup`), acionado pelo
`followup_runner` — no ciclo automático, no disparo manual da tela e no ciclo
avulso de `scripts/run_followup_once.py`.

Quem decide tudo o que não é texto está fora dele:

| Responsabilidade | Onde |
|---|---|
| quais leads são elegíveis, em qual régua, e o teto de tentativas | `FollowUpService` |
| orçamento de LLM, persistência da mensagem e da tentativa, envio pelo canal | `followup_runner` |
| se o canal tem envio ativo | `src/channels/envio.py` (`CANAIS_COM_ENVIO`) |

### Input
- o contexto do lead, montado pelo runner: nome, intenção, orçamento, bairro,
  região, quartos, urgência, motivo da busca, perfil narrativo, a última
  mensagem trocada e, no pós-agendamento, o compromisso;
- a régua, que escolhe a instrução da situação;
- o número da tentativa, que deixa a mensagem mais curta e leve a cada vez.

### Output
`FollowUpGerado`: o texto da mensagem e os tokens de entrada e saída, que o
runner registra em `llm_usage` com `operation="followup"`.

### Regras
- uma mensagem curta, com uma pergunta ou um próximo passo;
- só cita o que está no contexto: o agente não busca imóveis, então não diz que
  separou ou achou opções, nem comenta mercado ou clima;
- não controla elegibilidade, envio nem persistência.

### Erros tratáveis
- configuração de LLM ausente — o runner registra e segue para o próximo lead;
- falha do provider ou texto vazio — a tentativa é registrada como `failed`, e
  no disparo manual a tela mostra o motivo.

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
