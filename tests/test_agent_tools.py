"""Testes de contrato das tools e do ciclo de mensagem do agente."""

import asyncio

import pytest
from pydantic_ai.messages import (
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from src.agent import sdr_agent as agent_mod
from src.agent.history import build_message_history
from src.agent.prompts import HANDOVER_MESSAGE, UNAVAILABLE_MESSAGE
from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.models import Agendamento, LLMUsage, Mensagem
from src.services.catalog_service import CatalogService
from src.services.followup_service import REGUAS
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

from .conftest import escolha_da_busca


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="tool-001", db=db, nome="Ana"
    ).id


@pytest.fixture
def deps(lead_id):
    def criar():
        return SDRDependencies(
            lead_id=lead_id,
            channel="teste",
            lead_service=LeadService(),
            catalog_service=CatalogService(),
            scheduling_service=SchedulingService(),
            llm_usage_service=LLMUsageService(),
        )
    return criar


def conversar(texto, lead_id, deps, modelo):
    with agent_mod.sdr_agent.override(model=modelo):
        return asyncio.run(process_message(lead_id, texto, "teste", deps()))


# --- Contrato das tools ------------------------------------------------------


def test_todas_as_tools_estao_expostas(llm_fake, lead_id, deps):
    expostas = {}

    def capturar(messages, info):
        expostas["nomes"] = sorted(t.name for t in info.function_tools)
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="ok")])

    from pydantic_ai.models.function import FunctionModel
    conversar("oi", lead_id, deps, FunctionModel(capturar))

    assert expostas["nomes"] == [
        "agendar_reuniao",
        "atualizar_perfil_lead",
        "buscar_imoveis",
        "cancelar_agendamento",
        "confirmar_agendamento",
        "detalhar_imoveis",
        "encerrar_atendimento",
        "listar_agendamentos",
        "registrar_qualificacao",
    ]


def test_registrar_qualificacao_persiste_os_campos(llm_fake, lead_id, deps, db):
    modelo = llm_fake(
        ("registrar_qualificacao", {
            "intencao": "compra", "bairro_interesse": "Bela Vista",
            "orcamento_max": 700000, "quartos": 2, "urgencia": "alta",
        }),
        "Registrei tudo!",
    )
    conversar("quero 2 quartos na Bela Vista", lead_id, deps, modelo)

    lead = LeadService().get_lead(lead_id, db)
    assert (lead.intencao, lead.bairro_interesse, lead.quartos) == ("compra", "Bela Vista", 2)
    assert lead.status == "qualificado"


def test_valor_longo_e_recusado_pelo_schema_da_tool(llm_fake, lead_id, deps, db):
    """Regressão: `perfil` com texto longo derrubava o turno com DataError.

    Hoje o `max_length` da tool barra antes de chegar ao banco: o modelo
    recebe o erro de validação e pode corrigir. O turno não quebra e o valor
    invalido não é persistido.
    """
    frase_longa = "Busca de imovel para aluguel na zona leste, com interesse em 1 ou 2 quartos."
    modelo = llm_fake(
        ("registrar_qualificacao", {"intencao": "aluguel", "perfil": frase_longa}),
        "Certo!",
    )
    resposta = conversar("quero alugar", lead_id, deps, modelo)

    assert resposta == "Certo!"
    perfil = LeadService().get_lead(lead_id, db).perfil
    assert perfil != frase_longa
    assert perfil is None or len(perfil) <= 30


def test_valor_longo_que_escapa_do_schema_e_truncado(lead_id, db):
    """Segunda camada: o serviço não confia no schema e trunca mesmo assim."""
    frase_longa = "x" * 200
    LeadService().update_qualification(lead_id, {"perfil": frase_longa}, db)
    assert len(LeadService().get_lead(lead_id, db).perfil) == 30


def test_registrar_qualificacao_descarta_urgencia_invalida(llm_fake, lead_id, deps, db):
    modelo = llm_fake(
        ("registrar_qualificacao", {"intencao": "compra", "urgencia": "muito urgente"}),
        "Ok!",
    )
    conversar("tenho pressa", lead_id, deps, modelo)
    assert LeadService().get_lead(lead_id, db).urgencia is None


