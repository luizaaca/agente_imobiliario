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
| `buscar_imoveis` | Consulta catálogo com filtros e ranking textual |
| `registrar_qualificacao` | Persiste dados estruturados do lead (campos do schema) |
| `atualizar_perfil_lead` | **Acrescenta ao perfil narrativo** a novidade do turno, via consolidador |
| `agendar_reuniao` | Registra visita ou reunião no banco |
| `encerrar_atendimento` | Fecha o atendimento, entrega o briefing executivo ao corretor e tira o lead da régua |

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

Com a adoção do PostgreSQL e um volume maior de dados no catálogo sintético, a abordagem de busca acontecerá diretamente no banco de dados em camadas:

### Camada 1 — Filtros estruturados (SQL)
Filtros diretos via `WHERE` clause:
- intenção/finalidade
- faixa de preço (`BETWEEN`)
- região ou bairro (`IN` ou `=`)
- quantidade de quartos (`>=`)

### Camada 2 — Ranking textual (FTS)
Ordenar os resultados restantes por aderência textual usando o Full-Text Search do PostgreSQL.

A coluna `imoveis.search_vector` é **gerada pelo banco** (`GENERATED ALWAYS AS ... STORED`) a partir de título, descrição, tags, bairro e tipo, com índice GIN. Sem trigger nem código de aplicação para manter o vetor, ele não tem como ficar defasado.

A consulta usa `websearch_to_tsquery('portuguese', ...)`, que trata acentos e pontuação do texto cru sem risco de erro de sintaxe, e combina os termos com **OU** — exigir todas as palavras zeraria buscas como "varanda gourmet churrasqueira". Quem separa relevância é o `ts_rank`, que ordena o resultado. Se sobrarem apenas stopwords, a camada textual é ignorada em vez de zerar a busca.

As aspas do texto que o modelo manda são removidas antes de montar a consulta, pela mesma razão do OU: para o `websearch_to_tsquery` um par de aspas delimita frase exata, e intercalar `or` entre as palavras de dentro dele transformaria `"varanda gourmet"` na frase `varand <-> or <-> gourmet`, que não casa imóvel nenhum. Busca livre aqui é OU com ranking, não frase.

### Evolução opcional
Adicionar colunas `pgvector` para armazenar embeddings da descrição do imóvel, permitindo busca semântica real (cosine similarity). Isso deve ser tratado como **incremento** para a POC.
