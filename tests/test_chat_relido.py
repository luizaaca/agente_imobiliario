"""O chat mostra o que chegou à conversa por fora dele.

Um follow-up disparado na ficha, ou uma mensagem do lead pelo Telegram, entra
no banco sem passar por esta tela. A página roda de verdade aqui, pelo
`AppTest`, porque o defeito era de estado de sessão: a tela mostrava o que
tinha guardado, e não o que estava no banco.
"""

from streamlit.testing.v1 import AppTest

from src.services.lead_service import LeadService


def _pagina():
    from src.ui.chat import render_chat

    render_chat()


def _textos(app):
    return " ".join(m.value for m in app.markdown)


def test_mensagem_que_chegou_por_fora_aparece_no_proximo_desenho(db):
    servico = LeadService()
    lead = servico.get_or_create_lead(channel="streamlit", external_id="sessao-chat", db=db)
    servico.save_message(
        lead_id=lead.id, channel="streamlit", role="user",
        content="quero um 2 quartos", message_type="chat", db=db,
    )
    app = AppTest.from_function(_pagina, default_timeout=30)
    app.session_state["lead_id"] = lead.id
    app.session_state["messages"] = []
    app.run()
    assert "quero um 2 quartos" in _textos(app)

    # O follow-up entra pela ficha, com o chat já aberto neste lead.
    servico.save_message(
        lead_id=lead.id, channel="streamlit", role="assistant",
        content="Rita, achei que você ia gostar de saber", message_type="followup",
        db=db, status="generated",
    )
    app.run()

    assert "Rita, achei que você ia gostar de saber" in _textos(app)


def test_conversa_em_branco_nao_vai_ao_banco(db):
    app = AppTest.from_function(_pagina, default_timeout=30)
    app.session_state["lead_id"] = None
    app.session_state["messages"] = []

    app.run()

    assert not app.exception
