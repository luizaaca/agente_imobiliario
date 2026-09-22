"""Os três cenários obrigatórios do desafio, ponta a ponta.

O provider LLM é simulado: o que se valida aqui é o encadeamento real de
agente, tools, services, banco e canal — não a qualidade do texto gerado.
"""

import asyncio

import pytest
from sqlalchemy import text

from src.agent import followup_agent as followup_agent_mod
from src.agent import sdr_agent as agent_mod
from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.models import Agendamento, FollowUpAttempt, Mensagem
from src.scheduler.followup_runner import run_followup_cycle
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

from .conftest import escolha_da_busca

pytestmark = pytest.mark.cenario


def deps_de(lead_id, canal="teste"):
    return SDRDependencies(
        lead_id=lead_id,
        channel=canal,
        lead_service=LeadService(),
        catalog_service=CatalogService(),
        scheduling_service=SchedulingService(),
        llm_usage_service=LLMUsageService(),
    )


def conversar(lead_id, texto, modelo, db, canal="teste"):
    """Executa um turno e sincroniza a sessão do teste.

    As tools gravam por sessões próprias (`get_db()`), então sem expirar a
    identity map o teste continuaria enxergando o objeto antigo.
    """
    with agent_mod.sdr_agent.override(model=modelo):
        resposta = asyncio.run(
            process_message(lead_id, texto, canal, deps_de(lead_id, canal))
        )
    db.expire_all()
    return resposta


# --- Cenário 1: compra residencial ------------------------------------------


def _retorno_da_busca(lead_id, db) -> str:
    """O que a tool de busca devolveu neste cenario.

    Um cenario chama varias tools, e todas gravam com `role="tool"`: o nome
    fica no `metadata_json`, e e por ele que se acha a busca.
    """
    linhas = [
        m for m in db.query(Mensagem).filter(
            Mensagem.lead_id == lead_id, Mensagem.role == "tool"
        ).order_by(Mensagem.id).all()
        if (m.metadata_json or {}).get("tool_name") == "buscar_imoveis"
    ]
    assert len(linhas) == 1, f"esperava uma busca, achei {len(linhas)}"
    return linhas[0].content


def test_cenario_1_compra_residencial(llm_fake, busca_fake, catalogo, db):
    """Saudação → qualificação → busca no catálogo → agendamento de visita."""
    lead_service = LeadService()
    lead_id = lead_service.get_or_create_lead(
        channel="teste", external_id="cenario1", db=db, nome="Carla"
    ).id

    # 1. Saudação: o lead entra no funil
    conversar(lead_id, "Oi! Estou procurando um apartamento para comprar.",
              llm_fake("Ola Carla! Em qual regiao voce procura?"), db)
    assert lead_service.get_lead(lead_id, db).status == "em_qualificacao"

    # 2. Qualificação: os dados estruturados são registrados
    conversar(lead_id, "Bela Vista, ate 700 mil, 2 quartos.", llm_fake(
        ("registrar_qualificacao", {
            "intencao": "compra", "bairro_interesse": "Bela Vista",
            "orcamento_max": 700000, "quartos": 2, "urgencia": "alta",
        }),
        "Perfeito, ja anotei!",
    ), db)
    lead = lead_service.get_lead(lead_id, db)
    assert lead.status == "qualificado"
    assert (lead.bairro_interesse, lead.quartos) == ("Bela Vista", 2)

    # 3. Busca: os imóveis vêm do catálogo, não da imaginação do modelo
    with busca_fake(escolha_da_busca(
        (1, "2 quartos na Bela Vista, dentro do orçamento"),
        (2, "mesma região, 62 m2"),
    )):
        conversar(lead_id, "Pode me mostrar as opcoes?", llm_fake(
            ("buscar_imoveis", {
                "pedido": "apartamento de 2 quartos na Bela Vista ate 700 mil",
            }),
            "Encontrei 2 opcoes na Bela Vista.",
        ), db)

    busca = _retorno_da_busca(lead_id, db)
    assert "Apartamento Bela Vista Compacto" in busca

    # 4. Agendamento: handover operacional para o corretor
    conversar(lead_id, "Quero visitar a primeira.", llm_fake(
        ("agendar_reuniao", {
            "tipo": "visita", "data_hora": "2027-04-15 14:00", "imovel_id": 1,
            "observacoes": "Lead prefere a tarde",
        }),
        "Visita agendada!",
    ), db)

    lead = lead_service.get_lead(lead_id, db)
    agendamento = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()

    assert lead.status == "agendado"
    assert agendamento.tipo == "visita"
    assert float(lead.score) > 0

    # As falas da conversa, mais uma linha por ferramenta chamada: sem elas o
    # agente esqueceria, no turno seguinte, o que as tools lhe disseram.
    papeis = [
        m.role for m in
        db.query(Mensagem).filter(Mensagem.lead_id == lead_id)
        .order_by(Mensagem.id).all()
    ]
    assert papeis.count("user") + papeis.count("assistant") == 8
    # Qualificacao, busca e agendamento: uma linha para cada.
    assert papeis.count("tool") == 3


