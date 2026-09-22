# ADR 0007 — Delegar a recuperação de imóveis a um agente de busca dedicado

- **Status:** Aceito
- **Data:** 2026-09-22

## Contexto

A busca é o instrumento de qualificação do SDR: é mostrando imóvel que ele
descobre orçamento, tamanho e bairro sem transformar a conversa em formulário.
Isso põe duas exigências no mesmo lugar.

A primeira é de **expressividade**. O que a pessoa diz não se traduz em
filtros sem perda: "algo novo, em região nobre, entre a Paulista e a Faria
Lima, para uma contabilidade de 8 pessoas" mistura estado de conservação,
julgamento de valor, duas referências que não são bairros e um uso que implica
metragem. Um contrato de filtros obriga o agente conversacional a fazer essa
tradução antes de consultar, e é nessa tradução que a intenção se perde.

A segunda é de **orçamento de contexto**. Um contrato com dezenove filtros
tipados ocupa cerca de 1.300 tokens de schema — 42% de todo o bloco de
ferramentas do agente, e um quarto da base reenviada em **toda** requisição,
inclusive nos turnos em que ninguém busca nada. Descrever melhor cada filtro,
que é o que a expressividade pediria, encarece todos os turnos para melhorar
alguns.

As duas exigências puxam em direções opostas enquanto o mesmo agente conversa
e recupera dados.

## Decisão

Separar quem conversa de quem recupera.

O agente conversacional expõe **uma tool de busca com um único parâmetro de
texto livre**, onde ele escreve o que a pessoa procura na linguagem em que ela
pediu. A tool delega a um **agente de busca** dedicado, que conhece o catálogo
em detalhe, consulta o banco quantas vezes precisar e devolve os imóveis mais
aderentes com a justificativa de cada escolha.

O agente de busca consulta por **SQL, contra uma role somente-leitura restrita
à tabela `imoveis`**. As linhas que ele lê não entram no histórico da conversa:
o que volta ao agente conversacional é a seleção final, formatada pela camada
de código.

## Alternativas consideradas

### 1. Tool única com filtros estruturados tipados

- **Prós:** schema valida os valores antes do banco; nenhuma chamada extra ao
  provider; latência mínima; todo o comportamento é determinístico.
- **Contras:** a tradução do que a pessoa diz para filtros acontece dentro do
  agente conversacional, competindo com a conversa; o schema pesa em todo
  turno; melhorar a busca significa engordar o prompt de quem conversa.

### 2. Sub-agente com tools tipadas sobre o serviço de catálogo

- **Prós:** mesma separação de responsabilidades, com o SQL escrito em Python e
  as garantias do serviço de domínio preservadas.
- **Contras:** o sub-agente fica limitado às consultas que alguém previu. As
  perguntas que ele precisa fazer ao catálogo para decidir — quantos existem
  nesta faixa, onde se concentram, o que muda se afrouxar este critério — não
  cabem num conjunto fechado de filtros.

### 3. Busca vetorial com `pgvector`

- **Prós:** aderência semântica real, sem depender de vocabulário coincidente.
- **Contras:** pipeline de embeddings e reindexação; não resolve filtros
  numéricos (preço, metragem, quartos), que continuam precisando de SQL. Segue
  como evolução, não como substituto.

## Consequências

### Positivas

- o agente conversacional escreve o pedido na linguagem da pessoa, sem traduzir
  para filtros;
- as instruções detalhadas de busca — vocabulário do catálogo, ordem de
  investigação, o que nunca trocar — ficam no agente que busca, e não custam
  tokens nos turnos de conversa;
- o volume de linhas lidas é absorvido pelo agente de busca; o histórico da
  conversa recebe apenas a seleção final;
- o custo e a latência da recuperação ficam isolados em `llm_usage` com
  `operation="busca"`, mensuráveis separadamente do custo de conversar;
- a busca deixa de ser uma consulta única e passa a ser uma investigação: o
  agente de busca reformula quando o que achou não serve.

### Negativas

- **um turno com busca fica mais caro**, na faixa de 3 a 5 mil tokens: o que se
  economiza no schema do agente conversacional é menor do que o que o agente de
  busca consome;
- **a latência cresce**, com uma a três idas adicionais ao provider dentro da
  chamada da tool;
- **SQL escrito por LLM é superfície de ataque**: o banco guarda leads,
  telefones e o histórico das conversas, e o perfil narrativo — texto derivado
  do que o lead digitou — entra no contexto do agente de busca;
- **a proteção contra trocar a coisa procurada passa a ser instrução, não
  código**: quem pede galpão não pode receber sala comercial, e isso deixa de
  ser garantido por uma lista de filtros inegociáveis.

## Impacto arquitetural

O padrão é o mesmo da consolidação de perfil (ADR 0005): um agente chamado de
dentro da tool de outro agente, com prompt próprio, sem histórico de conversa e
com o custo registrado em separado. O consumo do agente de busca **não** é
propagado para o run principal — propagá-lo o gravaria como `operation="chat"`
e apagaria justamente a medição que motiva a separação.

O SQL gerado atravessa quatro camadas de contenção, descritas em
[`04-dados/01-modelagem-logica-do-banco.md`](../../04-dados/01-modelagem-logica-do-banco.md):
role somente-leitura com acesso a uma única tabela, transação read-only com
tempo limite, validação sintática do statement e teto de linhas. A role é o
limite de verdade; as outras três são profundidade.

A consequência negativa sobre a troca da coisa procurada é endereçada em dois
lugares: nas instruções do agente de busca, que fixam operação, tipo e
finalidade como inegociáveis, e num teste de regressão que exercita o caso
— pedido de galpão que não pode voltar como sala comercial.

A busca estruturada do serviço de catálogo permanece como **caminho de
degradação**: com o provider fora do ar, a tool monta filtros a partir da ficha
estruturada do lead e consulta sem LLM nenhum. A busca degrada em qualidade,
não em disponibilidade.
