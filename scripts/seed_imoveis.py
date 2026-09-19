#!/usr/bin/env python3
"""Script para ingerir o catálogo sintético de imóveis no PostgreSQL.

Lê o arquivo data/imoveis_catalogo.csv e insere os registros na tabela imoveis.
Responsabilidades:
1. Ler o CSV
2. Validar campos obrigatórios
3. Normalizar formatos
4. Inserir via SQLAlchemy
5. Registrar métricas da carga
"""

import csv
import sys
from pathlib import Path

from src.db.session import engine, SessionLocal
from src.db.models import Base, Imovel

def main():
    print("Iniciando ingestão de imóveis...")
    
    # Criar tabelas se não existirem
    Base.metadata.create_all(bind=engine)
    
    # Path relative to project root (assuming script runs from there)
    # The parent agent instructed to write everything starting with C:\... 
    # but the script will likely be run from the root.
    base_dir = Path(__file__).resolve().parent.parent
    csv_path = base_dir / "data" / "imoveis_catalogo.csv"
    
    if not csv_path.exists():
        print(f"Erro: Arquivo {csv_path} não encontrado.")
        sys.exit(1)
        
    inserted = 0
    skipped = 0
    errors = 0
    
    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        with SessionLocal() as db:
            for row in reader:
                try:
                    # Validar e processar linha
                    imovel_id = int(row['id'])
                    
                    # Verificar se já existe
                    exists = db.query(Imovel).filter(Imovel.id == imovel_id).first()
                    if exists:
                        skipped += 1
                        continue
                        
                    # Tratar booleanos e nulos
                    def parse_float(val):
                        return float(val) if val else None
                        
                    def parse_int(val):
                        return int(val) if val else None
                        
                    imovel = Imovel(
                        id=imovel_id,
                        titulo=row['titulo'],
                        tipo=row['tipo'],
                        finalidade=row['finalidade'],
                        operacao=row['operacao'],
                        bairro=row['bairro'],
                        zona=row.get('zona'),
                        cidade=row['cidade'],
                        estado=row['estado'],
                        preco=float(row['preco']),
                        quartos=int(row['quartos']),
                        suites=parse_int(row.get('suites')),
                        banheiros=parse_int(row.get('banheiros')),
                        vaga_garagem=parse_int(row.get('vaga_garagem')),
                        area_m2=float(row['area_m2']),
                        condominio=parse_float(row.get('condominio')),
                        iptu_anual=parse_float(row.get('iptu_anual')),
                        descricao=row.get('descricao'),
                        tags=row.get('tags'),
                        perfil_indicado=row.get('perfil_indicado'),
                        disponivel=row.get('disponivel', 'true').lower() == 'true',
                        imagem_url=row.get('imagem_url')
                    )
                    
                    db.add(imovel)
                    inserted += 1
                    
                except Exception as e:
                    print(f"Erro na linha id={row.get('id')}: {e}")
                    errors += 1
                    
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Erro ao salvar no banco de dados: {e}")
                sys.exit(1)
                
    print("\nResumo da Carga:")
    print(f"- Inseridos: {inserted}")
    print(f"- Ignorados (já existem): {skipped}")
    print(f"- Erros: {errors}")

if __name__ == "__main__":
    main()