# --- Cenário 2: investimento -------------------------------------------------


def test_cenario_2_investimento(llm_fake, perfil_fake, busca_fake, catalogo, db):
    """Perfil investidor → busca por ticket → resumo executivo ao corretor."""
    lead_service = LeadService()
    lead_id = lead_service.get_or_create_lead(
        channel="teste", external_id="cenario2", db=db, nome="Rogerio"
    ).id

    # 1. A intenção muda o perfil do atendimento
    conversar(lead_id, "Procuro imovel para investir, nao para morar.", llm_fake(
        ("registrar_qualificacao", {
            "intencao": "investimento", "perfil": "investidor",
            "orcamento_max": 500000, "regiao_interesse": "Oeste", "quartos": 1,
        }),
        "Entendi, foco em rentabilidade.",
    ), db)
    lead = lead_service.get_lead(lead_id, db)
    assert lead.intencao == "investimento"
    assert lead.perfil == "investidor"

    # 2. Investimento busca imóveis à venda
    with busca_fake(escolha_da_busca((4, "studio compacto, alta liquidez"))):
        conversar(lead_id, "O que cabe nesse ticket?", llm_fake(
            ("buscar_imoveis", {
                "pedido": "studio para investir ate 500 mil na zona oeste",
            }),
            "Separei opcoes com bom potencial de locacao.",
        ), db)

    busca = _retorno_da_busca(lead_id, db)
    assert "Studio Pinheiros Investidor" in busca

    # 3. O perfil narrativo acumula o contexto qualitativo: o SDR relata a
    #    novidade e o agente de consolidacao devolve o perfil inteiro.
    narrativa = "Investidor buscando ticket ate 500 mil na zona oeste, foco em renda de aluguel."
    with perfil_fake(narrativa):
        conversar(lead_id, "Priorizo liquidez.", llm_fake(
            ("atualizar_perfil_lead", {"novidades": "prioriza liquidez na revenda"}),
            "Anotado no seu perfil.",
        ), db)
    assert lead_service.get_lead(lead_id, db).perfil_narrativo == narrativa

    # 4. Encerramento: resumo executivo para o corretor e saída da régua
    with perfil_fake(narrativa):
        conversar(lead_id, "Pode me passar para um corretor.", llm_fake(
            ("encerrar_atendimento", {
                "desfecho": "pediu_corretor",
                "motivo": "quer falar com um especialista antes de decidir",
            }),
            "Encaminhei seu perfil ao corretor.",
        ), db)

    lead = lead_service.get_lead(lead_id, db)
    assert lead.resumo is not None
    assert "Resumo Executivo" in lead.resumo
    assert "investimento" in lead.resumo
    assert narrativa in lead.resumo
    # Um corretor assumiu: o follow-up automático não pode chegar por cima.
    assert lead.status == "inativo"


# --- Cenário 3: follow-up automático ----------------------------------------


