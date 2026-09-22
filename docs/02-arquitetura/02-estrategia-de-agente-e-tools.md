# Estratégia de Agente, Tools e Busca

**Objetivo:** detalhar o papel do agente SDR, a estratégia conversacional, o uso de tools e a abordagem de busca de imóveis adotada na POC.

---

## 1. Papel do agente

O agente deve atuar como um SDR consultivo, com foco em:
- entender a intenção do lead;
- identificar lacunas de informação;
- fazer a próxima pergunta mais útil;
- recomendar imóveis quando houver contexto suficiente;
- propor agendamento no momento adequado;
- registrar e resumir o atendimento;
- **manter atualizado o perfil narrativo do lead** a cada interação significativa.

## 2. Estratégia conversacional

O agente não deve despejar um questionário completo de uma vez. O fluxo ideal é:

1. identificar intenção principal;
2. coletar apenas o próximo dado mais relevante;
3. atualizar o estado estruturado do lead;
4. **atualizar o perfil narrativo** com novas informações, objeções ou preferências capturadas;
5. buscar imóveis quando houver contexto mínimo suficiente;
6. oferecer agendamento quando houver aderência e interesse.

## 3. Estratégia de perfil narrativo incremental

O `perfil_narrativo` é tratado como um artefato vivo:
- O agente recebe o perfil narrativo atual como parte do seu contexto a cada turno.
- Quando a conversa revela informação nova (preferência, restrição, objeção, reação a um imóvel), o agente chama a tool `atualizar_perfil_lead` **com a novidade do turno, e só com ela**.
- **Rejeições são dados valiosos**: "rejeitou o AP-007 porque achou a cozinha pequena" é tão importante quanto "gostou do AP-003".
- O perfil é o **produto principal do SDR** — o artefato que justifica sua existência ao entregar contexto completo ao corretor.

### Quem escreve o perfil

O agente conversacional relata; quem redige é um agente separado, o **consolidador de perfil** (`src/agent/perfil_agent.py`). A tool lê o perfil gravado, entrega ao consolidador esse texto mais a novidade, e grava o resultado.

A separação é o que garante o acúmulo. O agente conversacional nunca reescreve o texto anterior — ele não o tem como parâmetro —, então não tem como deixar nada de fora ao resumir. E o consolidador trabalha com dois textos, sem tools e sem histórico de conversa, o que mantém a chamada curta e o resultado previsível.

Regras do consolidador:
- nada do perfil atual pode sumir; a novidade acrescenta;
- quando a novidade contradiz o perfil, vale a novidade, e a mudança fica registrada ("procurava na zona sul, passou a considerar a zona norte");
- prosa corrida, no máximo 8 linhas, agrupada por assunto — é o corretor que lê.

Se o provider falhar ou devolver texto vazio, a tool emenda a novidade ao fim do perfil sem consolidar. Um perfil com emenda visível é pior de ler que um consolidado, e muito melhor que um perfil sem a informação — que é a única cópia do que a pessoa acabou de contar.

O custo da consolidação é registrado em `llm_usage` com `operation="perfil"`: entra no orçamento de tokens do lead, mas não conta como turno de conversa para o limite que dispara o handover.

## 4. Tools do agente

| Tool | Responsabilidade |
|---|---|
| `buscar_imoveis` | Entrega o pedido, em texto livre, ao agente de busca, e devolve os imóveis escolhidos |
| `detalhar_imoveis` | Relê do catálogo a ficha completa do que já foi apresentado |
| `registrar_qualificacao` | Persiste dados estruturados do lead (campos do schema) |
| `atualizar_perfil_lead` | **Acrescenta ao perfil narrativo** a novidade do turno, via consolidador |
| `agendar_reuniao` | Registra visita ou reunião no banco |
| `listar_agendamentos` | Devolve os compromissos de pé do lead, com o ID de cada um |
| `confirmar_agendamento` | Move um compromisso para `confirmado`, quando a pessoa confirma |
| `cancelar_agendamento` | Move um compromisso para `cancelado`, com o motivo registrado |
| `encerrar_atendimento` | Fecha o atendimento, entrega o briefing executivo ao corretor e tira o lead da régua |