def _retorno_da_busca(pedido, lead_id, deps, texto_final="ok") -> str:
    """Roda um turno em que o modelo chama `buscar_imoveis` e devolve o que a tool respondeu."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    capturado = {}

    def capturar(messages, info):
        if not capturado:
            capturado["chamou"] = True
            return ModelResponse(parts=[ToolCallPart(
                tool_name="buscar_imoveis", args={"pedido": pedido}
            )])
        capturado["retorno"] = str(messages[-1].parts[0].content)
        return ModelResponse(parts=[TextPart(content=texto_final)])

    conversar("busque para mim", lead_id, deps, FunctionModel(capturar))
    return capturado["retorno"]


def test_buscar_imoveis_devolve_itens_do_catalogo(
    llm_fake, catalogo, lead_id, deps, busca_fake
):
    with busca_fake(escolha_da_busca((1, "2 quartos na Bela Vista"))):
        retorno = _retorno_da_busca("o que tem na Bela Vista?", lead_id, deps)

    assert "Apartamento Bela Vista Compacto" in retorno


def test_busca_degradada_avisa_o_que_precisou_afrouxar(
    llm_fake, catalogo, lead_id, deps, busca_fora_do_ar, db
):
    """Sem LLM, quem amplia e a escada do catalogo — e ela diz o que mudou.

    O agente so pode contar a pessoa que ampliou a busca se ela tiver sido
    ampliada de fato.
    """
    LeadService().update_qualification(lead_id, {"bairro_interesse": "Inexistente"}, db)

    with busca_fora_do_ar():
        retorno = _retorno_da_busca("qualquer apartamento", lead_id, deps)

    assert "com os filtros exatos não havia nada" in retorno
    assert "olhando a região toda, não só o bairro" in retorno
    # Depois das fichas e rotulada: lida antes, ela vira a abertura da mensagem.
    assert retorno.index("Encontrei") < retorno.index("Nota da busca")


def test_busca_degradada_sem_nada_lista_o_que_tentou(
    llm_fake, catalogo, lead_id, deps, busca_fora_do_ar, db
):
    LeadService().update_qualification(
        lead_id, {"bairro_interesse": "Inexistente", "orcamento_max": 1}, db
    )

    with busca_fora_do_ar():
        retorno = _retorno_da_busca("qualquer coisa", lead_id, deps)

    assert "Nenhum imóvel encontrado" in retorno
    assert "Já tentei, sem sucesso:" in retorno


def test_agendar_reuniao_cria_agendamento(llm_fake, catalogo, lead_id, deps, db):
    modelo = llm_fake(
        ("agendar_reuniao", {
            "tipo": "visita", "data_hora": "2027-03-10 15:00", "imovel_id": 1,
        }),
        "Agendado!",
    )
    conversar("quero visitar", lead_id, deps, modelo)

    agendamento = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()
    assert agendamento.tipo == "visita"
    assert LeadService().get_lead(lead_id, db).status == "agendado"


def test_agendar_reuniao_rejeita_data_malformada(llm_fake, lead_id, deps, db):
    modelo = llm_fake(
        ("agendar_reuniao", {"tipo": "visita", "data_hora": "amanha de tarde"}),
        "Pode me dar a data exata?",
    )
    conversar("quero visitar", lead_id, deps, modelo)
    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 0


def test_atualizar_perfil_narrativo(llm_fake, perfil_fake, lead_id, deps, db):
    """A tool manda a novidade ao consolidador e grava o texto que ele devolve."""
    consolidado = "Busca apartamento proximo ao metro. Recusou opcoes sem varanda."
    modelo = llm_fake(
        ("atualizar_perfil_lead", {"novidades": "recusou o AP-7 por nao ter varanda"}),
        "Anotado!",
    )
    with perfil_fake(consolidado):
        conversar("nao gostei, quero varanda", lead_id, deps, modelo)
    assert LeadService().get_lead(lead_id, db).perfil_narrativo == consolidado


def _encerrar(desfecho, motivo, lead_id, deps, llm_fake, perfil_fake):
    modelo = llm_fake(
        ("encerrar_atendimento", {"desfecho": desfecho, "motivo": motivo}),
        "Obrigada pelo contato!",
    )
    with perfil_fake("perfil consolidado"):
        return conversar("era so isso", lead_id, deps, modelo)


def test_encerrar_atendimento_entrega_o_resumo(
    llm_fake, perfil_fake, lead_id, deps, db
):
    _encerrar("desistiu", "achou tudo acima do orcamento", lead_id, deps,
              llm_fake, perfil_fake)

    resumo = LeadService().get_lead(lead_id, db).resumo
    assert resumo and "Resumo Executivo" in resumo


def test_encerrar_por_desistencia_tira_o_lead_da_regua(
    llm_fake, perfil_fake, lead_id, deps, db
):
    """`inativo` e o unico status fora do alvo de todas as reguas de follow-up.

    Sem isto, quem disse que nao quer mais recebe "qual bairro voce prefere?"
    seis horas depois, ate tres vezes.
    """
    _encerrar("desistiu", "vai comprar so no ano que vem", lead_id, deps,
              llm_fake, perfil_fake)

    lead = LeadService().get_lead(lead_id, db)
    assert lead.status == "inativo"
    assert lead.status not in REGUAS["qualificacao_interrompida"]["status_alvo"]
    assert lead.status not in REGUAS["pos_envio_imoveis"]["status_alvo"]


def test_encerrar_grava_o_motivo_no_perfil(llm_fake, perfil_fake, lead_id, deps, db):
    """O motivo passa pelo consolidador, como qualquer outra anotacao."""
    visto = {}

    def capturar(messages, info):
        from pydantic_ai.messages import ModelResponse, UserPromptPart
        visto["prompt"] = "\n".join(
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        return ModelResponse(parts=[TextPart(content="perfil com o motivo")])

    from pydantic_ai.models.function import FunctionModel

    from src.agent import perfil_agent as perfil_mod

    modelo = llm_fake(
        ("encerrar_atendimento", {
            "desfecho": "desistiu", "motivo": "achou a zona norte longe demais",
        }),
        "Obrigada!",
    )
    with perfil_mod.perfil_agent.override(model=FunctionModel(capturar)):
        conversar("desisti", lead_id, deps, modelo)

    assert "achou a zona norte longe demais" in visto["prompt"]
    assert LeadService().get_lead(lead_id, db).perfil_narrativo == "perfil com o motivo"


def test_encerrar_como_agendado_sem_compromisso_e_recusado(
    llm_fake, perfil_fake, lead_id, deps, db
):
    """Encerrar por agendamento sem agendamento deixaria o corretor sem visita.

    A recusa se ve pelo resumo: a tool para antes de gera-lo, entao o campo
    continua vazio. Nao da para observar o `ModelRetry` pelo texto final, que
    o modelo simulado devolve de qualquer jeito.
    """
    _encerrar("agendou", "marcou a visita", lead_id, deps, llm_fake, perfil_fake)

    db.expire_all()
    assert LeadService().get_lead(lead_id, db).resumo is None


def test_encerrar_por_desistencia_com_visita_de_pe_e_recusado(
    llm_fake, perfil_fake, catalogo, lead_id, deps, db
):
    """Marcar `inativo` apagaria o lembrete de uma visita que continua na agenda."""
    conversar("quero visitar", lead_id, deps, llm_fake(
        ("agendar_reuniao", {
            "tipo": "visita", "data_hora": "2027-03-10 15:00", "imovel_id": 1,
        }),
        "Agendado!",
    ))
    _encerrar("desistiu", "mudou de ideia", lead_id, deps, llm_fake, perfil_fake)

    db.expire_all()
    lead = LeadService().get_lead(lead_id, db)
    assert lead.status == "agendado"
    assert lead.resumo is None


def test_encerrar_nao_reativa_o_lead_no_mesmo_turno(
    llm_fake, perfil_fake, lead_id, deps, db
):
    """`process_message` reativa lead inativo; o encerramento nao pode cair nisso.

    A reativacao olha o status de ANTES do turno. Se olhasse o de agora, o
    `inativo` gravado pela tool seria desfeito no mesmo segundo.
    """
    _encerrar("pediu_corretor", "quer falar com uma pessoa", lead_id, deps,
              llm_fake, perfil_fake)

    db.expire_all()
    assert LeadService().get_lead(lead_id, db).status == "inativo"


def test_lead_inativo_que_volta_a_escrever_e_reativado(
    llm_fake, perfil_fake, lead_id, deps, db
):
    """A trava do encerramento nao pode prender quem voltou por conta propria."""
    _encerrar("desistiu", "vai pensar melhor", lead_id, deps, llm_fake, perfil_fake)
    conversar("mudei de ideia, quero ver de novo", lead_id, deps, llm_fake("Que bom!"))

    db.expire_all()
    assert LeadService().get_lead(lead_id, db).status == "em_qualificacao"


# --- Ciclo de mensagem -------------------------------------------------------


def test_mensagens_do_turno_sao_persistidas(llm_fake, lead_id, deps, db):
    conversar("oi", lead_id, deps, llm_fake("ola!"))

    papeis = [m.role for m in db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id).order_by(Mensagem.id)]
    assert papeis == ["user", "assistant"]


def test_consumo_de_llm_e_registrado(llm_fake, lead_id, deps, db):
    conversar("oi", lead_id, deps, llm_fake("ola!"))
    uso = db.query(LLMUsage).filter(LLMUsage.lead_id == lead_id).one()
    assert uso.operation == "chat"
    assert uso.conversation_turn == 1


def test_lead_novo_entra_em_qualificacao(llm_fake, lead_id, deps, db):
    conversar("oi", lead_id, deps, llm_fake("ola!"))
    assert LeadService().get_lead(lead_id, db).status == "em_qualificacao"


def test_lead_inativo_e_retomado_ao_responder(llm_fake, lead_id, deps, db):
    LeadService().update_status(lead_id, "inativo", db)
    conversar("voltei!", lead_id, deps, llm_fake("que bom!"))
    assert LeadService().get_lead(lead_id, db).status == "em_qualificacao"


def test_falha_do_provider_nao_propaga(lead_id, deps):
    def explodir(messages, info):
        raise RuntimeError("provider fora do ar")

    from pydantic_ai.models.function import FunctionModel
    resposta = conversar("oi", lead_id, deps, FunctionModel(explodir))
    assert resposta == UNAVAILABLE_MESSAGE


def test_falha_do_provider_vira_linha_no_livro_caixa(lead_id, deps, db):
    """A falha precisa existir no banco, não só no log.

    É o que sustenta a taxa de erro do dashboard: um erro que só aparece no
    log deixa a tela afirmando que nunca houve falha nenhuma.
    """
    def explodir(messages, info):
        raise RuntimeError("provider fora do ar")

    from pydantic_ai.models.function import FunctionModel
    conversar("oi", lead_id, deps, FunctionModel(explodir))

    registros = db.query(LLMUsage).filter(LLMUsage.lead_id == lead_id).all()
    assert len(registros) == 1
    assert registros[0].status == "erro"
    assert registros[0].error_type == "RuntimeError"
    assert registros[0].latency_ms is not None


def test_turno_bem_sucedido_guarda_a_latencia(llm_fake, lead_id, deps, db):
    conversar("oi", lead_id, deps, llm_fake("olá"))

    registro = db.query(LLMUsage).filter(LLMUsage.lead_id == lead_id).one()
    assert registro.status == "ok"
    assert registro.latency_ms is not None


# --- Memória conversacional --------------------------------------------------


def test_primeiro_turno_nao_tem_historico(llm_fake, lead_id, deps):
    capturado = []

    def capturar(messages, info):
        capturado.append(sum(
            1 for m in messages for p in m.parts if isinstance(p, UserPromptPart)
        ))
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="ok")])

    from pydantic_ai.models.function import FunctionModel
    conversar("primeira", lead_id, deps, FunctionModel(capturar))
    assert capturado == [1]


def test_turnos_seguintes_recebem_o_historico(llm_fake, lead_id, deps):
    capturado = []

    def capturar(messages, info):
        capturado.append([
            ("U", str(p.content)) if isinstance(p, UserPromptPart) else ("A", str(p.content))
            for m in messages for p in m.parts
            if isinstance(p, (UserPromptPart, TextPart))
        ])
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="resposta")])

    from pydantic_ai.models.function import FunctionModel
    for texto in ("primeira", "segunda", "terceira"):
        conversar(texto, lead_id, deps, FunctionModel(capturar))

    assert capturado[0] == [("U", "primeira")]
    assert capturado[1] == [("U", "primeira"), ("A", "resposta"), ("U", "segunda")]
    assert capturado[2][-1] == ("U", "terceira")
    assert len(capturado[2]) == 5


def test_mensagem_atual_nao_aparece_duplicada(llm_fake, lead_id, deps):
    capturado = []

    def capturar(messages, info):
        capturado.append([
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, UserPromptPart)
        ])
        from pydantic_ai.messages import ModelResponse
        return ModelResponse(parts=[TextPart(content="resposta")])

    from pydantic_ai.models.function import FunctionModel
    conversar("primeira", lead_id, deps, FunctionModel(capturar))
    conversar("segunda", lead_id, deps, FunctionModel(capturar))

    assert capturado[1].count("segunda") == 1


class MensagemFalsa:
    def __init__(self, role, content, metadata_json=None, id=1):
        self.role = role
        self.content = content
        self.metadata_json = metadata_json
        self.id = id


def test_conversao_de_historico_deixa_system_de_fora(db):
    """`system` guarda avisos nossos, como o de turno bloqueado por orçamento.

    Se voltasse, o modelo repetiria o aviso de indisponibilidade como se fosse
    fala sua no turno seguinte.
    """
    historico = build_message_history([
        MensagemFalsa("user", "oi"),
        MensagemFalsa("system", "instrucao interna"),
        MensagemFalsa("assistant", "ola"),
        MensagemFalsa("user", "   "),
    ])

    assert len(historico) == 2


def test_tool_volta_como_par_de_chamada_e_retorno(db):
    """Sem isso o agente esquece o que as tools disseram entre um turno e outro.

    Os IDs dos imóveis só existem no retorno da busca — ele nunca os escreve
    para a pessoa —, então reapresentava o mesmo imóvel sem perceber.
    """
    historico = build_message_history([
        MensagemFalsa("user", "busque"),
        MensagemFalsa(
            "tool", "Encontrei 1 imóvel",
            metadata_json={
                "tool_name": "buscar_imoveis",
                "args": {"tipo": "galpao"},
                "tool_call_id": "chamada-1",
            },
        ),
        MensagemFalsa("assistant", "achei um"),
    ])

    partes = [p for msg in historico for p in msg.parts]
    chamada = next(p for p in partes if isinstance(p, ToolCallPart))
    retorno = next(p for p in partes if isinstance(p, ToolReturnPart))

    assert chamada.tool_name == "buscar_imoveis"
    assert chamada.tool_call_id == retorno.tool_call_id  # o par precisa casar
    assert "Encontrei 1 imóvel" in str(retorno.content)


def test_retorno_de_tool_muito_longo_e_abreviado(db):
    """Reenviar 3.000 chars de busca a cada turno foi o que estourou um teto."""
    historico = build_message_history([
        MensagemFalsa(
            "tool", "x" * 5000,
            metadata_json={"tool_name": "buscar_imoveis", "tool_call_id": "c1"},
        ),
    ])

    retorno = next(
        p for msg in historico for p in msg.parts if isinstance(p, ToolReturnPart)
    )
    assert len(str(retorno.content)) < 1200
    assert "abreviado" in str(retorno.content)


# --- Limites de custo --------------------------------------------------------


def test_budget_diario_estourado_bloqueia_o_turno(llm_fake, lead_id, deps, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_daily_budget_exceeded", lambda self, db: True
    )
    assert conversar("oi", lead_id, deps, llm_fake("nao deveria chegar aqui")) == UNAVAILABLE_MESSAGE


def test_turno_bloqueado_deixa_o_motivo_no_historico(
    llm_fake, lead_id, deps, monkeypatch, db
):
    """Sem isto a conversa guarda a pergunta e nada depois, como se o agente
    tivesse simplesmente parado — foi assim que a trava de custo apareceu."""
    monkeypatch.setattr(
        LLMUsageService, "is_daily_budget_exceeded", lambda self, db: True
    )

    conversar("oi", lead_id, deps, llm_fake("nao deveria chegar aqui"))

    aviso = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.message_type == "system_notice"
    ).one()
    assert "orçamento diário" in aviso.content


def test_aviso_de_bloqueio_nao_entra_no_historico_do_modelo(
    llm_fake, lead_id, deps, monkeypatch, db
):
    """`role='system'` fica de fora: senão o modelo repetiria o aviso de
    indisponibilidade como se fosse fala sua."""
    monkeypatch.setattr(
        LLMUsageService, "is_daily_budget_exceeded", lambda self, db: True
    )
    conversar("oi", lead_id, deps, llm_fake("x"))

    historico = build_message_history(LeadService().get_history(lead_id, 20, db))

    textos = [str(p.content) for msg in historico for p in msg.parts]
    assert not any("orçamento diário" in t for t in textos)


def test_budget_mensal_estourado_bloqueia_o_turno(llm_fake, lead_id, deps, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_monthly_budget_exceeded", lambda self, db: True
    )
    assert conversar("oi", lead_id, deps, llm_fake("nao deveria chegar aqui")) == UNAVAILABLE_MESSAGE


def test_limite_da_conversa_faz_handover_com_resumo(llm_fake, lead_id, deps, db, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_conversation_over_limit", lambda self, lead, db: True
    )
    resposta = conversar("oi", lead_id, deps, llm_fake("nao deveria chegar aqui"))

    assert resposta == HANDOVER_MESSAGE
    assert LeadService().get_lead(lead_id, db).resumo
    assert LeadService().has_message_type(lead_id, "handover", db)


def test_handover_nao_se_repete(llm_fake, lead_id, deps, db, monkeypatch):
    monkeypatch.setattr(
        LLMUsageService, "is_conversation_over_limit", lambda self, lead, db: True
    )
    for _ in range(3):
        conversar("oi", lead_id, deps, llm_fake("x"))

    handovers = db.query(Mensagem).filter(
        Mensagem.lead_id == lead_id, Mensagem.message_type == "handover"
    ).count()
    assert handovers == 1


def test_o_handover_registra_no_perfil_que_a_trava_encerrou(
    llm_fake, lead_id, deps, db, monkeypatch
):
    """Sem isto o perfil acaba na ultima objecao e o lead parece aberto.

    Na conversa que expos a falha, a pessoa tinha acabado de escrever que nao
    ia seguir. O corretor abriu uma ficha inativa sem uma linha dizendo por
    que, nem que quem encerrou foi a trava de custo.
    """
    monkeypatch.setattr(
        LLMUsageService, "is_conversation_over_limit", lambda self, lead, db: True
    )
    conversar("nao vou seguir, obrigado", lead_id, deps, llm_fake("x"))

    perfil = LeadService().get_lead(lead_id, db).perfil_narrativo

    assert "limite de tokens da conversa" in perfil
    assert "nao vou seguir, obrigado" in perfil


def test_o_handover_nao_gasta_llm_para_anotar(
    llm_fake, lead_id, deps, db, monkeypatch
):
    """Chega-se aqui porque o orcamento acabou; consolidar custaria mais."""
    monkeypatch.setattr(
        LLMUsageService, "is_conversation_over_limit", lambda self, lead, db: True
    )

    async def nao_deveria_ser_chamado(*args, **kwargs):
        raise AssertionError("consolidou o perfil com o orcamento estourado")

    monkeypatch.setattr(agent_mod, "consolidar_perfil", nao_deveria_ser_chamado)
    conversar("nao vou seguir", lead_id, deps, llm_fake("x"))

    assert LeadService().get_lead(lead_id, db).perfil_narrativo


def test_o_perfil_anterior_sobrevive_ao_handover(
    llm_fake, lead_id, deps, db, monkeypatch
):
    """A nota acrescenta; o que o corretor precisa ler continua ali."""
    LeadService().update_perfil_narrativo(
        lead_id, "Procura tres quartos na zona sul para o consultorio.", db
    )
    monkeypatch.setattr(
        LLMUsageService, "is_conversation_over_limit", lambda self, lead, db: True
    )
    conversar("nao vou seguir", lead_id, deps, llm_fake("x"))

    perfil = LeadService().get_lead(lead_id, db).perfil_narrativo

    assert "consultorio" in perfil
    assert "limite de tokens" in perfil


def test_agendar_reuniao_vincula_o_imovel(llm_fake, lead_id, deps, catalogo, db):
    modelo = llm_fake(
        ("agendar_reuniao", {
            "tipo": "visita", "data_hora": "2027-03-10 15:00", "imovel_id": 3,
        }),
        "Agendado!",
    )
    conversar("quero visitar a cobertura", lead_id, deps, modelo)

    agendamento = db.query(Agendamento).filter(Agendamento.lead_id == lead_id).one()
    assert agendamento.imovel_id == 3
    assert agendamento.imovel.titulo == "Cobertura Moema Alto Padrao"


def test_agendar_reuniao_rejeita_imovel_inventado(llm_fake, lead_id, deps, catalogo, db):
    """Um ID que nao existe violaria a FK e derrubaria o turno inteiro."""
    modelo = llm_fake(
        ("agendar_reuniao", {
            "tipo": "visita", "data_hora": "2027-03-10 15:00", "imovel_id": 99999,
        }),
        "Qual imovel voce quer visitar?",
    )
    resposta = conversar("quero visitar", lead_id, deps, modelo)

    assert db.query(Agendamento).filter(Agendamento.lead_id == lead_id).count() == 0
    assert resposta == "Qual imovel voce quer visitar?"
    assert LeadService().get_lead(lead_id, db).status != "agendado"