def test_cenario_3_followup_automatico(llm_fake, db):
    """Inatividade → job gera mensagem contextual → envia → registra tentativa."""
    lead_service = LeadService()
    lead_id = lead_service.get_or_create_lead(
        channel="telegram", external_id="777000", db=db, nome="Marcos"
    ).id

    # Conversa que para no meio
    conversar(lead_id, "Quero alugar na zona leste, ate 3 mil.", llm_fake(
        ("registrar_qualificacao", {
            "intencao": "aluguel", "regiao_interesse": "zona leste", "orcamento_max": 3000,
        }),
        "Qual bairro voce prefere?",
    ), db, canal="telegram")

    # O lead some por 8 horas (a régua de qualificação exige 6)
    db.execute(
        text("UPDATE mensagens SET timestamp = timestamp - make_interval(hours => 8) "
             "WHERE lead_id = :l"), {"l": lead_id},
    )
    db.commit()

    enviados = []

    async def sender(channel, chat_id, texto):
        enviados.append((channel, chat_id, texto))
        return True

    with followup_agent_mod.followup_agent.override(
        model=llm_fake("Oi Marcos! Ainda pensando no aluguel na zona leste?")
    ):
        stats = asyncio.run(run_followup_cycle(sender=sender))

    assert stats["elegiveis"] == 1
    assert stats["enviados"] == 1

    # A mensagem saiu pelo canal certo, com o chat_id certo
    assert len(enviados) == 1
    canal, chat_id, texto = enviados[0]
    assert (canal, chat_id) == ("telegram", "777000")
    assert "zona leste" in texto

    # E ficou registrada no histórico e na régua
    followup = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.message_type == "followup"
    ).one()
    assert followup.status == "sent"
    assert followup.sent_at is not None

    tentativa = db.query(FollowUpAttempt).filter(FollowUpAttempt.lead_id == lead_id).one()
    assert (tentativa.regua, tentativa.attempt_number, tentativa.status) == (
        "qualificacao_interrompida", 1, "sent",
    )


def test_cenario_3_contexto_preservado_no_followup(llm_fake, db):
    """O follow-up precisa retomar o que o lead já contou, não recomeçar."""
    lead_service = LeadService()
    lead_id = lead_service.get_or_create_lead(
        channel="telegram", external_id="777001", db=db, nome="Marcos"
    ).id
    lead_service.update_qualification(lead_id, {
        "intencao": "aluguel", "regiao_interesse": "zona leste",
        "orcamento_max": 3000, "quartos": 2,
    }, db)
    lead_service.save_message(
        lead_id=lead_id, channel="telegram", role="assistant",
        content="Qual bairro voce prefere?", message_type="chat", db=db,
    )
    db.execute(
        text("UPDATE mensagens SET timestamp = timestamp - make_interval(hours => 30) "
             "WHERE lead_id = :l"), {"l": lead_id},
    )
    db.commit()

    prompts = []

    def capturar(messages, info):
        from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
        prompts.append("\n".join(
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, UserPromptPart)
        ))
        return ModelResponse(parts=[TextPart(content="Oi Marcos, retomando nossa conversa!")])

    from pydantic_ai.models.function import FunctionModel
    with followup_agent_mod.followup_agent.override(model=FunctionModel(capturar)):
        asyncio.run(run_followup_cycle(sender=None))

    assert len(prompts) == 1
    prompt = prompts[0]
    # o contexto coletado precisa chegar ao modelo
    assert "Marcos" in prompt
    assert "aluguel" in prompt
    assert "zona leste" in prompt
    assert "Qual bairro voce prefere?" in prompt


def test_cenario_3_sem_canal_ativo_a_mensagem_fica_registrada(llm_fake, db):
    """Streamlit não tem push: a mensagem existe e aparece para o corretor."""
    lead_service = LeadService()
    lead_id = lead_service.get_or_create_lead(
        channel="streamlit", external_id="streamlit_demo_a1", db=db, nome="Ana"
    ).id
    lead_service.save_message(
        lead_id=lead_id, channel="streamlit", role="assistant",
        content="Qual sua urgencia?", message_type="chat", db=db,
    )
    db.execute(
        text("UPDATE mensagens SET timestamp = timestamp - make_interval(hours => 8) "
             "WHERE lead_id = :l"), {"l": lead_id},
    )
    db.commit()

    with followup_agent_mod.followup_agent.override(model=llm_fake("Oi Ana, tudo certo?")):
        stats = asyncio.run(run_followup_cycle(sender=None))

    assert stats["gerados"] == 1
    assert stats["enviados"] == 0

    tentativa = db.query(FollowUpAttempt).filter(FollowUpAttempt.lead_id == lead_id).one()
    assert tentativa.status == "generated"
    assert db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.message_type == "followup"
    ).count() == 1
