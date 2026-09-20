"""Serviço para catálogo de imóveis.

A busca é o instrumento de qualificação do agente: é mostrando imóvel que ele
descobre orçamento, tamanho e bairro, sem transformar a conversa em formulário.
Por isso ela precisa aceitar quase tudo que a pessoa diz — e recusar o que não
existe em vez de devolver qualquer coisa para preencher a lista.
"""

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Optional, get_args

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.db.models import Imovel

logger = logging.getLogger(__name__)

# Mesma configuracao usada na coluna gerada `imoveis.search_vector`.
FTS_CONFIG = "portuguese"

# --- Vocabulário do catálogo -------------------------------------------------
#
# Estes três conjuntos são os valores que as colunas realmente guardam. Viram
# `Literal` na assinatura das tools, então o schema da tool já rejeita o que
# não existe — em vez de a busca devolver zero e o agente achar que o catálogo
# é que está vazio. `tests/test_catalog_service.py` compara cada um com o
# `SELECT DISTINCT` do banco, para a lista não envelhecer em silêncio.

TipoImovel = Literal[
    "andar_corporativo", "apartamento", "casa", "casa_condominio", "cobertura",
    "consultorio", "escritorio", "flat", "galpao", "loft", "loja",
    "predio_comercial", "sala_comercial", "sobrado", "studio",
    "terreno_comercial",
]
TIPOS = get_args(TipoImovel)

Zona = Literal["centro", "zona_sul", "zona_norte", "zona_leste", "zona_oeste"]
ZONAS = get_args(Zona)

PerfilIndicado = Literal[
    "alto_padrao", "corporativo", "executivo", "investidor", "investidor_renda",
    "jovem_casal", "logistica_industrial", "pequena_empresa", "primeiro_imovel",
    "residencial_familia", "saude_consultorio", "varejo_comercio",
]
PERFIS_INDICADOS = get_args(PerfilIndicado)

Operacao = Literal["venda", "aluguel"]
Finalidade = Literal["residencial", "comercial"]
Ordenacao = Literal["preco_asc", "preco_desc", "area_desc", "relevancia"]

# O tipo determina a finalidade: nao existe galpao residencial nem apartamento
# comercial. Serve para deduzir a finalidade quando so o tipo vem, e para
# barrar o par contraditorio — que, como nenhum dos dois e afrouxado, daria
# lista vazia para sempre sem o agente entender por que.
FINALIDADE_POR_TIPO = {
    "andar_corporativo": "comercial",
    "apartamento": "residencial",
    "casa": "residencial",
    "casa_condominio": "residencial",
    "cobertura": "residencial",
    "consultorio": "comercial",
    "escritorio": "comercial",
    "flat": "residencial",
    "galpao": "comercial",
    "loft": "residencial",
    "loja": "comercial",
    "predio_comercial": "comercial",
    "sala_comercial": "comercial",
    "sobrado": "residencial",
    "studio": "residencial",
    "terreno_comercial": "comercial",
}

# A intencao e do lead ("quero comprar"); a operacao e do imovel ("esta a
# venda"). Investimento compra.
OPERACAO_POR_INTENCAO = {
    "compra": "venda",
    "investimento": "venda",
    "aluguel": "aluguel",
}


class FiltroInvalido(ValueError):
    """Combinação de filtros que nunca devolveria nada.

    Não é "não achei": é um pedido impossível, e a mensagem diz qual é a
    contradição para quem chamou poder corrigir na retentativa.
    """


def _padrao_de_zona(termo: str) -> str:
    """Transforma o jeito que as pessoas falam no jeito que a coluna guarda.

    `imoveis.zona` guarda 'zona_oeste', com underscore. Quem escreve "zona
    oeste" nao casava nada, que e justamente a forma mais natural de dizer.
    O underscore tambem e curinga de um caractere em LIKE, entao ele resolve
    os dois casos de uma vez: casa o underscore literal e o espaco.
    """
    return "%" + re.sub(r"[^0-9a-zA-ZÀ-ÿ]+", "_", termo.strip()) + "%"


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


def _custo_total():
    """Preço mais condomínio. Sem condomínio cadastrado, só o preço."""
    return Imovel.preco + func.coalesce(Imovel.condominio, 0)


