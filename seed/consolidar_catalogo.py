#!/usr/bin/env python3
"""Script de validação e consolidação dos batches de imóveis sintéticos.

Consolida os arquivos seed/batches/batch_01.csv a batch_06.csv em seed/imoveis_catalogo.csv,
executando validações estritas de schema, tipos, constraints e regras de negócio.
"""

import csv
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BATCHES_DIR = BASE_DIR / "batches"
OUTPUT_FILE = BASE_DIR / "imoveis_catalogo.csv"

EXPECTED_COLUMNS = [
    "id",
    "titulo",
    "tipo",
    "finalidade",
    "operacao",
    "bairro",
    "zona",
    "cidade",
    "estado",
    "preco",
    "quartos",
    "suites",
    "banheiros",
    "vaga_garagem",
    "area_m2",
    "condominio",
    "iptu_anual",
    "descricao",
    "tags",
    "perfil_indicado",
    "disponivel",
    "imagem_url",
]

VALID_TIPOS_RESIDENCIAIS = {
    "apartamento",
    "studio",
    "cobertura",
    "casa",
    "casa_condominio",
    "sobrado",
    "flat",
    "loft",
}

VALID_TIPOS_COMERCIAIS = {
    "sala_comercial",
    "consultorio",
    "escritorio",
    "andar_corporativo",
    "predio_comercial",
    "loja",
    "galpao",
    "terreno_comercial",
}

VALID_TIPOS = VALID_TIPOS_RESIDENCIAIS | VALID_TIPOS_COMERCIAIS
VALID_FINALIDADES = {"residencial", "comercial"}
VALID_OPERACOES = {"venda", "aluguel"}
VALID_ZONAS = {"zona_sul", "zona_oeste", "centro", "zona_norte", "zona_leste"}


