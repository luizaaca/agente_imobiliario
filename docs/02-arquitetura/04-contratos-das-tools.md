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
Consultar o catálogo com filtros estruturados e ranking textual. É o
instrumento de qualificação do agente: mostrar imóvel é o que faz a pessoa
revelar orçamento, tamanho e bairro sem que ninguém pergunte.

### Input esperado
O que a pessoa procura (nunca afrouxado):
- `operacao` — `venda` ou `aluguel`;
- `tipo` — um dos 16 tipos do catálogo;
- `finalidade` — `residencial` ou `comercial`, quando ela não nomeia o tipo.

Onde:
- `bairro` — só o nome do bairro;
- `zona` — uma das 5 regiões, e também aceita nome de bairro.

Quanto:
- `preco_min`, `preco_max` — preço do imóvel;
- `custo_total_max` — aluguel mais condomínio.

Como é:
- `quartos_min`, `quartos_max`, `suites_min`, `banheiros_min`, `vagas_min`;
- `area_min`, `area_max`;
- `perfil_indicado` — um dos 12 perfis de uso;
- `termos_livres` — só amenidades, em texto livre.

Apresentação:
- `ordenar_por` — `preco_asc`, `preco_desc`, `area_desc` ou `relevancia`;
- `limite_resultados` — 1 a 10, default 5.

`operacao`, `tipo`, `finalidade`, `zona`, `perfil_indicado` e `ordenar_por` são
`Literal` na assinatura, então viram `enum` no schema da tool: o valor inválido
é rejeitado pelo provider antes de chegar ao banco. `tests/test_catalog_service.py`
compara cada lista com o `SELECT DISTINCT` da coluna, para não envelhecerem.

### Output esperado
- lista de imóveis aderentes, com preço, metragem, quartos, suítes, banheiros e
  vagas; no aluguel, também aluguel + condomínio = total do mês;
- quando houve afrouxamento, a frase em português do que mudou;
- quando não houve resultado, o diagnóstico (ver abaixo).

### Efeitos colaterais
Nenhum efeito de escrita obrigatório.

### Regras
- aplicar filtros estruturados antes do ranking textual;
- nunca retornar imóveis incompatíveis de forma gritante apenas para “preencher lista”;
- ausência de resultado deve ser tratada como resposta válida;
- uma operação por busca (ver abaixo).

### Erros tratáveis
- falha de banco;
- parâmetros inválidos;
- catálogo indisponível.

### O que a busca nunca troca
`operacao`, `tipo` e `finalidade` ficam fora da escada de relaxamento. A escada
existe para dar flexibilidade de **lugar e condição** — outro bairro, teto 30%
maior, sem exigir a vaga —, não para trocar a coisa procurada por outra.

Isto veio de uma falha real: a pessoa pediu galpão, a escada derrubou o termo
antes de derrubar um filtro de região que não filtrava nada, e o agente
apresentou salas comerciais como se fossem o que ela tinha pedido.

Como `tipo` determina `finalidade` (não existe galpão residencial), a
finalidade é deduzida quando só o tipo vem, e o par contraditório é recusado
com `ModelRetry` — sem isso ele daria lista vazia para sempre, já que nenhum
dos dois é afrouxado.

### Lista vazia é resposta, não erro
Quando nada resta depois da escada, o retorno traz os números do catálogo:
quantos existem do que foi pedido, qual o mais barato, em que bairros há. É com
eles que o agente diz o que existe de verdade, em vez de pedir desculpa no
vazio ou oferecer outra coisa.

### Uma operação por busca
Sem `operacao`, a busca mistura venda e aluguel e a ordenação por preço faz os
aluguéis (a partir de R$ 1.500) enterrarem as vendas (a partir de R$ 240 mil).
Quando a pessoa aceita as duas, o agente busca duas vezes, uma por operação. O
retorno avisa disso quando a operação não foi informada, e a tool usa a
`intencao` já gravada do lead antes de cair na lista mista.

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
`gerar_resumo_corretor` como substituto e a relatar honestamente que aquilo não
trazia os IDs. A tool devolve a mesma verdade na posição mais recente da
conversa, que é onde o modelo olha.

---

## 3. `registrar_qualificacao`

### Objetivo
Persistir ou atualizar dados estruturados do lead.

### Input esperado
Campos estruturados do lead, como:
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
Atualizar incrementalmente o `perfil_narrativo` do lead.

### Input esperado
- `perfil_narrativo_atualizado`
- `motivo_atualizacao` (opcional, recomendado)

### Output esperado
- `perfil_narrativo` atualizado;
- confirmação de persistência.

### Efeitos colaterais
Escrita no campo `perfil_narrativo` do lead.

### Regras
- preservar coerência e legibilidade;
- registrar preferências, objeções, rejeições e contexto de vida relevantes;
- evitar duplicação desnecessária;
- não transformar o perfil em transcrição bruta da conversa.

### Erros tratáveis
- lead inexistente;
- texto inválido ou vazio;
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

## 6. `gerar_resumo_corretor`

### Objetivo
Gerar briefing executivo para o corretor a partir do histórico e do perfil do lead.

### Input esperado
Nenhum: o lead vem das dependências do run e o contexto é lido do banco.

### Output esperado
Resumo contendo:
- intenção;
- perfil;
- score;
- preferências;
- objeções;
- imóveis de interesse;
- próximos passos.

### Efeitos colaterais
Pode atualizar o campo `resumo` do lead.

### Regras
- o resumo deve ser útil para ação humana;
- deve explicar score e próximos passos;
- não deve ser mera cópia do histórico.

### Erros tratáveis
- lead inexistente;
- contexto insuficiente;
- falha de geração/persistência.

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
