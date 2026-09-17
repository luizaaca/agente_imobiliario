# Sub-plano: Estratégia de Agente, Tool Calling e Busca

**Referenciado pelo [PLANO_DE_IMPLEMENTACAO.md](./PLANO_DE_IMPLEMENTACAO.md)**

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
- Quando a conversa revela informações novas (preferência, restrição, objeção, reação a um imóvel), o agente chama a tool `atualizar_perfil_lead` com o texto atualizado.
- **Rejeições são dados valiosos**: "rejeitou o AP-007 porque achou a cozinha pequena" é tão importante quanto "gostou do AP-003".
- O perfil é o **produto principal do SDR** — o artefato que justifica sua existência ao entregar contexto completo ao corretor.

## 4. Tools do agente

| Tool | Responsabilidade |
|---|---|
| `buscar_imoveis` | Consulta catálogo com filtros e ranking textual |
| `registrar_qualificacao` | Persiste dados estruturados do lead (campos do schema) |
| `atualizar_perfil_lead` | **Atualiza o perfil narrativo textual** com novas informações da conversa |
| `agendar_reuniao` | Registra visita ou reunião no banco |
| `gerar_resumo_corretor` | Sintetiza briefing executivo final a partir do perfil e histórico |

> **Nota de escopo da POC:** a capacidade de geração de follow-up contextual existe no sistema, mas **não será exposta como tool do agente conversacional com o cliente**. Na POC, ela será usada exclusivamente pelo `FollowUpService`, que controla a régua, a elegibilidade, as tentativas e o envio, acionando a LLM apenas para compor a mensagem.

## 5. Boas práticas de tool calling adotadas

- Tools pequenas, específicas e com nomes claros.
- Schemas estritos e tipados.
- Poucas tools expostas por vez.
- Sem parâmetros redundantes que o sistema já conhece.
- Retornos estruturados para facilitar rastreabilidade e UI.

---

## 6. Estratégia de Busca de Imóveis

Com a adoção do PostgreSQL e um volume maior de dados (dataset importado), a abordagem de busca acontecerá diretamente no banco de dados em camadas:

### Camada 1 — Filtros estruturados (SQL)
Filtros diretos via `WHERE` clause:
- intenção/finalidade
- faixa de preço (`BETWEEN`)
- região ou bairro (`IN` ou `=`)
- quantidade de quartos (`>=`)

### Camada 2 — Ranking textual (FTS)
Ordenar os resultados restantes por aderência semântica e textual, utilizando o Full-Text Search do PostgreSQL (`to_tsvector` e `to_tsquery`):
- descrição do imóvel
- tags associadas
- termos-chave extraídos do `perfil_narrativo` do lead

### Evolução opcional
Adicionar colunas `pgvector` para armazenar embeddings da descrição do imóvel, permitindo busca semântica real (cosine similarity). Isso deve ser tratado como **incremento** para a POC.
