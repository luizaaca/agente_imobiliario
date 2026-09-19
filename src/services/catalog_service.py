"""Serviço para catálogo de imóveis."""

import logging
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.db.models import Imovel

logger = logging.getLogger(__name__)

# Mesma configuracao usada na coluna gerada `imoveis.search_vector`.
FTS_CONFIG = "portuguese"


def _tsquery(termos: str):
    """Monta a tsquery de busca livre com semantica de OU.

    `websearch_to_tsquery` e usada em vez de `to_tsquery` porque ela ja trata
    aspas, acentos e pontuacao do texto cru, sem risco de erro de sintaxe com o
    que a LLM mandar. O `or` entre os termos e deliberado: exigir todas as
    palavras (o padrao) zeraria o resultado em buscas como
    "varanda gourmet churrasqueira", e quem separa relevancia e o ranking.
    """
    palavras = [p for p in termos.split() if p]
    return func.websearch_to_tsquery(FTS_CONFIG, " or ".join(palavras))


class CatalogService:
    """Serviço de domínio para busca e consulta no catálogo de imóveis."""

    def search(
        self,
        db: Session,
        intencao: Optional[str] = None,
        orcamento_min: Optional[float] = None,
        orcamento_max: Optional[float] = None,
        regiao_interesse: Optional[str] = None,
        bairro_interesse: Optional[str] = None,
        quartos: Optional[int] = None,
        termos_livres: Optional[str] = None,
        limite: int = 5,
    ) -> list[Imovel]:
        """Busca imóveis com filtros estruturados e ranking textual.

        Camada 1: filtros SQL diretos (finalidade, preço, bairro, quartos).
        Camada 2: ranking textual via FTS ou ILIKE fallback.
        """
        try:
            query = db.query(Imovel).filter(Imovel.disponivel.is_(True))

            # Camada 1: Filtros estruturados
            if intencao:
                if intencao in ("compra", "investimento"):
                    query = query.filter(Imovel.operacao == "venda")
                elif intencao == "aluguel":
                    query = query.filter(Imovel.operacao == "aluguel")

            if orcamento_min is not None:
                query = query.filter(Imovel.preco >= orcamento_min)

            if orcamento_max is not None:
                query = query.filter(Imovel.preco <= orcamento_max)

            if bairro_interesse:
                query = query.filter(
                    Imovel.bairro.ilike(f"%{bairro_interesse}%")
                )

            if regiao_interesse:
                query = query.filter(
                    or_(
                        Imovel.zona.ilike(f"%{regiao_interesse}%"),
                        Imovel.bairro.ilike(f"%{regiao_interesse}%"),
                    )
                )

            if quartos is not None:
                query = query.filter(Imovel.quartos >= quartos)

            # Camada 2: ranking textual via Full-Text Search do PostgreSQL.
            # `search_vector` e coluna gerada com indice GIN (ver models.py).
            if termos_livres and termos_livres.strip():
                consulta = _tsquery(termos_livres)
                query = query.filter(
                    or_(
                        Imovel.search_vector.op("@@")(consulta),
                        # Se sobrar so stopword ("para mim"), a tsquery fica
                        # vazia e nao casaria nada: nesse caso a camada textual
                        # e ignorada em vez de zerar a busca inteira.
                        func.numnode(consulta) == 0,
                    )
                ).order_by(
                    func.ts_rank(Imovel.search_vector, consulta).desc(),
                    Imovel.preco.asc(),
                )
            else:
                query = query.order_by(Imovel.preco.asc())

            results = query.limit(limite).all()

            logger.info(
                f"Busca de imóveis: {len(results)} resultados "
                f"(intencao={intencao}, bairro={bairro_interesse}, "
                f"preco={orcamento_min}-{orcamento_max}, quartos={quartos})"
            )

            return results

        except Exception as e:
            logger.error(f"Erro na busca de imóveis: {e}", exc_info=True)
            return []

    def get_by_id(self, imovel_id: int, db: Session) -> Optional[Imovel]:
        """Busca um imóvel pelo ID."""
        return db.query(Imovel).filter(Imovel.id == imovel_id).first()

    def count_available(self, db: Session) -> int:
        """Retorna a quantidade de imóveis disponíveis."""
        from sqlalchemy import func
        return (
            db.query(func.count(Imovel.id))
            .filter(Imovel.disponivel.is_(True))
            .scalar() or 0
        )
