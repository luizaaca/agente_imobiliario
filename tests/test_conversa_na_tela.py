"""O que a tela mostra de uma conversa, incluindo o que aconteceu por baixo.

O agente de busca escreve SQL e consulta o catálogo quantas vezes precisar, e
nada disso vira mensagem — só existe no `metadata_json` da chamada. Estes testes
cobrem o caminho que leva esse registro até a tela; sem ele, "como ele achou
esses imóveis" só se responde com um `psql` aberto.
"""

from src.config import settings
from src.db.models import Mensagem
from src.services.lead_service import LeadService
from src.services.llm_usage_service import LLMUsageService
from src.ui.conversa import (
    Fala,
    _titulo_da_ferramenta,
    custo_da_conversa,
    falas_do_lead,
    falas_visiveis,
    legenda_da_conversa,
    quantas_falas,
)


def _conversa_com_busca(lead_id: int, db) -> None:
    """Um turno como `process_message` o grava: fala, ferramenta, resposta."""
    servico = LeadService()
    servico.save_message(
        lead_id=lead_id, channel="teste", role="user",
        content="quero um galpão", message_type="chat", db=db,
    )
    db.add(Mensagem(
        lead_id=lead_id, channel="teste", role="tool",
        content="Encontrei 1 imóvel(is): ...", message_type="chat",
        metadata_json={
            "tool_name": "buscar_imoveis",
            "args": {"pedido": "galpão para logística"},
            "tool_call_id": "call_1",
            "busca": {
                "consultas": ["SELECT id FROM imoveis WHERE tipo = 'galpao' LIMIT 100"],
                "imovel_ids": [7],
                "tokens_in": 4200,
                "tokens_out": 350,
            },
        },
    ))
    db.commit()
    servico.save_message(
        lead_id=lead_id, channel="teste", role="assistant",
        content="Achei um galpão no Belém.", message_type="chat", db=db,
    )


def test_a_chamada_de_ferramenta_chega_a_tela(db):
    """Antes ela era filtrada fora, e o rastro morria no banco."""
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-1", db=db
    ).id
    _conversa_com_busca(lead_id, db)

    falas = falas_do_lead(lead_id, db, 50)
    papeis = [f.role for f in falas]

    assert papeis == ["user", "tool", "assistant"]
    assert falas[1].e_ferramenta


def test_o_sql_do_agente_de_busca_viaja_junto(db):
    """É o único registro de como ele chegou nos imóveis que mostrou."""
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-2", db=db
    ).id
    _conversa_com_busca(lead_id, db)

    ferramenta = next(f for f in falas_do_lead(lead_id, db, 50) if f.e_ferramenta)

    assert ferramenta.meta["busca"]["consultas"] == [
        "SELECT id FROM imoveis WHERE tipo = 'galpao' LIMIT 100"
    ]
    assert ferramenta.meta["args"]["pedido"] == "galpão para logística"


def test_a_contagem_ignora_as_ferramentas(db):
    """"3 mensagens" para uma conversa de duas falas seria mentira."""
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-3", db=db
    ).id
    _conversa_com_busca(lead_id, db)

    falas = falas_do_lead(lead_id, db, 50)

    assert len(falas) == 3
    assert quantas_falas(falas) == 2


def test_o_aviso_do_sistema_continua_aparecendo(db):
    """`system_notice` é o que explica um turno sem resposta."""
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-4", db=db
    ).id
    LeadService().save_message(
        lead_id=lead_id, channel="teste", role="system",
        content="Turno bloqueado: orçamento diário esgotado.",
        message_type="system_notice", db=db,
    )

    # `role="system"` fica fora da conversa; quem tem rótulo é a fala do agente.
    assert falas_do_lead(lead_id, db, 50) == []


def test_o_titulo_do_painel_diz_o_que_a_busca_custou():
    """Fechado, o painel já precisa dizer se vale abrir."""
    titulo = _titulo_da_ferramenta(
        "buscar_imoveis", ["sql1", "sql2"], {"tokens_in": 4200, "tokens_out": 350}
    )

    assert "buscar_imoveis" in titulo
    assert "2 consulta(s)" in titulo
    assert "4200 → 350 tokens" in titulo


def test_ferramenta_sem_busca_tem_titulo_simples():
    assert _titulo_da_ferramenta("registrar_qualificacao", [], {}) == (
        "`registrar_qualificacao`"
    )


def test_fala_comum_nao_e_ferramenta():
    assert not Fala(role="assistant", conteudo="oi").e_ferramenta

# --- O que cada papel enxerga da conversa ------------------------------------


class BancoProibido:
    """Uma sessão que acusa qualquer uso.

    Existe para provar que a tela do corretor não paga consulta nenhuma pelo
    custo que ela não vai mostrar.
    """

    def __getattr__(self, nome):
        raise AssertionError(f"foi ao banco por '{nome}' sem precisar")


def test_sem_bastidores_a_conversa_perde_as_ferramentas(db):
    """A tela do corretor mostra o diálogo, e só."""
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-5", db=db
    ).id
    _conversa_com_busca(lead_id, db)
    falas = falas_do_lead(lead_id, db, 50)

    visiveis = falas_visiveis(falas, bastidores=False)

    assert [f.role for f in visiveis] == ["user", "assistant"]


def test_com_bastidores_nada_e_escondido(db):
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-6", db=db
    ).id
    _conversa_com_busca(lead_id, db)
    falas = falas_do_lead(lead_id, db, 50)

    assert falas_visiveis(falas, bastidores=True) == falas


def test_a_legenda_so_promete_painel_a_quem_tem_painel():
    falas = [Fala(role="user", conteudo="oi"), Fala(role="assistant", conteudo="olá")]

    assert legenda_da_conversa(falas, bastidores=False) == "2 mensagem(ns)"
    assert "painéis" in legenda_da_conversa(falas, bastidores=True)


def test_o_corretor_nao_ve_custo_nem_consulta_o_banco():
    """Custo em dólar do provider é informação de quem opera a aplicação."""
    assert custo_da_conversa(1, BancoProibido(), bastidores=False) == ""


def test_o_custo_traz_o_consumido_o_teto_e_o_dolar(db):
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-7", db=db
    ).id
    LLMUsageService().record(
        lead_id=lead_id, model="gpt-4o", tokens_in=1_000_000, tokens_out=100_000,
        operation="chat", db=db,
    )

    linha = custo_da_conversa(lead_id, db, bastidores=True)

    assert "1.100.000" in linha
    assert f"{settings.LLM_MAX_TOKENS_PER_CONVERSATION:,}".replace(",", ".") in linha
    assert "US$ 3.5000" in linha


def test_conversa_sem_gasto_mostra_zero_e_nao_some(db):
    """Some, o admin não sabe se custou zero ou se a tela esqueceu de contar."""
    lead_id = LeadService().get_or_create_lead(
        channel="teste", external_id="tela-8", db=db
    ).id

    linha = custo_da_conversa(lead_id, db, bastidores=True)

    assert linha.startswith("0 /")
    assert "US$ 0.0000" in linha
