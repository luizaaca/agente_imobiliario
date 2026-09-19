# Planejamento e Especificação da Geração de Catálogo Sintético de Imóveis

Este documento define a taxonomia, regras de consistência, distribuição estatística e instruções de geração em batches da massa sintética de imóveis para o projeto **Agente SDR Imobiliário com IA**.

---

## 1. Levantamento e Referências de Mercado

A modelagem de dados e a taxonomia foram construídas a partir de benchmarking nos principais portais imobiliários brasileiros (**Zap Imóveis**, **VivaReal**, referências residenciais do **QuintoAndar**) e dados do **Índice FipeZAP** para a cidade de **São Paulo/SP**.

### 1.1 Insights do Levantamento
- **Segmentação Realista**: Portais dividem rigorosamente em **Residencial** e **Comercial**, sendo que comercial engloba desde salas compactas de consultório/escritório até lajes corporativas monousuário e galpões industriais.
- **Faixas de Preço de Venda (São Paulo)**:
  - *Alto Padrão / Luxo (Itaim Bibi, Pinheiros, Jardins, Vila Nova Conceição)*: R$ 16.000 a R$ 24.000 / m².
  - *Médio-Alto Padrão (Moema, Perdizes, Brooklin, Campo Belo, Santana, Tatuapé)*: R$ 10.000 a R$ 15.000 / m².
  - *Econômico / Médio (Centro, Bela Vista, Mooca, Butantã, Barra Funda)*: R$ 6.000 a R$ 9.500 / m².
  - *Comercial Venda*: Salas (R$ 7.000 a R$ 18.000 / m²); Lajes Corporativas Triple A (R$ 18.000 a R$ 35.000 / m²); Galpões (R$ 2.500 a R$ 6.000 / m²).
- **Faixas de Locação Mensal (São Paulo)**:
  - *Residencial Aluguel*: R$ 45 a R$ 130 / m² / mês dependendo da localização e mobília.
  - *Comercial Aluguel*: Salas e escritórios (R$ 50 a R$ 110 / m² / mês); Lajes Corporativas (R$ 100 a R$ 260 / m² / mês); Galpões (R$ 22 a R$ 45 / m² / mês).
- **Condomínio e IPTU**:
  - Condomínio residencial: R$ 10 a R$ 25 / m² / mês.
  - Condomínio comercial: R$ 18 a R$ 45 / m² / mês (piso elevado, gerador full, segurança armada, leed, recepção bilíngue).
  - Casas de rua e terrenos: condomínio = 0 ou nulo.

---

## 2. Schema Alvo da Tabela `imoveis`

Conforme especificado em `docs/04-dados/01-modelagem-logica-do-banco.md` (seções 8.2 e 8.3):

| Campo | Tipo | Nullable | Regra / Descrição |
|---|---|:---:|---|
| `id` | `INTEGER` | Não | Identificador sequencial (1 a 300) |
| `titulo` | `VARCHAR(200)` | Não | Título claro, comercialmente atraente e informativo |
| `tipo` | `VARCHAR(30)` | Não | Conforme taxonomia expandida (seção 3) |
| `finalidade` | `VARCHAR(20)` | Não | `residencial` ou `comercial` |
| `operacao` | `VARCHAR(20)` | Não | `venda` ou `aluguel` |
| `bairro` | `VARCHAR(100)` | Não | Bairro oficial da cidade de São Paulo |
| `zona` | `VARCHAR(50)` | Não | `zona_sul`, `zona_oeste`, `centro`, `zona_norte`, `zona_leste` |
| `cidade` | `VARCHAR(100)` | Não | Valor fixo: `São Paulo` |
| `estado` | `VARCHAR(2)` | Não | Valor fixo: `SP` |
| `preco` | `NUMERIC(12,2)` | Não | Preço total em Reais (BRL) |
| `quartos` | `SMALLINT` | Não | Qtd de dormitórios/salas de atendimento (0 para comercial/studio) |
| `suites` | `SMALLINT` | Sim | Qtd de suítes (0 para comercial; <= quartos) |
| `banheiros` | `SMALLINT` | Não | Qtd total de banheiros/lavabos (mínimo 1) |
| `vaga_garagem` | `SMALLINT` | Não | Qtd de vagas privativas ou rotativas (0 a 40) |
| `area_m2` | `NUMERIC(10,2)` | Não | Área útil/privativa em metros quadrados |
| `condominio` | `NUMERIC(10,2)` | Sim | Cota condominial mensal em BRL (0 para casas de rua/terrenos) |
| `iptu_anual` | `NUMERIC(10,2)` | Sim | IPTU anual total em BRL |
| `descricao` | `TEXT` | Não | Texto descritivo rico (3-5 linhas) ideal para PostgreSQL Full-Text Search |
| `tags` | `TEXT` | Não | Lista de tags/diferenciais separadas por vírgula |
| `perfil_indicado` | `VARCHAR(30)` | Não | Segmento alvo do lead/comprador (seção 3.4) |
| `disponivel` | `BOOLEAN` | Não | `true` (95% do catálogo) ou `false` (5% para testar filtros) |
| `imagem_url` | `VARCHAR(500)` | Não | URL placeholder temática de alta qualidade (Unsplash arquitetura) |

