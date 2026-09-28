"""Orquestração de um ciclo de follow-up automático.

Vive na camada de scheduler porque é o único ponto que combina domínio
(FollowUpService, LeadService) com agente (geração via LLM) e canal (envio).
Manter essa costura aqui evita que os services dependam do agente.

Um ciclo, para cada lead elegível:
  1. monta o contexto do lead;
  2. gera a mensagem contextual da régua via LLM;
  3. persiste a Mensagem (message_type='followup');
  4. registra o consumo de LLM (operation='followup');
  5. despacha pelo canal, quando há remetente disponível;
  6. registra o FollowUpAttempt com o desfecho;
  7. marca o lead como inativo se a régua de silêncio se esgotou.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Optional, Protocol

from src.agent.followup_agent import gerar_mensagem_followup
from src.agent.provider import LLMConfigError
from src.channels.envio import CANAIS_COM_ENVIO
from src.config import settings
from src.db.models import FollowUpAttempt, Mensagem
from src.db.session import get_db
from src.services.followup_service import REGUAS, FollowUpService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService
from src.tempo import formatar

logger = logging.getLogger(__name__)


class Sender(Protocol):
    """Despacha uma mensagem de follow-up pelo canal do lead.

    Deve devolver True quando a mensagem saiu de fato. Um canal sem envio
    ativo (Streamlit, por exemplo) simplesmente não é registrado como sender.
    """

    async def __call__(self, channel: str, external_chat_id: str, texto: str) -> bool:
        ...


def _montar_contexto(lead, regua: str, db) -> dict[str, object]:
    """Reúne, ainda dentro da sessão, tudo que a geração precisa."""
    lead_service = LeadService()

    historico = lead_service.get_history(lead.id, 4, db)
    ultima = historico[-1].content[:300] if historico else None

    contexto: dict[str, object] = {
        "nome": lead.nome,
        "intencao": lead.intencao,
        "orcamento_max": lead.orcamento_max,
        "bairro_interesse": lead.bairro_interesse,
        "regiao_interesse": lead.regiao_interesse,
        "quartos": lead.quartos,
        "urgencia": lead.urgencia,
        "motivo_busca": lead.motivo_busca,
        "perfil_narrativo": lead.perfil_narrativo,
        "ultima_mensagem": ultima,
    }

    if regua == "pos_agendamento":
        agendamentos = SchedulingService().list_by_lead(lead.id, db)
        proximo = next(
            (a for a in reversed(agendamentos) if a.status in ("pendente", "confirmado")),
            None,
        )
        if proximo:
            contexto["agendamento"] = (
                f"{proximo.tipo} em {formatar(proximo.data_hora)} "
                f"(status: {proximo.status})"
            )

    return contexto


async def run_followup_cycle(sender: Optional[Sender] = None) -> dict[str, int]:
    """Executa um ciclo completo de follow-up.

    Returns:
        Contadores do ciclo: elegiveis, enviados, gerados, falhas, inativados.
    """
    stats = {"elegiveis": 0, "enviados": 0, "gerados": 0, "falhas": 0, "inativados": 0}

    followup_service = FollowUpService()
    usage_service = LLMUsageService()

    with get_db() as db:
        # O budget é checado uma vez por ciclo: se o teto já estourou, nem vale
        # começar a gerar mensagens.
        if usage_service.is_daily_budget_exceeded(db):
            logger.warning("event=followup_abortado motivo=budget_diario_excedido")
            return stats
        if usage_service.is_monthly_budget_exceeded(db):
            logger.warning("event=followup_abortado motivo=budget_mensal_excedido")
            return stats

        elegiveis = [
            (lead.id, lead.canal_origem, regua, _montar_contexto(lead, regua, db))
            for lead, regua in followup_service.get_eligible_leads(db)
        ]

    stats["elegiveis"] = len(elegiveis)

    for lead_id, canal_origem, regua, contexto in elegiveis:
        await _processar_lead(lead_id, canal_origem, regua, contexto, sender, stats)

    logger.info("event=followup_ciclo_concluido %s", stats)
    return stats


@dataclass
class DisparoManual:
    """Desfecho de um follow-up disparado pelo corretor na tela.

    `executado` falso tem duas causas que a tela mostra de jeitos diferentes:
    uma regra que barrou o disparo (teto, budget, status sem régua), que é
    informação, e uma falha na geração (`falhou`), que é erro.
    """

    executado: bool
    motivo: str = ""
    stats: dict[str, int] = field(default_factory=dict)
    falhou: bool = False
    texto: str = ""
    regua: str = ""
    tentativa: int = 0
    maximo: int = 0
    canal: str = ""
    enviado: bool = False


@dataclass
class _Desfecho:
    """O que `_processar_lead` fez com um lead; o ciclo automático o ignora."""

    texto: str = ""
    canal: str = ""
    enviado: bool = False
    erro: str = ""


async def run_followup_para_lead(
    lead_id: int, sender: Optional[Sender] = None
) -> DisparoManual:
    """Dispara o follow-up de um lead só, a pedido do corretor.

    Mesma lógica do ciclo automático, gatilho diferente: o que se dispensa é
    apenas a janela de inatividade, que existe para o robô não ser inoportuno
    — o corretor, olhando o lead, já decidiu que é hora.

    O teto de tentativas da régua e o budget continuam valendo: são limites de
    custo e de insistência, não de tempo, e valem igual em qualquer gatilho.
    """
    stats = {"elegiveis": 0, "enviados": 0, "gerados": 0, "falhas": 0, "inativados": 0}
    followup_service = FollowUpService()
    usage_service = LLMUsageService()

    with get_db() as db:
        if usage_service.is_daily_budget_exceeded(db):
            return DisparoManual(False, "O orçamento diário de LLM já foi atingido.")
        if usage_service.is_monthly_budget_exceeded(db):
            return DisparoManual(False, "O orçamento mensal de LLM já foi atingido.")

        lead = LeadService().get_lead(lead_id, db)
        if lead is None:
            return DisparoManual(False, "Lead não encontrado.")

        regua = followup_service.regua_do_status(lead.status)
        if regua is None:
            return DisparoManual(
                False, f"Não há régua de follow-up para o status `{lead.status}`."
            )

        tentativas = followup_service.get_attempts_count(lead_id, regua, db)
        maximo = REGUAS[regua]["max_tentativas"]
        if tentativas >= maximo:
            return DisparoManual(
                False,
                f"A régua *{REGUAS[regua]['descricao']}* já esgotou as "
                f"{maximo} tentativas deste lead.",
            )

        canal_origem = lead.canal_origem
        contexto = _montar_contexto(lead, regua, db)

    stats["elegiveis"] = 1
    logger.info(
        "event=followup_disparo_manual lead_id=%s regua=%s tentativa=%s",
        lead_id, regua, tentativas + 1,
    )
    desfecho = await _processar_lead(
        lead_id, canal_origem, regua, contexto, sender, stats
    )
    return DisparoManual(
        executado=not desfecho.erro,
        motivo=desfecho.erro,
        stats=stats,
        falhou=bool(desfecho.erro),
        texto=desfecho.texto,
        regua=regua,
        tentativa=tentativas + 1,
        maximo=maximo,
        canal=desfecho.canal,
        enviado=desfecho.enviado,
    )


async def _processar_lead(
    lead_id: int,
    canal_origem: Optional[str],
    regua: str,
    contexto: dict[str, object],
    sender: Optional[Sender],
    stats: dict[str, int],
) -> _Desfecho:
    """Gera, persiste, despacha e registra o follow-up de um lead.

    Extraido do ciclo para que o disparo manual do dashboard passe exatamente
    pelo mesmo caminho: mesma geracao, mesma persistencia, mesmo registro de
    tentativa. O que muda entre os dois e so quem escolhe o lead.

    Nao propaga excecao — um lead com problema nao derruba o ciclo. Quem
    precisa saber se deu certo, como o botao do dashboard, le o desfecho.
    """
    followup_service = FollowUpService()
    lead_service = LeadService()
    usage_service = LLMUsageService()

    try:
        with get_db() as db:
            tentativa = followup_service.get_attempts_count(lead_id, regua, db) + 1

        gerado = await gerar_mensagem_followup(contexto, regua, tentativa)
        if not gerado.texto:
            raise ValueError("LLM devolveu mensagem vazia")

        with get_db() as db:
            identidade = lead_service.get_primary_identity(lead_id, db)
            canal = identidade.channel if identidade else (canal_origem or "desconhecido")
            chat_id = identidade.external_chat_id if identidade else None

            msg = lead_service.save_message(
                lead_id=lead_id,
                channel=canal,
                role="assistant",
                content=gerado.texto,
                message_type="followup",
                db=db,
                status="generated",
            )
            message_id = msg.id

            usage_service.record(
                lead_id=lead_id,
                model=settings.LLM_MODEL,
                tokens_in=gerado.tokens_in,
                tokens_out=gerado.tokens_out,
                operation="followup",
                db=db,
            )

        enviado = False
        motivo_falha: Optional[str] = None
        # Só se tenta enviar por canal que tem envio. No Streamlit a mensagem
        # gravada já é o desfecho — aparece no chat do lead —, e pedir ao
        # remetente para enviá-la só produzia uma recusa registrada como falha.
        vai_pelo_canal = bool(sender and chat_id and canal in CANAIS_COM_ENVIO)
        if vai_pelo_canal:
            try:
                enviado = await sender(canal, chat_id, gerado.texto)
                if not enviado:
                    motivo_falha = "canal recusou o envio"
            except Exception as e:
                motivo_falha = f"{type(e).__name__}: {e}"[:120]
                logger.exception(
                    "event=followup_envio_falhou lead_id=%s canal=%s", lead_id, canal
                )
        elif not sender and canal in CANAIS_COM_ENVIO:
            motivo_falha = "sem remetente ativo para o canal"

        with get_db() as db:
            if enviado:
                lead_service.mark_message_sent(message_id, db)
                status_tentativa = "sent"
                stats["enviados"] += 1
            else:
                # A mensagem existe e aparece no painel do corretor mesmo
                # sem despacho ativo — isso não é uma falha de geração.
                status_tentativa = "failed" if vai_pelo_canal else "generated"
                stats["gerados" if status_tentativa == "generated" else "falhas"] += 1

            followup_service.record_attempt(
                lead_id=lead_id,
                regua=regua,
                status=status_tentativa,
                db=db,
                message_id=message_id,
                failure_reason=motivo_falha,
            )

            if followup_service.deve_marcar_inativo(lead_id, regua, db):
                lead_service.update_status(lead_id, "inativo", db)
                stats["inativados"] += 1
                logger.info(
                    "event=lead_inativado lead_id=%s regua=%s "
                    "motivo=tentativas_esgotadas", lead_id, regua,
                )

        logger.info(
            "event=followup_processado lead_id=%s regua=%s tentativa=%s enviado=%s",
            lead_id, regua, tentativa, enviado,
        )
        return _Desfecho(texto=gerado.texto, canal=canal, enviado=enviado)

    except LLMConfigError as e:
        logger.error("event=followup_llm_config_error lead_id=%s erro=%s", lead_id, e)
        stats["falhas"] += 1
        return _Desfecho(erro=f"O modelo de linguagem não está configurado: {e}")
    except Exception as e:
        stats["falhas"] += 1
        logger.exception(
            "event=followup_falhou lead_id=%s regua=%s tipo_erro=%s",
            lead_id, regua, type(e).__name__,
        )
        motivo = f"{type(e).__name__}: {e}"[:120]
        with get_db() as db:
            followup_service.record_attempt(
                lead_id=lead_id, regua=regua, status="failed", db=db,
                failure_reason=motivo,
            )
        return _Desfecho(erro=f"A geração falhou ({motivo}).")


# Quanto tempo um follow-up gerado sem despacho ainda pode sair pelo canal. Ele
# nasce assim quando quem o gerou não tinha remetente — o botão do painel, o
# script de ciclo avulso — e fica à espera do processo do Telegram. Passado
# isso ele perdeu a hora: a conversa andou, ou a pessoa já não espera por ele.
VALIDADE_DO_PENDENTE = timedelta(minutes=15)


@dataclass
class _Pendente:
    """Um follow-up à espera de despacho, lido numa transação curta."""

    tentativa_id: int
    message_id: int
    lead_id: int
    canal: str
    chat_id: str
    texto: str


async def dispatch_pending_followups(sender: Optional[Sender] = None) -> dict[str, int]:
    """Envia pelo canal os follow-ups que ficaram gerados sem despacho.

    Só sai o que ainda faz sentido mandar: canal com envio, gerado há menos
    de `VALIDADE_DO_PENDENTE`, sem resposta do lead depois dele, e só o mais
    recente de cada lead. O resto vira `skipped`, com o motivo — e continua
    contando no teto da régua, como qualquer tentativa.

    A tentativa é reservada como `sent` antes de ir à rede, numa transação
    curta, e só volta a `failed` se o envio der errado. Assim nenhuma linha
    fica travada enquanto o canal responde, e duas execuções nunca mandam a
    mesma mensagem: a segunda não consegue reservar. O preço é o caso inverso
    — o processo cair entre a reserva e o envio deixa `sent` o que não saiu —,
    e uma mensagem perdida é melhor que a mesma mensagem duas vezes para uma
    pessoa.
    """
    stats = {"enviados": 0, "falhas": 0, "descartados": 0}
    if sender is None:
        return stats

    for pendente in _triar_pendentes(stats):
        with get_db() as db:
            reservou = (
                db.query(FollowUpAttempt)
                .filter(
                    FollowUpAttempt.id == pendente.tentativa_id,
                    FollowUpAttempt.status == "generated",
                )
                .update({"status": "sent"}, synchronize_session=False)
            )
        if not reservou:
            continue

        falha: Optional[str] = None
        try:
            if not await sender(pendente.canal, pendente.chat_id, pendente.texto):
                falha = "canal recusou o envio"
        except Exception as e:
            falha = f"{type(e).__name__}: {e}"[:120]
            logger.exception(
                "event=followup_pendente_falhou lead_id=%s", pendente.lead_id
            )

        with get_db() as db:
            if falha is None:
                LeadService().mark_message_sent(pendente.message_id, db)
                stats["enviados"] += 1
            else:
                db.query(FollowUpAttempt).filter(
                    FollowUpAttempt.id == pendente.tentativa_id
                ).update(
                    {"status": "failed", "failure_reason": falha},
                    synchronize_session=False,
                )
                stats["falhas"] += 1

        logger.info(
            "event=followup_pendente_despachado lead_id=%s message_id=%s enviado=%s",
            pendente.lead_id, pendente.message_id, falha is None,
        )

    return stats


def _triar_pendentes(stats: dict[str, int]) -> list[_Pendente]:
    """Separa o que ainda deve sair e marca o resto como `skipped`.

    Lê e decide numa transação só, sem ir à rede. Mensagem de canal sem envio
    nem entra na consulta: para ela `generated` já é o estado final.
    """
    agora = datetime.now(UTC)
    lead_service = LeadService()
    a_enviar: list[_Pendente] = []
    ja_vistos: set[int] = set()

    with get_db() as db:
        pendentes = (
            db.query(FollowUpAttempt, Mensagem)
            .join(Mensagem, FollowUpAttempt.message_id == Mensagem.id)
            .filter(
                FollowUpAttempt.status == "generated",
                Mensagem.channel.in_(CANAIS_COM_ENVIO),
            )
            # O mais recente de cada lead primeiro: é ele que sai.
            .order_by(FollowUpAttempt.lead_id, Mensagem.id.desc())
            .all()
        )

        for tentativa, mensagem in pendentes:
            identidade = lead_service.get_primary_identity(tentativa.lead_id, db)
            if tentativa.lead_id in ja_vistos:
                motivo = "substituído por um follow-up mais recente"
            elif agora - tentativa.created_at > VALIDADE_DO_PENDENTE:
                motivo = "expirou sem despacho"
            elif _lead_respondeu_depois(mensagem, db):
                motivo = "o lead respondeu antes do envio"
            elif (
                identidade is None
                or identidade.channel not in CANAIS_COM_ENVIO
                or not identidade.external_chat_id
            ):
                motivo = "sem chat_id em canal com envio"
            else:
                motivo = None
            ja_vistos.add(tentativa.lead_id)

            if motivo:
                tentativa.status = "skipped"
                tentativa.failure_reason = motivo
                stats["descartados"] += 1
                logger.info(
                    "event=followup_pendente_descartado lead_id=%s motivo=%s",
                    tentativa.lead_id, motivo,
                )
                continue

            a_enviar.append(_Pendente(
                tentativa_id=tentativa.id,
                message_id=mensagem.id,
                lead_id=tentativa.lead_id,
                canal=identidade.channel,
                chat_id=identidade.external_chat_id,
                texto=mensagem.content,
            ))

    return a_enviar


def _lead_respondeu_depois(mensagem: Mensagem, db) -> bool:
    """O lead escreveu depois deste follow-up ter sido gerado?"""
    return db.query(
        db.query(Mensagem)
        .filter(
            Mensagem.lead_id == mensagem.lead_id,
            Mensagem.role == "user",
            Mensagem.id > mensagem.id,
        )
        .exists()
    ).scalar()