As três tools de compromisso existente trabalham sobre IDs que o agente recebe
nas instruções do turno, remontadas do banco. `agendar_reuniao` cria; as outras
mudam o estado do que já existe — usar a primeira para confirmar criaria um
segundo compromisso no mesmo horário.

> **Nota de escopo da POC:** a capacidade de geração de follow-up contextual existe no sistema, mas **não será exposta como tool do agente conversacional com o cliente**. Na POC, ela será usada exclusivamente pelo `FollowUpService`, que controla a régua, a elegibilidade, as tentativas e o envio, acionando a LLM apenas para compor a mensagem.

## 5. Boas práticas de tool calling adotadas

- Tools pequenas, específicas e com nomes claros.
- Schemas estritos e tipados.
- Poucas tools expostas por vez.
- Sem parâmetros redundantes que o sistema já conhece.
- Retornos estruturados para facilitar rastreabilidade e UI.
- **O agente escreve o delta, nunca o estado inteiro.** Pedir a um LLM que reescreva um texto acumulado para preservá-lo é apostar num resumo que pode encolher; pedir só o que mudou torna a perda impossível e ainda barateia a chamada. Quem precisa do estado completo é o código, que já o tem no banco.

---

## 6. Estratégia de Busca de Imóveis

### Quem busca

O agente conversacional **não** monta a consulta. Ele descreve o que a pessoa
procura, na linguagem em que ela pediu, e entrega esse texto ao **agente de
busca** (`src/agent/busca_agent.py`), que conhece o catálogo em detalhe e
investiga o banco até ter o que responder.

A separação resolve duas coisas que puxam em direções opostas. O que a pessoa
diz raramente se traduz em filtros sem perda — "algo novo, em região nobre,
entre a Paulista e a Faria Lima, para uma contabilidade de 8 pessoas" mistura
estado de conservação, julgamento de valor, duas referências que não são
bairros e um uso que implica metragem. E o contrato que aceitaria tudo isso em
campos tipados pesaria em toda requisição do agente conversacional, inclusive
nos turnos em que ninguém busca nada. Com a delegação, as instruções longas de
busca ficam onde só são lidas quando há busca.

O agente de busca recebe, além do pedido:
- a ficha estruturada do lead e o perfil narrativo, para desempatar o que o
  pedido não diz;
- os IDs dos imóveis já apresentados nesta conversa, para não reoferecer os
  mesmos.

### Como ele consulta

Por SQL, escrito por ele, contra uma **role somente-leitura restrita à tabela
`imoveis`**. As camadas de contenção estão em
[`04-dados/01-modelagem-logica-do-banco.md`](../04-dados/01-modelagem-logica-do-banco.md).

Consultar por SQL é o que torna a busca uma investigação em vez de uma consulta
única. As perguntas que decidem uma recomendação — quantos existem nesta faixa,
em que bairros se concentram, o que aparece se o teto subir 30% — não cabem num
conjunto fechado de filtros, e são elas que separam "não achei" de "não existe".

Um erro de SQL volta ao agente de busca como texto, para ele reescrever a
consulta. O limite de linhas é do statement, não da resposta: ele pode ler
dezenas de imóveis e devolver três.

**O que ele nunca troca:** operação, tipo e finalidade. Quem pede galpão não
recebe sala comercial. Bairro, preço, metragem e amenidades são negociáveis e
podem ser afrouxados — desde que a resposta diga, em português, o que precisou
mudar.

### O que o PostgreSQL oferece a ele

A coluna `imoveis.search_vector` é **gerada pelo banco** (`GENERATED ALWAYS AS ... STORED`) a partir de título, descrição, tags, bairro e tipo, com índice GIN. Sem trigger nem código de aplicação para manter o vetor, ele não tem como ficar defasado.

