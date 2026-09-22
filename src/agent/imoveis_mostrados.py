"""Quais imóveis já foram oferecidos a cada lead nesta conversa.

Serve a uma coisa só: o agente de busca não deve reoferecer como novidade o que
a pessoa acabou de ver e não quis. Perguntar sobre um imóvel já mostrado —
*"aquele da Mooca, quanto era mesmo?"* — é outra coisa, e não passa por aqui.

Vive em memória, de propósito. O estado é da conversa, e uma conversa dura
menos que a validade da entrada; gravá-lo no banco criaria um artefato
permanente para responder a uma pergunta que só existe durante o atendimento.

O preço está escrito: some no restart do processo, e é por processo — Streamlit
e bot do Telegram rodam separados (ADR 0004). Como um lead conversa por um
canal de cada vez, e cada canal é um processo, isso não se nota dentro de um
atendimento. Uma conversa retomada no dia seguinte pode rever os mesmos
imóveis, o que é aceitável; o que não era aceitável é a pessoa receber o mesmo
apartamento três vezes no mesmo atendimento.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Renovada a cada nova apresentação, e não fixa desde a primeira: uma conversa
# de noventa minutos com atividade o tempo todo não deve esquecer no meio.
#
# Medida em relógio monotônico, e não no calendário: o que interessa aqui é
# tempo decorrido, e um ajuste de NTP para trás esvaziaria o cache no meio de
# um atendimento.
VALIDADE_EM_SEGUNDOS = 3600

# Teto de IDs lembrados por lead. Sem ele, uma conversa longa acumularia
# exclusões até estreitar o catálogo a ponto de não sobrar o que mostrar —
# lembrar demais e lembrar de menos falham do mesmo jeito, com a pessoa sem
# imóvel na tela. Os mais antigos saem primeiro: se ela voltou a um assunto
# depois de quarenta imóveis, rever o primeiro deles não é repetição.
TETO_POR_LEAD = 40

_lock = threading.Lock()
_por_lead: dict[int, tuple[float, list[int]]] = {}


def _expirada(quando: float, agora: float) -> bool:
    return agora - quando > VALIDADE_EM_SEGUNDOS


def registrar(lead_id: int, imovel_ids: list[int]) -> None:
    """Marca estes imóveis como já apresentados a este lead."""
    if not imovel_ids:
        return

    agora = time.monotonic()
    with _lock:
        _descartar_expiradas(agora)

        _, anteriores = _por_lead.get(lead_id, (agora, []))
        # `dict.fromkeys` preserva a ordem e elimina repetido: o ID que voltar
        # mantém a posição antiga, e não vira o mais recente da lista.
        juntos = list(dict.fromkeys([*anteriores, *imovel_ids]))
        _por_lead[lead_id] = (agora, juntos[-TETO_POR_LEAD:])


def ja_mostrados(lead_id: int) -> list[int]:
    """Os IDs já apresentados a este lead, do mais antigo ao mais recente."""
    agora = time.monotonic()
    with _lock:
        entrada = _por_lead.get(lead_id)
        if entrada is None:
            return []
        quando, ids = entrada
        if _expirada(quando, agora):
            del _por_lead[lead_id]
            return []
        return list(ids)


def esquecer(lead_id: int) -> None:
    """Apaga o que este lead já viu. Usado ao começar uma conversa nova."""
    with _lock:
        _por_lead.pop(lead_id, None)


def _descartar_expiradas(agora: float) -> None:
    """Limpa as entradas vencidas de todos os leads.

    Roda na escrita, e não num temporizador: o dicionário é pequeno, a varredura
    é barata, e um processo que ficou dias no ar sem buscar nada não deveria
    estar segurando conversa nenhuma na memória.

    Quem chama já está com o lock.
    """
    vencidos = [
        lead_id
        for lead_id, (quando, _) in _por_lead.items()
        if _expirada(quando, agora)
    ]
    for lead_id in vencidos:
        del _por_lead[lead_id]
    if vencidos:
        logger.info(
            "event=imoveis_mostrados_expirados leads=%s", len(vencidos)
        )
