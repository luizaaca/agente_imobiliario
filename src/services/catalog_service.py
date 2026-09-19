"""Serviço para catálogo de imóveis."""

import logging
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.db.models import Imovel

logger = logging.getLogger(__name__)


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

            # Camada 2: Ranking textual
            if termos_livres:
                # Fallback com ILIKE para compatibilidade sem FTS trigger
                search_filter = or_(
                    Imovel.titulo.ilike(f"%{termos_livres}%"),
                    Imovel.descricao.ilike(f"%{termos_livres}%"),
                    Imovel.tags.ilike(f"%{termos_livres}%"),
                )
                query = query.filter(search_filter)

            # Ordenar por preço como fallback
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