Para texto, a consulta usa `websearch_to_tsquery('portuguese', ...)`, que trata acentos e pontuação do texto cru sem risco de erro de sintaxe. Os termos são combinados com **OU** — exigir todas as palavras zeraria buscas como "varanda gourmet churrasqueira". Quem separa relevância é o `ts_rank`, que ordena o resultado.

Aspas ali dentro delimitam frase exata, não ênfase: `"varanda gourmet"` vira a
sequência `varand <-> gourmet`, que exige as duas palavras adjacentes. É o
oposto do OU, e serve para quando a adjacência é mesmo o que se procura.

**O que não está no vetor:** zona, finalidade, perfil indicado, preço, área e
número de cômodos. Todos têm coluna própria e se filtram com `WHERE`. Procurar
"comercial" no texto traz apartamento que usa a palavra na descrição e perde
sala que não a usa; procurar "zona norte" não traz nada, porque a palavra só
existe numa coluna que o vetor não cobre.

### Quem escreve a resposta

O agente de busca devolve os IDs escolhidos e **uma linha de porquê para cada**.
Preço, condomínio, metragem e cômodos são relidos do banco e formatados pela
camada de código.

A divisão é deliberada: o julgamento é do agente, os números são do PostgreSQL.
O agente SDR promete à pessoa que nunca inventa preço nem disponibilidade, e
essa promessa não sobrevive a números escritos por um modelo.

### O que já foi mostrado

Os IDs apresentados a cada lead são gravados no `metadata_json` da mensagem da
ferramenta, e `detalhar_imoveis` os relê do catálogo quando a pessoa pergunta
mais sobre um imóvel que já está na conversa.

A gravação existe porque o histórico não basta. O retorno da busca é abreviado
em 900 caracteres ao ser reidratado, e medido numa conversa real isso derrubou
**metade dos IDs — três de seis**, incluindo o do imóvel sobre o qual a pessoa
perguntou em seguida. Sem registro durável, responder "quantas vagas tem o de
66 m²" custava uma busca inteira: dezenas de milhares de tokens, meio minuto, e
imóveis diferentes dos que ela tinha visto.

É o mesmo registro que sustenta o agendamento. `agendar_reuniao` exige
`imovel_id`, e um ID perdido no truncamento deixaria a visita sem imóvel.

No banco, e não em memória: Streamlit e bot do Telegram rodam em processos
separados (ADR 0004), e nada aqui pode depender de qual deles atendeu o turno
anterior.

### Onde se vê o que ele fez

As consultas do agente de busca não viram mensagem — é o que torna a delegação
barata —, então a única cópia delas é o `metadata_json` da chamada. A aba
**Conversa** da ficha e o simulador leem dali e mostram, num painel fechado ao
lado da fala que aquilo produziu: o pedido em texto livre, cada `SELECT`
escrito, o custo em tokens e o que a ferramenta devolveu ao agente.

Fechado por padrão porque quem abre a ficha quer ler a conversa; o painel existe
para a pergunta seguinte, que é como aqueles imóveis foram parar ali.

O renderizador é o mesmo nas duas telas (`src/ui/conversa.py`). O canal do
Telegram não passa por ele: o que chega à pessoa lá é só a resposta final.

### Quando o provider falha

A tool monta filtros a partir da ficha estruturada do lead, usa o pedido como
termo livre e consulta o catálogo sem LLM nenhum, com a escada de relaxamento
determinística do `CatalogService`. A busca degrada em qualidade, não em
disponibilidade — a pessoa recebe imóveis piores, não um pedido de desculpas.

Aqui o pedido é prosa, não uma consulta escrita para o PostgreSQL: as aspas que
vierem no meio dele são removidas, porque a adjacência que elas exigiriam não
foi pedida por ninguém e zeraria a busca inteira.

### Evolução opcional
Adicionar colunas `pgvector` para armazenar embeddings da descrição do imóvel, permitindo busca semântica real (cosine similarity). Isso deve ser tratado como **incremento** para a POC.
