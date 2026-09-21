"""O perfil narrativo acumula: o que entrou nele nao sai.

A tool `atualizar_perfil_lead` recebe so a novidade do turno e delega a fusao
ao agente de consolidacao. O que se testa aqui e a garantia que essa divisao
existe para dar: qualquer que seja o caminho — consolidacao bem-sucedida,
provider fora do ar ou resposta vazia — o texto anterior continua gravado.
"""

import asyncio

import pytest
from pydantic_ai.models.function import FunctionModel

from src.agent import perfil_agent as perfil_mod
from src.agent import sdr_agent as agent_mod
from src.agent.perfil_agent import SEM_PERFIL, build_perfil_prompt, juntar_sem_llm
from src.agent.sdr_agent import SDRDependencies, process_message
from src.db.models import LLMUsage
from src.services.catalog_service import CatalogService
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.services.scheduling_service import SchedulingService

ANTERIOR = (
    "Procura sala comercial na zona norte para consultorio medico. "
    "Pretende alugar, com teto de R$ 5.000 por mes incluindo condominio."
)
NOVIDADE = "prefere a sala de 60 m2 em Santana pela recepcao ampla"


@pytest.fixture
def lead_id(db):
    return LeadService().get_or_create_lead(
        channel="teste", external_id="perfil-001", db=db, nome="Luiz"
    ).id


@pytest.fixture
def deps(lead_id):
    return lambda: SDRDependencies(
        lead_id=lead_id,
        channel="teste",
        lead_service=LeadService(),
        catalog_service=CatalogService(),
        scheduling_service=SchedulingService(),
        llm_usage_service=LLMUsageService(),
    )


def anotar(lead_id, deps, llm_fake, novidade=NOVIDADE):
    """Roda um turno em que o SDR chama `atualizar_perfil_lead`."""
    modelo = llm_fake(
        ("atualizar_perfil_lead", {"novidades": novidade}),
        "Anotado!",
    )
    with agent_mod.sdr_agent.override(model=modelo):
        return asyncio.run(process_message(lead_id, "prefiro a segunda", "teste", deps()))


def perfil_de(lead_id, db):
    db.expire_all()
    return LeadService().get_lead(lead_id, db).perfil_narrativo


# --- O prompt da consolidacao ------------------------------------------------


def test_prompt_leva_o_perfil_atual_e_a_novidade():
    prompt = build_perfil_prompt(ANTERIOR, NOVIDADE)
    assert ANTERIOR in prompt
    assert NOVIDADE in prompt


def test_prompt_diz_quando_nao_ha_perfil_ainda():
    """Sem esta marca o modelo trataria o vazio como perfil a preservar."""
    assert SEM_PERFIL in build_perfil_prompt(None, NOVIDADE)
    assert SEM_PERFIL in build_perfil_prompt("   ", NOVIDADE)


def test_emenda_preserva_os_dois_textos():
    juntado = juntar_sem_llm(ANTERIOR, NOVIDADE)
    assert ANTERIOR in juntado
    assert NOVIDADE in juntado


def test_emenda_sem_perfil_anterior_e_so_a_novidade():
    assert juntar_sem_llm(None, NOVIDADE) == NOVIDADE


# --- O caminho completo, pela tool -------------------------------------------