def reais(valor) -> str:
    """Valor no formato brasileiro, com ponto separando o milhar.

    O padrão do Python separa com vírgula, e "R$ 12,500" em português se lê
    doze reais e meio. Estes textos vão para o modelo, que repete o número
    para a pessoa — então o erro sairia da tela como preço errado.
    """
    return f"R$ {valor:,.0f}".replace(",", ".")


@dataclass
class ResultadoBusca:
    """O que a busca achou, o que foi afrouxado e, se nada veio, por quê."""
    imoveis: list[Imovel] = field(default_factory=list)
    # Descrições em português do que foi relaxado, na ordem em que foi.
    relaxamentos: list[str] = field(default_factory=list)
    # Só quando a lista veio vazia: o que no catálogo barrou cada filtro.
    diagnostico: list[str] = field(default_factory=list)
    # Quantos imóveis existem com os filtros que nunca são afrouxados
    # (operação, tipo, finalidade). Zero significa catálogo sem aquilo.
    universo: int = 0

    @property
    def exata(self) -> bool:
        return not self.relaxamentos


class CatalogService:
    """Serviço de domínio para busca e consulta no catálogo de imóveis."""

    # Filtros que definem O QUE a pessoa procura. Afrouxar qualquer um deles é
    # trocar o pedido por outro: quem pede galpão e recebe sala comercial não
    # foi atendido com flexibilidade, foi ignorado.
    FILTROS_FIXOS = ("operacao", "tipo", "finalidade")

    def _normalizar(self, filtros: dict[str, Any]) -> dict[str, Any]:
        """Deduz o que dá para deduzir e barra o que se contradiz."""
        filtros = {k: v for k, v in filtros.items() if v not in (None, "")}

        tipo = filtros.get("tipo")
        if tipo:
            if tipo not in FINALIDADE_POR_TIPO:
                raise FiltroInvalido(
                    f"Não existe o tipo '{tipo}' no catálogo. Os tipos são: "
                    + ", ".join(TIPOS)
                )
            correta = FINALIDADE_POR_TIPO[tipo]
            informada = filtros.get("finalidade")
            if informada and informada != correta:
                raise FiltroInvalido(
                    f"'{tipo}' é sempre {correta}, então não existe "
                    f"{tipo} {informada}. Refaça sem a finalidade, ou com "
                    f"finalidade='{correta}'."
                )
            # Deduzida em vez de exigida: o modelo nao precisa saber a tabela.
            filtros["finalidade"] = correta

        for campo, minimo, maximo in (
            ("quartos", "quartos_min", "quartos_max"),
            ("preço", "preco_min", "preco_max"),
            ("área", "area_min", "area_max"),
        ):
            piso, teto = filtros.get(minimo), filtros.get(maximo)
            if piso is not None and teto is not None and piso > teto:
                raise FiltroInvalido(
                    f"A faixa de {campo} está invertida: {minimo}={piso} é "
                    f"maior que {maximo}={teto}."
                )

        return filtros

    def search(
        self,
        db: Session,
        operacao: Optional[str] = None,
        tipo: Optional[str] = None,
        finalidade: Optional[str] = None,
        bairro: Optional[str] = None,
        zona: Optional[str] = None,
        preco_min: Optional[float] = None,
        preco_max: Optional[float] = None,
        custo_total_max: Optional[float] = None,
        quartos_min: Optional[int] = None,
        quartos_max: Optional[int] = None,
        suites_min: Optional[int] = None,
        banheiros_min: Optional[int] = None,
        vagas_min: Optional[int] = None,
        area_min: Optional[float] = None,
        area_max: Optional[float] = None,
        perfil_indicado: Optional[str] = None,
        termos_livres: Optional[str] = None,
        ordenar_por: Optional[str] = None,
        limite: int = 5,
    ) -> list[Imovel]:
        """Busca imóveis com filtros estruturados e ranking textual.

        Camada 1: filtros SQL diretos (operação, tipo, preço, bairro, metragem…).
        Camada 2: ranking textual via FTS sobre título, descrição e tags.
        """
        try:
            query = db.query(Imovel).filter(Imovel.disponivel.is_(True))

            if operacao:
                query = query.filter(Imovel.operacao == operacao)

            if tipo:
                query = query.filter(Imovel.tipo == tipo)

            # Residencial x comercial e filtro estruturado, nao busca
            # textual: procurar "comercial" no texto traz apartamento com a
            # palavra na descricao e perde sala que nao a usa.
            if finalidade:
                query = query.filter(Imovel.finalidade == finalidade)

            if bairro:
                query = query.filter(Imovel.bairro.ilike(f"%{bairro}%"))

            if zona:
                # Aceita tambem nome de bairro: o modelo nem sempre sabe em que
                # zona fica a Mooca, e errar para mais brando e melhor que zerar.
                query = query.filter(
                    or_(
                        Imovel.zona.ilike(_padrao_de_zona(zona)),
                        Imovel.bairro.ilike(f"%{zona}%"),
                    )
                )

            if preco_min is not None:
                query = query.filter(Imovel.preco >= preco_min)

            if preco_max is not None:
                query = query.filter(Imovel.preco <= preco_max)

            if custo_total_max is not None:
                query = query.filter(_custo_total() <= custo_total_max)

            if quartos_min is not None:
                query = query.filter(Imovel.quartos >= quartos_min)

            if quartos_max is not None:
                query = query.filter(Imovel.quartos <= quartos_max)

            # Nulo reprovado de proposito: pedir duas suites e receber imovel
            # sem suite cadastrada seria mentir por omissao.
            if suites_min is not None:
                query = query.filter(Imovel.suites >= suites_min)

            if banheiros_min is not None:
                query = query.filter(Imovel.banheiros >= banheiros_min)

            if vagas_min is not None:
                query = query.filter(Imovel.vaga_garagem >= vagas_min)

            if area_min is not None:
                query = query.filter(Imovel.area_m2 >= area_min)

            if area_max is not None:
                query = query.filter(Imovel.area_m2 <= area_max)

            if perfil_indicado:
                query = query.filter(Imovel.perfil_indicado == perfil_indicado)

            # Camada 2: ranking textual via Full-Text Search do PostgreSQL.
            # `search_vector` e coluna gerada com indice GIN (ver models.py).
            consulta = None
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
                )

            query = query.order_by(*self._ordenacao(ordenar_por, consulta))
            results = query.limit(limite).all()

            logger.info(
                "event=busca_de_imoveis status=ok resultados=%s operacao=%s "
                "tipo=%s bairro=%s zona=%s preco_min=%s preco_max=%s "
                "quartos_min=%s quartos_max=%s area_min=%s",
                len(results), operacao, tipo, bairro, zona, preco_min,
                preco_max, quartos_min, quartos_max, area_min,
            )

            return results

        except Exception as e:
            logger.error(
                "event=busca_de_imoveis status=erro tipo_erro=%s erro=%s",
                type(e).__name__, e, exc_info=True,
            )
            return []

    def _ordenacao(self, ordenar_por: Optional[str], consulta):
        """Critérios de `ORDER BY`, com desempate sempre por preço e id.

        Sem `ordenar_por`, a ordem é a que faz sentido para o que foi pedido:
        relevância quando houve texto livre, preço crescente quando não houve.
        O id no fim existe para a paginação ser estável entre chamadas iguais.
        """
        if ordenar_por is None:
            ordenar_por = "relevancia" if consulta is not None else "preco_asc"

        if ordenar_por == "relevancia" and consulta is None:
            # Pediram relevancia sem termo nenhum: nao ha o que ranquear.
            ordenar_por = "preco_asc"

        if ordenar_por == "relevancia":
            return (
                func.ts_rank(Imovel.search_vector, consulta).desc(),
                Imovel.preco.asc(),
                Imovel.id.asc(),
            )
        if ordenar_por == "preco_desc":
            return (Imovel.preco.desc(), Imovel.id.asc())
        if ordenar_por == "area_desc":
            return (Imovel.area_m2.desc(), Imovel.preco.asc(), Imovel.id.asc())
        return (Imovel.preco.asc(), Imovel.id.asc())

    # Ordem em que os filtros sao afrouxados quando a busca exata nao devolve
    # nada. Vai do que a pessoa menos sente falta ao que mais sente, e cada
    # passo carrega o texto que explica o que mudou. Operacao, tipo e
    # finalidade nao estao aqui: ver FILTROS_FIXOS.
    ESCADA_DE_RELAXAMENTO = (
        ("perfil_indicado", "sem restringir ao perfil do imóvel"),
        ("banheiros_min", "sem exigir o número de banheiros"),
        ("suites_min", "sem exigir suíte"),
        ("vagas_min", "sem exigir vaga de garagem"),
        ("quartos_max", "aceitando imóveis com mais quartos"),
        ("area_max", "sem teto de metragem"),
        ("area_min", "sem exigir a metragem mínima"),
        ("quartos_min", "sem fixar o número de quartos"),
        ("preco_max", "com o teto de preço 30% maior"),
        ("custo_total_max", "com o teto de custo total 30% maior"),
        ("preco_min", "aceitando imóveis mais baratos"),
        ("bairro", "olhando a região toda, não só o bairro"),
        ("termos_livres", "sem exigir os termos da descrição"),
        ("zona", "em qualquer região da cidade"),
    )

    # Quanto cada teto/piso se move, em vez de sumir: um orçamento de 600 mil
    # que vira "qualquer preço" traz cobertura de 5 milhões para quem não pode.
    FATOR = {"preco_max": 1.3, "custo_total_max": 1.3, "preco_min": 0.7}

    def search_relaxando(self, db: Session, **filtros: Any) -> ResultadoBusca:
        """Busca e, se nao achar nada, vai afrouxando filtros ate achar.

        Existe porque a alternativa era o agente devolver o problema para o
        lead ("me diga uma faixa de orcamento") ou, pior, dizer que ampliou a
        busca sem ter ampliado. Aqui o alargamento acontece de fato, e a lista
        de `relaxamentos` da ao agente as palavras exatas do que foi mudado.

        Operacao, tipo e finalidade ficam de fora do afrouxamento: sao o que a
        pessoa procura, e nao uma preferencia negociavel. Quando a busca falha
        por causa deles, o retorno traz `diagnostico` em vez de outro imovel
        qualquer.
        """
        filtros = self._normalizar(filtros)
        limite = filtros.get("limite", 5)

        imoveis = self.search(db=db, **filtros)
        if imoveis:
            return ResultadoBusca(imoveis=imoveis)

        atuais = dict(filtros)
        relaxamentos: list[str] = []

        for campo, descricao in self.ESCADA_DE_RELAXAMENTO:
            if atuais.get(campo) in (None, ""):
                continue  # nada a afrouxar aqui; nao inventa relaxamento

            if campo in self.FATOR:
                atuais[campo] = float(atuais[campo]) * self.FATOR[campo]
            else:
                atuais[campo] = None

            relaxamentos.append(descricao)
            imoveis = self.search(db=db, **atuais)
            if imoveis:
                logger.info(
                    "event=busca_relaxada relaxamentos=%s resultados=%s",
                    relaxamentos, len(imoveis),
                )
                return ResultadoBusca(imoveis=imoveis, relaxamentos=relaxamentos)

        universo = self._universo(db, filtros)
        diagnostico = self._diagnostico(db, filtros, universo, limite)
        logger.info(
            "event=busca_sem_resultado relaxamentos=%s universo=%s",
            relaxamentos, universo,
        )
        return ResultadoBusca(
            relaxamentos=relaxamentos, diagnostico=diagnostico, universo=universo
        )

    def _universo(self, db: Session, filtros: dict[str, Any]) -> int:
        """Quantos imóveis existem só com os filtros que nunca são afrouxados."""
        fixos = {c: filtros[c] for c in self.FILTROS_FIXOS if filtros.get(c)}
        return self._contar(db, fixos)

    def _contar(self, db: Session, filtros: dict[str, Any]) -> int:
        query = db.query(func.count(Imovel.id)).filter(Imovel.disponivel.is_(True))
        for campo, valor in filtros.items():
            if campo == "operacao":
                query = query.filter(Imovel.operacao == valor)
            elif campo == "tipo":
                query = query.filter(Imovel.tipo == valor)
            elif campo == "finalidade":
                query = query.filter(Imovel.finalidade == valor)
        return query.scalar() or 0

    def _diagnostico(
        self, db: Session, filtros: dict[str, Any], universo: int, limite: int
    ) -> list[str]:
        """Por que a busca deu zero, com os números do catálogo.

        Sem isto o agente só sabe que não achou, e a resposta vira um pedido de
        desculpas vago. Com os números ele pode dizer o que existe de verdade:
        "galpão para alugar tem, mas o mais barato é 12.500".
        """
        procurado = self._descrever_procurado(filtros)

        if universo == 0:
            return [f"O catálogo não tem nenhum {procurado}."]

        linhas = [f"O catálogo tem {universo} {procurado}."]
        fixos = {c: filtros[c] for c in self.FILTROS_FIXOS if filtros.get(c)}

        if preco_max := filtros.get("preco_max"):
            barato = self._extremo(db, fixos, Imovel.preco, "min")
            if barato is not None and barato > Decimal(str(preco_max)):
                linhas.append(
                    f"Nenhum cabe em {reais(preco_max)}: o mais barato é "
                    f"{reais(barato)}."
                )

        if preco_min := filtros.get("preco_min"):
            caro = self._extremo(db, fixos, Imovel.preco, "max")
            if caro is not None and caro < Decimal(str(preco_min)):
                linhas.append(
                    f"Nenhum passa de {reais(preco_min)}: o mais caro é "
                    f"{reais(caro)}."
                )

        if area_min := filtros.get("area_min"):
            maior = self._extremo(db, fixos, Imovel.area_m2, "max")
            if maior is not None and maior < Decimal(str(area_min)):
                linhas.append(
                    f"Nenhum chega a {float(area_min):g}m²: o maior tem {float(maior):g}m²."
                )

        if bairro := filtros.get("bairro"):
            onde = self._bairros(db, fixos, limite)
            if onde and not any(bairro.lower() in b.lower() for b in onde):
                linhas.append(
                    f"Não há em {bairro}. Há em: " + ", ".join(onde) + "."
                )

        return linhas

    def _descrever_procurado(self, filtros: dict[str, Any]) -> str:
        """"galpao para alugar", "imóvel comercial à venda" — em português."""
        tipo = filtros.get("tipo") or (
            f"imóvel {filtros['finalidade']}" if filtros.get("finalidade")
            else "imóvel"
        )
        operacao = filtros.get("operacao")
        if operacao == "aluguel":
            return f"{tipo} para alugar"
        if operacao == "venda":
            return f"{tipo} à venda"
        return tipo

    def _extremo(self, db: Session, fixos: dict[str, Any], coluna, ponta: str):
        agregado = func.min(coluna) if ponta == "min" else func.max(coluna)
        query = db.query(agregado).filter(Imovel.disponivel.is_(True))
        for campo, valor in fixos.items():
            query = query.filter(getattr(Imovel, campo) == valor)
        return query.scalar()

    def _bairros(self, db: Session, fixos: dict[str, Any], limite: int) -> list[str]:
        """Bairros onde o que a pessoa procura de fato existe, dos que mais têm."""
        query = (
            db.query(Imovel.bairro, func.count(Imovel.id).label("quantos"))
            .filter(Imovel.disponivel.is_(True))
        )
        for campo, valor in fixos.items():
            query = query.filter(getattr(Imovel, campo) == valor)
        linhas = (
            query.group_by(Imovel.bairro)
            .order_by(func.count(Imovel.id).desc(), Imovel.bairro.asc())
            .limit(limite)
            .all()
        )
        return [f"{bairro} ({quantos})" for bairro, quantos in linhas]

    def get_by_id(self, imovel_id: int, db: Session) -> Optional[Imovel]:
        """Busca um imóvel pelo ID."""
        return db.query(Imovel).filter(Imovel.id == imovel_id).first()

    def count_available(self, db: Session) -> int:
        """Retorna a quantidade de imóveis disponíveis."""
        return (
            db.query(func.count(Imovel.id))
            .filter(Imovel.disponivel.is_(True))
            .scalar() or 0
        )