---

## 3. Taxonomia Expandida e Categorização

### 3.1 Tipos de Imóveis (`tipo`)
- **Residenciais (8 tipos)**:
  - `apartamento`: Apartamento padrão vertical (1 a 4 dormitórios).
  - `studio`: Imóvel compacto integrado (20 a 45 m²).
  - `cobertura`: Unidade no último andar, duplex ou linear com área externa.
  - `casa`: Casa térrea ou assobradada em rua pública.
  - `casa_condominio`: Residência em condomínio horizontal fechado com segurança.
  - `sobrado`: Imóvel residencial de 2 ou mais pavimentos.
  - `flat`: Unidade com serviços pay-per-use e recepção.
  - `loft`: Imóvel de conceito aberto, pé-direito duplo ou estilo industrial.

- **Comerciais e Corporativos (8 tipos)**:
  - `sala_comercial`: Módulo para escritório individual ou pequeno negócio (28 a 90 m²).
  - `consultorio`: Espaço adaptado para área de saúde (médico, odontológico, psicológico, salas de espera/esterilização).
  - `escritorio`: Conjunto comercial consolidado para médias equipes (90 a 250 m²).
  - `andar_corporativo`: Laje corporativa ampla ocupando meio ou andar inteiro (250 a 1.500 m²).
  - `predio_comercial`: Edifício comercial monousuário ou multi-inquilino (400 a 4.000 m²).
  - `loja`: Ponto comercial térreo, de rua ou galeria com vitrine e fluxo de pedestres.
  - `galpao`: Galpão logístico ou industrial com pé-direito alto, docas e pátio de manobra.
  - `terreno_comercial`: Lote ou terreno com zoneamento comercial/misto para empreendimentos.

### 3.2 Zonas e Bairros de São Paulo
- **`zona_sul`**: Itaim Bibi, Vila Olímpia, Moema, Brooklin, Vila Nova Conceição, Campo Belo, Santo Amaro, Vila Mariana, Morumbi, Saúde.
- **`zona_oeste`**: Pinheiros, Perdizes, Vila Madalena, Alto de Pinheiros, Barra Funda, Butantã, Lapa, Pompeia.
- **`centro`**: Bela Vista, Consolação, República, Higienópolis, Santa Cecília, Centro Histórico.
- **`zona_leste`**: Tatuapé, Jardim Anália Franco, Mooca, Belém.
- **`zona_norte`**: Santana, Tucuruvi, Jardim São Paulo, Casa Verde.

### 3.3 Perfis Indicados (`perfil_indicado`)
- *Residenciais*:
  - `alto_padrao`: Leads que buscam luxo, acabamento nobre, exclusividade e metragens amplas.
  - `investidor`: Leads focados em yield de locação, valorização e liquidez (studios, flats, compactos).
  - `residencial_familia`: Famílias que priorizam 3+ quartos, condomínio clube, escolas próximas.
  - `primeiro_imovel`: Compradores de primeiro imóvel, apartamentos compactos a médios.
  - `executivo`: Solteiros ou casais que buscam praticidade, proximidade de centros financeiros e metrô.
  - `jovem_casal`: Casais iniciando vida a dois, plantas modernas de 2 dormitórios.

- *Comerciais*:
  - `corporativo`: Médias e grandes empresas necessitando de lajes, TI de ponta e imagem corporativa.
  - `pequena_empresa`: Escritórios, startups, agências e prestadores de serviço.
  - `saude_consultorio`: Médicos, clínicas integradas, dentistas e laboratórios.
  - `varejo_comercio`: Lojas, comércio de rua, franquias e alimentação.
  - `logistica_industrial`: Centros de distribuição, armazenagem e operações industriais leves.
  - `investidor_renda`: Compradores de imóveis com contratos de locação ativos (renda passiva).

