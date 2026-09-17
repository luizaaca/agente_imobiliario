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

---

## 2. `buscar_imoveis`

### Objetivo
Consultar o catálogo de imóveis com filtros estruturados e ranking textual.

### Input esperado
- `intencao`
- `orcamento_min` (opcional)
- `orcamento_max` (opcional)
- `regiao_interesse` ou `bairro_interesse` (opcional)
- `quartos` (opcional)
- `termos_livres` (opcional)
- `limite_resultados` (opcional, default recomendado: 5)

### Output esperado
- lista de imóveis aderentes;
- justificativa resumida de aderência;
- indicador de ausência de resultados quando aplicável.

### Efeitos colaterais
Nenhum efeito de escrita obrigatório.

### Regras
- aplicar filtros estruturados antes do ranking textual;
- nunca retornar imóveis incompatíveis de forma gritante apenas para “preencher lista”;
- ausência de resultado deve ser tratada como resposta válida.

### Erros tratáveis
- falha de banco;
- parâmetros inválidos;
- catálogo indisponível.

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
- `lead_id`
- `novo_trecho` ou `perfil_narrativo_atualizado`
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
- `lead_id`
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
- registrar observações relevantes para o corretor.

### Erros tratáveis
- lead inexistente;
- data inválida;
- falha de persistência.

---

## 6. `gerar_resumo_corretor`

### Objetivo
Gerar briefing executivo para o corretor a partir do histórico e do perfil do lead.

### Input esperado
- `lead_id`
- contexto consolidado do lead

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

Cada execução de tool deve registrar, quando aplicável:
- `lead_id`
- `tool_name`
- `status`
- duração
- erro resumido
- identificador de correlação

---

## 9. Requisitos transversais de teste

Cada tool deve ter, no mínimo:
- teste de sucesso;
- teste de input inválido;
- teste de falha de dependência;
- teste de contrato do retorno.
