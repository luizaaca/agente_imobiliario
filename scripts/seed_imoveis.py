#!/usr/bin/env python3
"""Ingere o catálogo sintético de imóveis no PostgreSQL.

Pré-requisito: o schema precisa existir. Rode `alembic upgrade head` antes.

A carga é idempotente (imóveis com `id` já presente são ignorados) e tolerante
a linha: um registro inválido é isolado em SAVEPOINT e não derruba a carga
inteira.

Uso:
    python -m scripts.seed_imoveis
"""

import csv
import sys
from pathlib import Path

from sqlalchemy import inspect, select, text

from src.db.models import Imovel
from src.db.session import SessionLocal, engine

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "imoveis_catalogo.csv"


def _to_float(value):
    return float(value) if value not in (None, "") else None


def _to_int(value):
    return int(value) if value not in (None, "") else None


def _to_bool(value):
    return str(value or "").strip().lower() in ("true", "1", "t", "sim", "yes")


def build_imovel(row: dict) -> Imovel:
    """Converte uma linha do CSV no modelo ORM."""
    return Imovel(
        id=int(row["id"]),
        titulo=row["titulo"],
        tipo=row["tipo"],
        finalidade=row["finalidade"],
        operacao=row["operacao"],
        bairro=row["bairro"],
        zona=row.get("zona"),
        cidade=row["cidade"],
        estado=row["estado"],
        preco=float(row["preco"]),
        quartos=int(row["quartos"]),
        suites=_to_int(row.get("suites")),
        banheiros=_to_int(row.get("banheiros")),
        vaga_garagem=_to_int(row.get("vaga_garagem")),
        area_m2=float(row["area_m2"]),
        condominio=_to_float(row.get("condominio")),
        iptu_anual=_to_float(row.get("iptu_anual")),
        descricao=row.get("descricao"),
        tags=row.get("tags"),
        perfil_indicado=row.get("perfil_indicado"),
        disponivel=_to_bool(row.get("disponivel", "true")),
        imagem_url=row.get("imagem_url"),
    )


def resync_sequence(db) -> None:
    """Ressincroniza a sequence de `imoveis.id` após inserts com id explícito.

    Sem isso, o próximo insert gerado pelo banco tentaria usar id=1 e colidiria.
    """
    if engine.dialect.name != "postgresql":
        return
    db.execute(
        text(
            "SELECT setval("
            "  pg_get_serial_sequence('imoveis', 'id'),"
            "  COALESCE((SELECT MAX(id) FROM imoveis), 1)"
            ")"
        )
    )
    db.commit()


def main() -> None:
    print("Iniciando ingestão de imóveis...")

    if not CSV_PATH.exists():
        print(f"Erro: arquivo {CSV_PATH} não encontrado.")
        sys.exit(1)

    if not inspect(engine).has_table(Imovel.__tablename__):
        print(
            "Erro: a tabela 'imoveis' não existe. "
            "Rode `alembic upgrade head` antes do seed."
        )
        sys.exit(1)

    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    inserted = skipped = errors = 0

    with SessionLocal() as db:
        existing_ids = set(db.scalars(select(Imovel.id)).all())

        for row in rows:
            row_id = row.get("id")
            try:
                if int(row_id) in existing_ids:
                    skipped += 1
                    continue
                # SAVEPOINT por linha: uma linha inválida não invalida as demais.
                with db.begin_nested():
                    db.add(build_imovel(row))
                    db.flush()
                inserted += 1
            except Exception as e:
                errors += 1
                print(f"Erro na linha id={row_id}: {e}")

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Erro ao salvar no banco de dados: {e}")
            sys.exit(1)

        resync_sequence(db)

    print("\nResumo da Carga:")
    print(f"- Inseridos: {inserted}")
    print(f"- Ignorados (já existem): {skipped}")
    print(f"- Erros: {errors}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