---

## 4. Regras de Consistência e Engenharia Textual para FTS

Para garantir que a tool `buscar_imoveis` e o **PostgreSQL Full-Text Search (FTS)** tenham performance realista e enriquecedora durante as conversas com o agente SDR:

1. **Vocabulário FTS no Campo `descricao`**:
   - Cada descrição deve conter de 3 a 5 frases completas com palavras-chave reais de busca do mercado imobiliário:
     - Residencial: `varanda gourmet`, `vista panorâmica`, `armários planejados`, `churrasqueira`, `piscina climatizada`, `academia moderna`, `próximo ao metrô`, `portaria 24h`, `ensolarado`, `reformado`, `suíte master`, `closet`.
     - Comercial: `piso elevado`, `forro modular`, `cabeamento estruturado`, `ar condicionado central`, `gerador total`, `doca de carga e descarga`, `estacionamento rotativo`, `fibra óptica`, `certificação leed`, `recepção bilíngue`, `portaria com catracas eletrônicas`, `pé direito duplo`, `vitrine ampla`.
2. **Tags Padronizadas no Campo `tags`**:
   - Strings separadas por vírgula em minúsculas (ex: `metro_proximo, varanda_gourmet, piscina, academia, pet_friendly` ou `piso_elevado, ar_central, gerador_full, fibra_optica, leed_gold, estacionamento_rotativo`).
3. **Coerência de Metadados Numéricos**:
   - `quartos`: Obrigatório = 0 para tipos comerciais (`sala_comercial`, `consultorio`, `escritorio`, `andar_corporativo`, `predio_comercial`, `loja`, `galpao`, `terreno_comercial`).
   - `suites`: Deve ser `<= quartos`. Obrigatório = 0 para imóveis comerciais.
   - `banheiros`: Deve ser coerente (mínimo 1 para salas; 4 a 16 para lajes corporativas e prédios).
   - `vaga_garagem`: Compatível com a metragem e categoria (0 a 3 para residenciais comuns, 5 a 40 para lajes corporativas).
   - `area_m2`: Compatível com a tipologia.

---

## 5. Estratégia de Geração em Batches (Total: 300 Registros)

O volume de **300 imóveis** atende perfeitamente à faixa solicitada (entre 200 e 400 itens). A geração será distribuída em **6 batches de 50 registros**, atribuídos a subagentes autônomos:

| Batch | Faixa de IDs | Foco / Tipologias | Operação | Finalidade | Qtd |
|---|---|---|---|---|:---:|
| **Batch 1** | `001` a `050` | Apartamentos padrão, Studios compactos, Flats modernos | `venda` | `residencial` | 50 |
| **Batch 2** | `051` a `100` | Coberturas duplex/lineares, Casas de rua, Casas em condomínio, Sobrados, Lofts | `venda` | `residencial` | 50 |
| **Batch 3** | `101` a `150` | Studios, Apartamentos 1-3 dormitórios, Coberturas compactas, Sobrados | `aluguel` | `residencial` | 50 |
| **Batch 4** | `151` a `200` | Salas comerciais, Escritórios, Consultórios médicos, Lojas de rua, Terrenos comerciais | `venda` | `comercial` | 50 |
| **Batch 5** | `201` a `250` | Salas comerciais, Consultórios, Escritórios corporativos, Lojas / Pontos comerciais | `aluguel` | `comercial` | 50 |
| **Batch 6** | `251` a `300` | Andares / Lajes corporativas Triple A, Prédios comerciais monousuário, Galpões logísticos | `venda` e `aluguel` | `comercial` | 50 |

---

## 6. Pipeline de Execução e Consolidação

1. **Subagentes**: Cada subagente recebe seu prompt especializado com a faixa de IDs, requisitos de tipos, preços e atributos, e salva seu respectivo arquivo CSV parcial em `seed/batches/batch_XX.csv`.
2. **Script de Consolidação e Sanitização (`seed/consolidar_catalogo.py`)**:
   - Lê todos os batches (`batch_01.csv` a `batch_06.csv`).
   - Verifica unicidade de IDs de 1 a 300.
   - Valida tipagens numéricas e faixas aceitáveis.
   - Garante ausência de campos nulos obrigatórios e formatação correta de texto/escape CSV.
   - Gera estatísticas de cobertura (tipos, bairros, finalidade, operação).
   - Salva o arquivo consolidado final em `seed/imoveis_catalogo.csv`.
3. **Artefato Walkthrough**:
   - Documenta a execução completa e distribuição gerada.
