# Walkthrough: Geração de Catálogo Sintético de Imóveis (Residencial e Comercial)

> **Reprodutibilidade.** Os arquivos `seed/batches/batch_01.csv` a
> `batch_06.csv` não são versionados, então `consolidar_catalogo.py` não
> regenera o catálogo. O artefato final — os 300 imóveis — está versionado
> em `data/imoveis_catalogo.csv`, que é o que o seed carrega. Este documento
> registra **como** o catálogo foi gerado.

Concluímos a produção da massa de dados sintética de imóveis para o projeto **Agente SDR Imobiliário com IA**. O dataset atende integralmente às especificações do modelo de dados (`docs/04-dados/01-modelagem-logica-do-banco.md`), ao planejamento de mercado elaborado e às solicitações de inclusão de imóveis comerciais variados.

---

## 1. O Que Foi Realizado

### 1.1 Levantamento Inicial de Mercado
- Pesquisa nos principais portais imobiliários brasileiros (**Zap Imóveis**, **Viva Real**, referências do **QuintoAndar**) e análise do **Índice FipeZAP** para a capital paulista.
- Identificação das categorias comerciais essenciais do mercado de São Paulo: *salas comerciais, consultórios médicos/odontológicos, escritórios corporativos, lajes/andares corporativos Triple A, prédios comerciais monousuários, lojas/pontos comerciais e galpões industriais/logísticos*.
- Parametrização realista de precificação por metro quadrado (R$/m²), cotas condominiais e IPTU nas 5 zonas da cidade (Sul, Oeste, Centro, Leste e Norte).