def validate_and_consolidate():
    print("=" * 60)
    print("Iniciando Validação e Consolidação do Catálogo de Imóveis")
    print("=" * 60)

    batch_files = sorted(BATCHES_DIR.glob("batch_*.csv"))
    if not batch_files:
        print(f"ERRO: Nenhum arquivo de batch encontrado em {BATCHES_DIR}")
        return False

    all_rows = []
    seen_ids = set()
    errors = []

    for batch_path in batch_files:
        print(f"Lendo {batch_path.name}...")
        with open(batch_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if not header or [c.strip() for c in header] != EXPECTED_COLUMNS:
                errors.append(
                    f"[{batch_path.name}] Cabeçalho inválido. "
                    f"Esperado: {EXPECTED_COLUMNS}, Obtido: {header}"
                )
                continue

            for row_idx, row in enumerate(reader, start=2):
                clean_row = {k.strip(): (v.strip() if v else "") for k, v in row.items()}
                imovel_id_raw = clean_row.get("id")

                # Validação de ID
                try:
                    imovel_id = int(imovel_id_raw)
                    if imovel_id in seen_ids:
                        errors.append(f"[{batch_path.name}:L{row_idx}] ID duplicado: {imovel_id}")
                    seen_ids.add(imovel_id)
                except (ValueError, TypeError):
                    errors.append(f"[{batch_path.name}:L{row_idx}] ID inválido: '{imovel_id_raw}'")
                    continue

                # Validação de tipo, finalidade, operacao
                tipo = clean_row.get("tipo", "")
                finalidade = clean_row.get("finalidade", "")
                operacao = clean_row.get("operacao", "")
                zona = clean_row.get("zona", "")

                if tipo not in VALID_TIPOS:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Tipo desconhecido: '{tipo}'")
                if finalidade not in VALID_FINALIDADES:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Finalidade inválida: '{finalidade}'")
                if operacao not in VALID_OPERACOES:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Operação inválida: '{operacao}'")
                if zona not in VALID_ZONAS:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Zona inválida: '{zona}'")

                # Validações numéricas
                try:
                    preco = float(clean_row.get("preco", 0))
                    if preco <= 0:
                        errors.append(f"[{batch_path.name}:ID {imovel_id}] Preço deve ser > 0: {preco}")
                except ValueError:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Preço inválido: '{clean_row.get('preco')}'")

                try:
                    area_m2 = float(clean_row.get("area_m2", 0))
                    if area_m2 <= 0:
                        errors.append(f"[{batch_path.name}:ID {imovel_id}] Área m² deve ser > 0: {area_m2}")
                except ValueError:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Área m² inválida: '{clean_row.get('area_m2')}'")

                try:
                    quartos = int(clean_row.get("quartos", 0))
                    suites = int(clean_row.get("suites", 0)) if clean_row.get("suites") else 0
                    banheiros = int(clean_row.get("banheiros", 1))
                    vagas = int(clean_row.get("vaga_garagem", 0)) if clean_row.get("vaga_garagem") else 0

                    if tipo in VALID_TIPOS_COMERCIAIS:
                        if quartos != 0:
                            errors.append(f"[{batch_path.name}:ID {imovel_id}] Imóvel comercial '{tipo}' deve ter quartos=0, obtido: {quartos}")
                        if suites != 0:
                            errors.append(f"[{batch_path.name}:ID {imovel_id}] Imóvel comercial '{tipo}' deve ter suites=0, obtido: {suites}")
                    else:
                        if suites > quartos and tipo != "studio":
                            errors.append(f"[{batch_path.name}:ID {imovel_id}] Suítes ({suites}) não podem exceder quartos ({quartos})")

                    if banheiros < 1:
                        errors.append(f"[{batch_path.name}:ID {imovel_id}] Banheiros deve ser >= 1, obtido: {banheiros}")
                    if vagas < 0:
                        errors.append(f"[{batch_path.name}:ID {imovel_id}] Vagas não pode ser negativo: {vagas}")
                except ValueError as e:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Erro numérico de cômodos: {e}")

                # Descrição rica para FTS
                descricao = clean_row.get("descricao", "")
                if len(descricao) < 60:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Descrição muito curta para FTS ({len(descricao)} chars)")

                # Tags
                tags = clean_row.get("tags", "")
                if not tags:
                    errors.append(f"[{batch_path.name}:ID {imovel_id}] Campo tags não pode ser vazio")

                all_rows.append(clean_row)

    print("-" * 60)
    print(f"Total de registros lidos: {len(all_rows)}")
    print(f"Total de erros encontrados: {len(errors)}")

    if errors:
        print("Erros de validação:")
        for err in errors[:20]:
            print(f"  - {err}")
        if len(errors) > 20:
            print(f"  ... e mais {len(errors) - 20} erros.")
        return False

    # Ordenar por ID
    all_rows.sort(key=lambda r: int(r["id"]))

    # Verificar sequencialidade
    expected_ids = list(range(1, len(all_rows) + 1))
    actual_ids = [int(r["id"]) for r in all_rows]
    if actual_ids != expected_ids:
        print(f"AVISO: IDs não estão estritamente sequenciais de 1 a {len(all_rows)}.")
        # Re-indexar para garantir IDs perfeitos
        for idx, row in enumerate(all_rows, start=1):
            row["id"] = str(idx)
        print("IDs re-indexados com sucesso de 1 a 300.")

    # Salvar arquivo CSV final consolidado
    with open(OUTPUT_FILE, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPECTED_COLUMNS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nSucesso! Arquivo final gerado em: {OUTPUT_FILE}")
    print(f"Tamanho do dataset consolidado: {len(all_rows)} imóveis.")

    # Estatísticas de cobertura
    print("\n" + "=" * 60)
    print("ESTATÍSTICAS DO CATÁLOGO CONSOLIDADO")
    print("=" * 60)

    finalidades = Counter(r["finalidade"] for r in all_rows)
    operacoes = Counter(r["operacao"] for r in all_rows)
    tipos = Counter(r["tipo"] for r in all_rows)
    zonas = Counter(r["zona"] for r in all_rows)

    print("\n[Distribuição por Finalidade]")
    for k, v in finalidades.most_common():
        print(f"  {k:15}: {v:3d} ({v/len(all_rows)*100:.1f}%)")

    print("\n[Distribuição por Operação]")
    for k, v in operacoes.most_common():
        print(f"  {k:15}: {v:3d} ({v/len(all_rows)*100:.1f}%)")

    print("\n[Distribuição por Tipo]")
    for k, v in tipos.most_common():
        print(f"  {k:20}: {v:3d} ({v/len(all_rows)*100:.1f}%)")

    print("\n[Distribuição por Zona]")
    for k, v in zonas.most_common():
        print(f"  {k:15}: {v:3d} ({v/len(all_rows)*100:.1f}%)")

    venda_precos = [float(r["preco"]) for r in all_rows if r["operacao"] == "venda"]
    aluguel_precos = [float(r["preco"]) for r in all_rows if r["operacao"] == "aluguel"]

    print("\n[Métricas de Preço - Venda]")
    if venda_precos:
        print(f"  Mínimo: R$ {min(venda_precos):,.2f}")
        print(f"  Médio : R$ {sum(venda_precos)/len(venda_precos):,.2f}")
        print(f"  Máximo: R$ {max(venda_precos):,.2f}")

    print("\n[Métricas de Preço - Aluguel]")
    if aluguel_precos:
        print(f"  Mínimo: R$ {min(aluguel_precos):,.2f}")
        print(f"  Médio : R$ {sum(aluguel_precos)/len(aluguel_precos):,.2f}")
        print(f"  Máximo: R$ {max(aluguel_precos):,.2f}")

    print("=" * 60)
    return True


if __name__ == "__main__":
    success = validate_and_consolidate()
    sys.exit(0 if success else 1)
