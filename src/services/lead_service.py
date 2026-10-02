"""Serviço para gestão de leads."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import (
    Agendamento,
    FollowUpAttempt,
    Lead,
    LeadChannelIdentity,
    LLMUsage,
    Mensagem,
)
from src.schemas.lead import LeadStatus

logger = logging.getLogger(__name__)


# Limites de tamanho lidos do próprio modelo, para não duplicar o schema aqui.
LIMITES_DE_TEXTO = {
    coluna.name: coluna.type.length
    for coluna in Lead.__table__.columns
    if getattr(coluna.type, "length", None)
}

# Campos com vocabulário fechado no banco (CHECK constraints). Um valor fora
# da lista derrubaria o INSERT, então é descartado antes de chegar lá.
VALORES_PERMITIDOS = {
    "intencao": {"compra", "aluguel", "investimento"},
    "urgencia": {"baixa", "media", "alta"},
}

# Pesos das cinco dimensões do score, que somados dão 10. Forma de pagamento
# não está entre elas: a conversa nunca chega nesse dado, e um ponto que
# ninguém consegue ganhar só empurra a régua inteira para baixo.
PESO_URGENCIA = {"alta": 2.0, "media": 1.0, "baixa": 0.5}
PESO_TIPOLOGIA = 1.0
PESO_AGENDAMENTO = 2.5

# Cada um dos seis campos-chave da ficha vale meio ponto, e juntos fecham os
# 3.0 da completude. Meio ponto por campo em vez de faixas largas: assim todo
# dado que a conversa arranca move o número, e não só o que cruza um degrau.
PONTO_POR_CAMPO_DA_FICHA = 0.5

# Quantas mensagens da pessoa valem quantos pontos de engajamento.
FAIXAS_DE_ENGAJAMENTO = ((11, 1.5), (6, 1.0), (1, 0.5))

# Visita marcada é o evento de conversão do funil, e o score existe para
# ordenar a fila de quem o corretor liga primeiro. Sem um piso próprio ela
# valia menos que a completude do cadastro: um lead com visita na agenda
# empatava com um lead que já tinha parado de responder.
PISO_COM_VISITA_MARCADA = 7.0


def _campos_da_ficha(lead: Lead) -> tuple[bool, ...]:
    """Os seis campos-chave da qualificação, cada um presente ou ausente.

    Telefone está na lista porque o score ordena a fila de ligações: uma
    ficha impecável sem número não chega a virar contato, e o corretor que
    liga primeiro para ela perde o turno.

    Devolve a tupla, e não a contagem, para que o tamanho da ficha seja um
    fato do código — é dele que o teto da régua é conferido.
    """
    return (
        bool(lead.intencao),
        lead.orcamento_min is not None or lead.orcamento_max is not None,
        bool(lead.bairro_interesse or lead.regiao_interesse),
        lead.quartos is not None,
        bool(lead.urgencia),
        bool(lead.telefone),
    )


def _degrau(quantidade: int, faixas: tuple[tuple[int, float], ...]) -> float:
    """Pontos da primeira faixa que a quantidade alcança; zero se nenhuma."""
    for piso, pontos in faixas:
        if quantidade >= piso:
            return pontos
    return 0.0


@dataclass(frozen=True)
class ConversaResumo:
    """Uma conversa como o seletor do simulador precisa ver."""
    lead_id: int
    nome: Optional[str]
    status: str
    canal: Optional[str]
    total_mensagens: int
    ultima_atividade: Optional[datetime]

    def rotulo(self) -> str:
        partes = [f"Lead #{self.lead_id}"]
        if self.nome:
            partes.append(self.nome)
        partes.append(self.status)
        if self.canal:
            partes.append(self.canal)
        partes.append(f"{self.total_mensagens} msgs")
        return " · ".join(partes)


class LeadService:
    """Serviço de domínio para gestão de leads."""

    def sanitizar_qualificacao(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ajusta os dados vindos da LLM aos limites do banco.

        As tools recebem texto livre de um modelo de linguagem; sem esta
        barreira, um valor fora do vocabulário ou maior que a coluna derruba o
        turno inteiro com DataError/IntegrityError.
        """
        limpo: dict[str, Any] = {}

        for campo, valor in data.items():
            if not isinstance(valor, str):
                limpo[campo] = valor
                continue

            valor = valor.strip()

            permitidos = VALORES_PERMITIDOS.get(campo)
            if permitidos:
                normalizado = valor.lower()
                if normalizado not in permitidos:
                    logger.warning(
                        "event=valor_fora_do_vocabulario campo=%s valor=%r "
                        "permitidos=%s acao=descartado",
                        campo, valor[:60], sorted(permitidos),
                    )
                    continue
                valor = normalizado

            limite = LIMITES_DE_TEXTO.get(campo)
            if limite and len(valor) > limite:
                logger.warning(
                    "event=valor_truncado campo=%s tamanho=%s limite=%s valor=%r",
                    campo, len(valor), limite, valor[:60],
                )
                valor = valor[:limite]

            limpo[campo] = valor

        return limpo

    def get_or_create_lead(
        self,
        channel: str,
        external_id: str,
        db: Session,
        nome: Optional[str] = None,
    ) -> Lead:
        """Busca lead existente ou cria um novo para o canal."""
        identity = (
            db.query(LeadChannelIdentity)
            .filter_by(channel=channel, external_chat_id=external_id)
            .first()
        )

        if identity:
            identity.last_seen_at = func.now()
            if nome and not identity.lead.nome:
                identity.lead.nome = nome
            db.commit()
            return identity.lead

        lead = Lead(
            status=LeadStatus.NOVO.value,
            score=Decimal("0.0"),
            canal_origem=channel,
            nome=nome,
        )
        db.add(lead)
        db.flush()

        new_identity = LeadChannelIdentity(
            lead_id=lead.id,
            channel=channel,
            external_chat_id=external_id,
            is_primary=True,
        )
        db.add(new_identity)
        db.commit()
        db.refresh(lead)
        logger.info(
            "event=lead_criado lead_id=%s channel=%s status=%s",
            lead.id, channel, lead.status,
        )
        return lead

    def get_lead(self, lead_id: int, db: Session) -> Optional[Lead]:
        """Busca um lead pelo ID."""
        return db.query(Lead).filter(Lead.id == lead_id).first()

    def update_qualification(
        self, lead_id: int, data: dict[str, Any], db: Session
    ) -> Optional[Lead]:
        """Atualiza os dados de qualificação de um lead."""
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return None

        for key, value in self.sanitizar_qualificacao(data).items():
            if hasattr(lead, key) and value is not None:
                setattr(lead, key, value)

        lead.status = self.avaliar_status(lead)

        db.commit()
        db.refresh(lead)
        return lead

    # Campos que o corretor edita na ficha. Fora desta lista nada é gravado por
    # essa via: score é calculado, resumo é gerado, e id/datas são do banco.
    CAMPOS_EDITAVEIS = (
        "nome", "telefone", "intencao", "tipologia_interesse",
        "orcamento_min", "orcamento_max", "forma_pagamento",
        "regiao_interesse", "bairro_interesse", "quartos", "urgencia",
        "motivo_busca", "perfil", "amenidades_desejadas", "perfil_narrativo",
        "status",
    )

    def editar_lead(
        self, lead_id: int, campos: dict[str, Any], db: Session
    ) -> Optional[Lead]:
        """Grava a ficha editada pelo corretor, exatamente como ele a deixou.

        Diferente de `update_qualification`, que vem da LLM: lá o `None`
        significa "o modelo não falou disso" e é ignorado, aqui significa "o
        corretor apagou este campo" e é gravado. Sem essa distinção não haveria
        como limpar um dado que o agente entendeu errado.

        O status também não é recalculado: se o corretor moveu o lead no funil
        de propósito, `avaliar_status` desfaria a decisão dele no mesmo clique.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return None

        for campo, valor in campos.items():
            if campo in self.CAMPOS_EDITAVEIS:
                setattr(lead, campo, valor)

        db.commit()
        db.refresh(lead)
        logger.info(
            "event=lead_editado lead_id=%s campos=%s",
            lead_id, sorted(c for c in campos if c in self.CAMPOS_EDITAVEIS),
        )
        return lead

    def criar_lead_manual(
        self, campos: dict[str, Any], db: Session
    ) -> Lead:
        """Cria um lead pela ficha, sem conversa que o tenha originado.

        Nasce em `novo` e com score zero, como qualquer lead: o score vem dos
        dados e do engajamento, e `calculate_score` recalcula na sequência.
        """
        lead = Lead(status=LeadStatus.NOVO.value, score=Decimal("0.0"))
        db.add(lead)
        db.flush()

        for campo, valor in campos.items():
            if campo in self.CAMPOS_EDITAVEIS:
                setattr(lead, campo, valor)

        db.commit()
        db.refresh(lead)
        logger.info("event=lead_criado lead_id=%s channel=manual status=%s",
                    lead.id, lead.status)
        return lead

    def definir_identidade(
        self, lead_id: int, channel: str, external_chat_id: str, db: Session
    ) -> Optional[LeadChannelIdentity]:
        """Liga o lead a um canal de conversa, ou corrige o que ele já tem.

        É o que torna um lead criado à mão alcançável pelo follow-up: sem
        identidade, `get_primary_identity` devolve `None`, o runner não acha
        para onde despachar e a mensagem fica só registrada no painel.

        O `external_chat_id` precisa ser o identificador real do canal — no
        Telegram, o `chat_id` numérico que o bot enxerga. Um valor inventado
        faz o envio falhar no canal, não aqui.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return None

        identidade = (
            db.query(LeadChannelIdentity)
            .filter(
                LeadChannelIdentity.lead_id == lead_id,
                LeadChannelIdentity.channel == channel,
            )
            .first()
        )
        if identidade is None:
            identidade = LeadChannelIdentity(lead_id=lead_id, channel=channel)
            db.add(identidade)

        identidade.external_chat_id = external_chat_id
        # Passa a ser a preferencial, e as outras deixam de ser: o corretor
        # acabou de dizer por onde falar com este lead.
        db.query(LeadChannelIdentity).filter(
            LeadChannelIdentity.lead_id == lead_id
        ).update({"is_primary": False}, synchronize_session=False)
        db.flush()
        identidade.is_primary = True

        if not lead.canal_origem:
            lead.canal_origem = channel

        db.commit()
        db.refresh(identidade)
        logger.info(
            "event=identidade_definida lead_id=%s channel=%s", lead_id, channel
        )
        return identidade

    # Dados mínimos que caracterizam um lead qualificado: sem eles o corretor
    # não consegue trabalhar a oportunidade.
    CAMPOS_DE_QUALIFICACAO = (
        ("intencao",),
        ("orcamento_min", "orcamento_max"),
        ("bairro_interesse", "regiao_interesse"),
        ("quartos",),
    )

    def esta_qualificado(self, lead: Lead) -> bool:
        """Indica se o lead já tem os dados mínimos de qualificação."""
        return all(
            any(getattr(lead, campo, None) is not None for campo in grupo)
            for grupo in self.CAMPOS_DE_QUALIFICACAO
        )

    def avaliar_status(self, lead: Lead) -> str:
        """Calcula o status do lead no funil a partir dos dados coletados.

        Só avança leads ainda em coleta: quem já agendou não regride, e quem
        está inativo só volta ao funil quando responde (ver process_message).
        """
        if lead.status not in (LeadStatus.NOVO.value, LeadStatus.EM_QUALIFICACAO.value):
            return lead.status

        if self.esta_qualificado(lead):
            return LeadStatus.QUALIFICADO.value

        return LeadStatus.EM_QUALIFICACAO.value

    def status_sem_compromisso(self, lead: Lead) -> str:
        """Status que o lead teria se nao houvesse compromisso marcado.

        `agendado` afirma que existe uma visita ou reuniao de pe. Quando o
        ultimo compromisso e apagado ou cancelado, essa afirmacao deixa de ser
        verdadeira e o lead precisa voltar para onde os dados dele o colocam —
        senao ele fica parado num estagio que ninguem consegue explicar
        olhando a ficha.
        """
        if self.esta_qualificado(lead):
            return LeadStatus.QUALIFICADO.value
        return LeadStatus.EM_QUALIFICACAO.value

    def update_perfil_narrativo(
        self, lead_id: int, novo_texto: str, db: Session
    ) -> Optional[Lead]:
        """Grava o perfil narrativo do lead.

        Recebe o texto inteiro e o substitui. Quem monta esse texto é o agente
        de consolidação (`src.agent.perfil_agent`), que junta o perfil anterior
        com a novidade do turno antes de chegar aqui — a coerência e o acúmulo
        se resolvem lá, e esta camada só persiste o resultado.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return None

        lead.perfil_narrativo = novo_texto
        db.commit()
        db.refresh(lead)
        logger.info(
            "event=perfil_narrativo_atualizado lead_id=%s tamanho=%s",
            lead_id, len(novo_texto or ""),
        )
        return lead

    def calculate_score(self, lead_id: int, db: Session) -> Decimal:
        """Calcula e persiste o score do lead, de 0 a 10.

        Cinco dimensões: completude da ficha (3.0), urgência declarada (2.0),
        tipologia definida (1.0), engajamento na conversa (1.5) e visita
        marcada (2.5), com piso de 7.0 para quem tem compromisso de pé.

        Urgência aparece duas vezes de propósito, e não é engano de contagem:
        na completude conta ter o dado, na dimensão própria conta o quanto
        ele aperta. Quem precisa mudar em trinta dias e quem pode esperar um
        ano contaram a mesma coisa, mas não valem a mesma ligação.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return Decimal("0.0")

        mensagens = (
            db.query(func.count(Mensagem.id))
            .filter(Mensagem.lead_id == lead.id, Mensagem.role == "user")
            .scalar() or 0
        )
        score = (
            sum(_campos_da_ficha(lead)) * PONTO_POR_CAMPO_DA_FICHA
            + PESO_URGENCIA.get(lead.urgencia or "", 0.0)
            + (PESO_TIPOLOGIA if lead.tipologia_interesse else 0.0)
            + _degrau(mensagens, FAIXAS_DE_ENGAJAMENTO)
        )
        if self._tem_visita_marcada(lead_id, db):
            score = max(score + PESO_AGENDAMENTO, PISO_COM_VISITA_MARCADA)

        lead.score = Decimal(str(round(score, 2)))
        db.commit()

        return lead.score

    @staticmethod
    def _tem_visita_marcada(lead_id: int, db: Session) -> bool:
        """Se há visita ou reunião de pé — cancelada e realizada não contam.

        O import é tardio porque `scheduling_service` importa este módulo; no
        topo seria um ciclo. Vale a volta para não haver duas definições de
        quais status ainda estão de pé.
        """
        from src.services.scheduling_service import SchedulingService

        return SchedulingService().tem_compromisso_ativo(lead_id, db)

    def update_status(
        self, lead_id: int, new_status: str, db: Session
    ) -> None:
        """Atualiza o status de um lead."""
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead:
            lead.status = new_status
            db.commit()

    def save_message(
        self,
        lead_id: int,
        channel: str,
        role: str,
        content: str,
        message_type: str,
        db: Session,
        status: str = "created",
        metadata_json: Optional[dict] = None,
    ) -> Mensagem:
        """Salva uma mensagem no histórico.

        `metadata_json` carrega o que não cabe em `content`: numa linha de
        `role="tool"`, o nome da ferramenta, os argumentos e o id da chamada,
        que é o que permite remontar o par chamada/retorno no turno seguinte.
        """
        msg = Mensagem(
            lead_id=lead_id,
            channel=channel,
            role=role,
            content=content,
            message_type=message_type,
            status=status,
            metadata_json=metadata_json,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        # `role` distingue o que chegou do lead do que o agente respondeu;
        # o conteúdo fica de fora de propósito, porque é dado pessoal.
        logger.info(
            "event=mensagem_registrada lead_id=%s mensagem_id=%s channel=%s "
            "role=%s tipo=%s tamanho=%s status=%s",
            lead_id, msg.id, channel, role, message_type, len(content or ""), status,
        )
        return msg

    def mark_message_sent(self, message_id: int, db: Session) -> None:
        """Marca uma mensagem como efetivamente enviada ao canal."""
        msg = db.query(Mensagem).filter(Mensagem.id == message_id).first()
        if msg:
            msg.status = "sent"
            msg.sent_at = datetime.now(UTC)
            db.commit()

    def get_primary_identity(
        self, lead_id: int, db: Session
    ) -> Optional[LeadChannelIdentity]:
        """Identidade de canal preferencial do lead, para envio ativo."""
        return (
            db.query(LeadChannelIdentity)
            .filter(LeadChannelIdentity.lead_id == lead_id)
            .order_by(LeadChannelIdentity.is_primary.desc(), LeadChannelIdentity.id)
            .first()
        )

    def has_message_type(
        self, lead_id: int, message_type: str, db: Session
    ) -> bool:
        """Indica se o lead já possui alguma mensagem do tipo informado."""
        return (
            db.query(Mensagem.id)
            .filter(
                Mensagem.lead_id == lead_id,
                Mensagem.message_type == message_type,
            )
            .first()
            is not None
        )

    # Linhas que contam para o `limit` do histórico: são as falas da conversa.
    # As de `tool` entram de carona na janela que estas delimitam.
    PAPEIS_DA_CONVERSA = ("user", "assistant")

    def ja_respondeu(self, lead_id: int, db: Session) -> bool:
        """Se o agente já falou com este lead alguma vez.

        É o que separa a primeira mensagem da conversa das demais, e só na
        primeira a Marina se apresenta. Uma pergunta de existência sobre o
        índice de `lead_id`, e não uma leitura do histórico: a resposta é um
        booleano e roda a cada turno.
        """
        return db.query(
            db.query(Mensagem)
            .filter(Mensagem.lead_id == lead_id, Mensagem.role == "assistant")
            .exists()
        ).scalar()

    def imoveis_apresentados(self, lead_id: int, db: Session) -> list[int]:
        """IDs dos imóveis já mostrados a este lead, do mais antigo ao recente.

        Lidos do `metadata_json` das mensagens de ferramenta, e não do texto
        delas: o retorno da busca é abreviado em 900 caracteres ao voltar ao
        histórico, e numa conversa real isso derrubou metade dos IDs — três de
        seis. O que a pessoa viu na tela precisa de um registro que não dependa
        de caber numa janela de contexto.

        No banco, e não em memória, porque disto dependem duas coisas que não
        podem sumir num restart: responder sobre um imóvel já apresentado e
        marcar visita nele. Streamlit e bot rodam em processos separados
        (ADR 0004), e memória de processo não atravessa essa fronteira.
        """
        linhas = (
            db.query(Mensagem.metadata_json)
            .filter(Mensagem.lead_id == lead_id, Mensagem.role == "tool")
            .order_by(Mensagem.id)
            .all()
        )
        # Dict em vez de set: preserva a ordem de apresentação, que é o que faz
        # "o último que você me mostrou" significar alguma coisa.
        vistos: dict[int, None] = {}
        for (meta,) in linhas:
            for imovel_id in ((meta or {}).get("busca") or {}).get("imovel_ids") or []:
                vistos[imovel_id] = None
        return list(vistos)

    def get_history(
        self, lead_id: int, limit: int, db: Session
    ) -> list[Mensagem]:
        """As últimas `limit` falas do lead, com as tools que houve entre elas.

        O limite conta só `user` e `assistant`. Se contasse tudo, uma conversa
        com muitas buscas gastaria a janela em linhas de ferramenta e o agente
        esqueceria o que a pessoa disse — o oposto do que o histórico serve.

        A ordem é por `id`, e não por `timestamp`: uma chamada de ferramenta e
        a resposta que ela gerou caem no mesmo segundo, e empate de timestamp
        embaralharia o par chamada/retorno, que precisa chegar junto e na
        ordem certa para o modelo aceitar.
        """
        falas = (
            db.query(Mensagem.id)
            .filter(
                Mensagem.lead_id == lead_id,
                Mensagem.role.in_(self.PAPEIS_DA_CONVERSA),
            )
            .order_by(Mensagem.id.desc())
            .limit(limit)
            .all()
        )
        if not falas:
            return []

        return (
            db.query(Mensagem)
            .filter(Mensagem.lead_id == lead_id, Mensagem.id >= min(f.id for f in falas))
            .order_by(Mensagem.id.asc())
            .all()
        )

    def delete_lead(self, lead_id: int, db: Session) -> bool:
        """Remove um lead e tudo que depende dele.

        O consumo de LLM nao e apagado junto: os tokens foram gastos de fato e
        os budgets diario e mensal continuam tendo que enxerga-los. As linhas
        so perdem o vinculo com o lead (`lead_id` fica nulo), senao apagar
        leads viraria uma forma de zerar o controle de custo.

        A ordem segue as chaves estrangeiras, de folha para raiz.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return False

        db.query(FollowUpAttempt).filter(
            FollowUpAttempt.lead_id == lead_id
        ).delete(synchronize_session=False)
        db.query(Agendamento).filter(
            Agendamento.lead_id == lead_id
        ).delete(synchronize_session=False)
        db.query(LeadChannelIdentity).filter(
            LeadChannelIdentity.lead_id == lead_id
        ).delete(synchronize_session=False)
        db.query(LLMUsage).filter(LLMUsage.lead_id == lead_id).update(
            {"lead_id": None}, synchronize_session=False
        )
        db.query(Mensagem).filter(
            Mensagem.lead_id == lead_id
        ).delete(synchronize_session=False)

        db.delete(lead)
        db.commit()
        logger.info("event=lead_removido lead_id=%s", lead_id)
        return True

    def list_conversations(
        self, db: Session, limit: int = 50
    ) -> list["ConversaResumo"]:
        """Conversas com pelo menos uma mensagem, da mais recente para a mais antiga.

        Nao filtra por canal nem por usuario: o seletor do simulador precisa
        alcancar qualquer conversa, inclusive as que vieram do Telegram ou de
        outro corretor. Filtrar pelo prefixo do usuario, como antes, deixava a
        lista visivelmente incompleta.
        """
        ultima = func.max(Mensagem.timestamp).label("ultima")
        total = func.count(Mensagem.id).label("total")

        linhas = (
            db.query(Lead, total, ultima)
            .join(Mensagem, Mensagem.lead_id == Lead.id)
            .group_by(Lead.id)
            .order_by(ultima.desc())
            .limit(limit)
            .all()
        )
        return [
            ConversaResumo(
                lead_id=lead.id,
                nome=lead.nome,
                status=lead.status,
                canal=lead.canal_origem,
                total_mensagens=total_msgs,
                ultima_atividade=ultima_em,
            )
            for lead, total_msgs, ultima_em in linhas
        ]

    def count_messages(self, lead_id: int, db: Session) -> int:
        """Quantidade de mensagens registradas para o lead."""
        return (
            db.query(func.count(Mensagem.id))
            .filter(Mensagem.lead_id == lead_id)
            .scalar() or 0
        )

    def get_leads_for_dashboard(
        self, filters: dict[str, Any], db: Session
    ) -> list[Lead]:
        """Busca leads para o painel do corretor com filtros."""
        query = db.query(Lead)

        if filters.get("status"):
            query = query.filter(Lead.status == filters["status"])
        if filters.get("intencao"):
            query = query.filter(Lead.intencao == filters["intencao"])

        return query.order_by(Lead.score.desc().nullslast()).limit(50).all()