### 1.2 Documentação e Modelagem
- **[Criado]** [`seed/planejamento_geracao_catalogo.md`](file:///C:/Users/LuizAlbertodeAndrade/source/repos/agente_imobiliario/seed/planejamento_geracao_catalogo.md): Documento mestre de referência com taxonomia, faixas de preços, vocabulário FTS e divisão de batches.
- **[Atualizado]** [`docs/04-dados/01-modelagem-logica-do-banco.md`](file:///C:/Users/LuizAlbertodeAndrade/source/repos/agente_imobiliario/docs/04-dados/01-modelagem-logica-do-banco.md): Atualização do schema formal da tabela `imoveis`, adicionando os tipos comerciais à lista e corrigindo as constraints SQL de `tipo`, `finalidade` e `operacao`.

### 1.3 Arquitetura de Geração por Subagentes
- Criação do tipo especializado de subagente `batch_generator` para escrita estruturada de dados CSV.
- Disparo concorrente de **6 batches de 50 registros** (totalizando 300 imóveis):
  - **Batch 01 (IDs 001–050)**: Residencial Venda (Apartamentos padrão, Studios compactos, Flats).
  - **Batch 02 (IDs 051–100)**: Residencial Venda (Coberturas duplex/lineares, Casas, Casas em condomínio fechado, Sobrados, Lofts).
  - **Batch 03 (IDs 101–150)**: Residencial Aluguel (Studios mobiliados, Apartamentos, Sobrados, Coberturas).
  - **Batch 04 (IDs 151–200)**: Comercial Venda (Salas comerciais, Escritórios, Consultórios médicos, Lojas de rua, Terrenos comerciais).
  - **Batch 05 (IDs 201–250)**: Comercial Aluguel (Salas comerciais, Consultórios, Escritórios corporativos, Lojas / Pontos comerciais).
  - **Batch 06 (IDs 251–300)**: Corporativo e Industrial (Lajes/Andares Corporativos Triple A, Prédios comerciais monousuário, Galpões logísticos).

### 1.4 Script de Consolidação e Sanitização
- **[Criado]** [`seed/consolidar_catalogo.py`](file:///C:/Users/LuizAlbertodeAndrade/source/repos/agente_imobiliario/seed/consolidar_catalogo.py): Script de validação estrita que inspeciona cabeçalhos, integridade de IDs, regras de negócio (ex.: `quartos=0` e `suites=0` para comerciais), limites numéricos, sanitização de caracteres e métricas estatísticas.
- **[Gerado]** [`seed/imoveis_catalogo.csv`](file:///C:/Users/LuizAlbertodeAndrade/source/repos/agente_imobiliario/seed/imoveis_catalogo.csv): Dataset consolidado final com 300 registros.

---

## 2. Estatísticas e Métricas do Catálogo Consolidado

A execução de validação retornou **100% de conformidade com 0 erros**:

```text
============================================================
Iniciando Validação e Consolidação do Catálogo de Imóveis
============================================================
Lendo batch_01.csv...
Lendo batch_02.csv...
Lendo batch_03.csv...
Lendo batch_04.csv...
Lendo batch_05.csv...
Lendo batch_06.csv...
------------------------------------------------------------
Total de registros lidos: 300
Total de erros encontrados: 0

Sucesso! Arquivo final gerado em: seed/imoveis_catalogo.csv
Tamanho do dataset consolidado: 300 imóveis.
============================================================
```

### Distribuição por Finalidade e Operação
| Dimensão | Categoria | Quantidade | Proporção |
|---|---|:---:|:---:|
| **Finalidade** | `residencial` | 150 | 50.0% |
| | `comercial` | 150 | 50.0% |
| **Operação** | `venda` | 170 | 56.7% |
| | `aluguel` | 130 | 43.3% |

### Distribuição por Tipologia (`tipo`)
| Tipo | Qtd | % | Segmento |
|---|:---:|:---:|---|
| `apartamento` | 52 | 17.3% | Residencial |
| `sala_comercial` | 42 | 14.0% | Comercial |
| `studio` | 30 | 10.0% | Residencial |
| `escritorio` | 22 | 7.3% | Comercial |
| `andar_corporativo` | 22 | 7.3% | Corporativo |
| `cobertura` | 19 | 6.3% | Residencial Nobre |
| `consultorio` | 18 | 6.0% | Comercial / Saúde |
| `loja` | 15 | 5.0% | Varejo |
| `sobrado` | 14 | 4.7% | Residencial |
| `predio_comercial` | 14 | 4.7% | Corporativo Monousuário |
| `galpao` | 14 | 4.7% | Logística / Industrial |
| `casa` | 12 | 4.0% | Residencial |
| `casa_condominio` | 10 | 3.3% | Residencial Fechado |
| `flat` | 8 | 2.7% | Residencial / Serviços |
| `loft` | 5 | 1.7% | Residencial Conceito |
| `terreno_comercial` | 3 | 1.0% | Empreendimento |
| **Total** | **300** | **100.0%** | |

### Distribuição Regional por Zonas de São Paulo
- **`zona_sul`**: 127 imóveis (42.3%) — Itaim Bibi, Vila Olímpia, Moema, Brooklin, Santo Amaro, Vila Mariana, Campo Belo, Morumbi, Saúde.
- **`zona_oeste`**: 80 imóveis (26.7%) — Pinheiros, Perdizes, Vila Madalena, Alto de Pinheiros, Barra Funda, Butantã, Lapa, Pompeia.
- **`centro`**: 38 imóveis (12.7%) — Bela Vista, Consolação, República.
- **`zona_leste`**: 36 imóveis (12.0%) — Tatuapé, Mooca, Belém, Anália Franco.
- **`zona_norte`**: 19 imóveis (6.3%) — Santana, Jardim São Paulo.

### Faixas de Preço Consolidadas
- **Venda**:
  - Mínimo: **R$ 240.000,00** (sala comercial compacta / studio)
  - Médio : **R$ 3.544.382,35**
  - Máximo: **R$ 48.000.000,00** (prédio monousuário / laje corporativa Faria Lima)
- **Aluguel**:
  - Mínimo: **R$ 1.500,00** (sala comercial em Santana / studio no Centro)
  - Médio : **R$ 21.119,62**
  - Máximo: **R$ 240.000,00** (laje corporativa Triple A de 1.400 m² na Vila Olímpia)

---

## 3. Qualidade Textual para Full-Text Search (FTS)

Todas as 300 descrições foram geradas com 3 a 5 frases completas, integrando termos de pesquisa imobiliária real para indexação no PostgreSQL com `plainto_tsquery('portuguese', ...)`:
- *Residenciais*: "varanda gourmet", "próximo ao metrô", "piscina privativa", "suíte master com hidromassagem", "ensolarado", "vista panorâmica", "condomínio clube".
- *Comerciais e Corporativos*: "piso elevado em ardósia", "certificação LEED Gold", "ar condicionado central VRF", "gerador full 100%", "heliponto homologado", "docas de carga e descarga", "estacionamento rotativo com manobrista", "catracas biométricas".

---

## 4. Próximos Passos
O arquivo [`seed/imoveis_catalogo.csv`](file:///C:/Users/LuizAlbertodeAndrade/source/repos/agente_imobiliario/seed/imoveis_catalogo.csv) está pronto para ser ingerido no banco de dados através do script de seed (`scripts/seed_imoveis.py`) quando a infraestrutura do PostgreSQL e SQLAlchemy for iniciada.