def test_o_perfil_anterior_chega_ao_consolidador(llm_fake, lead_id, deps, db):
    """Sem o texto anterior no prompt, o consolidador nao teria o que preservar."""
    LeadService().update_perfil_narrativo(lead_id, ANTERIOR, db)
    visto = {}

    def capturar(messages, info):
        from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
        visto["prompt"] = "\n".join(
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        return ModelResponse(parts=[TextPart(content="perfil consolidado")])

    with perfil_mod.perfil_agent.override(model=FunctionModel(capturar)):
        anotar(lead_id, deps, llm_fake)

    assert ANTERIOR in visto["prompt"]
    assert NOVIDADE in visto["prompt"]


def test_grava_o_texto_consolidado(llm_fake, perfil_fake, lead_id, deps, db):
    LeadService().update_perfil_narrativo(lead_id, ANTERIOR, db)
    consolidado = f"{ANTERIOR} Prefere a sala de 60 m2 em Santana."

    with perfil_fake(consolidado):
        anotar(lead_id, deps, llm_fake)

    assert perfil_de(lead_id, db) == consolidado


def test_provider_fora_do_ar_nao_apaga_o_perfil(llm_fake, lead_id, deps, db):
    """O turno nao pode custar o perfil inteiro por causa de uma chamada que caiu."""
    LeadService().update_perfil_narrativo(lead_id, ANTERIOR, db)

    def explodir(messages, info):
        raise RuntimeError("provider indisponivel")

    with perfil_mod.perfil_agent.override(model=FunctionModel(explodir)):
        anotar(lead_id, deps, llm_fake)

    salvo = perfil_de(lead_id, db)
    assert ANTERIOR in salvo
    assert NOVIDADE in salvo


def test_consolidacao_vazia_nao_apaga_o_perfil(llm_fake, perfil_fake, lead_id, deps, db):
    """Texto vazio gravado direto zeraria o campo — o pior resultado possivel."""
    LeadService().update_perfil_narrativo(lead_id, ANTERIOR, db)

    with perfil_fake("   "):
        anotar(lead_id, deps, llm_fake)

    salvo = perfil_de(lead_id, db)
    assert ANTERIOR in salvo
    assert NOVIDADE in salvo


def test_tres_anotacoes_seguidas_mantem_a_primeira(llm_fake, lead_id, deps, db):
    """O acumulo e do texto inteiro, nao so do ultimo turno.

    O consolidador simulado aqui emenda o que recebe, que e o comportamento
    minimo exigido pelo prompt dele: nada do perfil atual pode sumir.
    """
    def emendar(messages, info):
        from pydantic_ai.messages import ModelResponse, TextPart, UserPromptPart
        recebido = "\n".join(
            str(p.content) for m in messages for p in m.parts
            if isinstance(p, UserPromptPart)
        )
        anterior = recebido.split("## O que a conversa acabou de revelar")[0]
        novo = recebido.split("## O que a conversa acabou de revelar")[1]
        anterior = anterior.replace("## Perfil atual", "").strip()
        novo = novo.replace("Escreva agora o perfil consolidado.", "").strip()
        if anterior == SEM_PERFIL:
            anterior = ""
        return ModelResponse(parts=[TextPart(content=f"{anterior} {novo}".strip())])

    with perfil_mod.perfil_agent.override(model=FunctionModel(emendar)):
        anotar(lead_id, deps, llm_fake, "quer consultorio medico na zona norte")
        anotar(lead_id, deps, llm_fake, "pretende alugar, teto de 5 mil")
        anotar(lead_id, deps, llm_fake, "prefere a sala de 60 m2 em Santana")

    salvo = perfil_de(lead_id, db)
    assert "consultorio medico na zona norte" in salvo
    assert "pretende alugar" in salvo
    assert "60 m2 em Santana" in salvo


# --- Custo -------------------------------------------------------------------


def test_custo_da_consolidacao_fica_no_lead(llm_fake, perfil_fake, lead_id, deps, db):
    """Sao tokens gastos por causa desta conversa: entram no orcamento dela."""
    with perfil_fake("perfil consolidado"):
        anotar(lead_id, deps, llm_fake)

    operacoes = [
        u.operation for u in
        db.query(LLMUsage).filter(LLMUsage.lead_id == lead_id).all()
    ]
    assert "perfil" in operacoes


def test_consolidacao_nao_conta_como_turno_da_conversa(
    llm_fake, perfil_fake, lead_id, deps, db
):
    """O limite de turnos mede a conversa com a pessoa, nao as chamadas internas."""
    with perfil_fake("perfil consolidado"):
        anotar(lead_id, deps, llm_fake)

    assert LLMUsageService().get_conversation_turns(lead_id, db) == 1
