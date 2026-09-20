"""Pagina de ajuda: o que a aplicacao faz e por que ela se comporta assim.

Escrita para quem abre a aplicacao sem ter lido o repositorio — um avaliador,
por exemplo. Responde de dentro da tela as perguntas que hoje so o README
responde, e as que so aparecem usando: por que o chat esta desativado, por que
sumiu um menu, por que a sessao caiu.

O conteudo espelha o README e os documentos em `docs/`; quando um comportamento
mudar, os dois precisam mudar junto.
"""

import streamlit as st

from src.agent.provider import configuracao_ausente
from src.config import settings
from src.ui.papeis import e_admin, papeis_da_sessao

VERSAO = "0.1"


def _estado_da_aplicacao() -> None:
    """O que esta configurado agora, nesta instalacao.

    Vem antes do FAQ de proposito: metade das duvidas de quem abre a
    aplicacao ("por que o chat nao responde?") se resolve olhando isto.
    """
    faltando = configuracao_ausente()
    papeis = papeis_da_sessao()

    col_chat, col_papel, col_sessao = st.columns(3)

    with col_chat:
        if faltando:
            st.metric("Chat com o agente", "desativado", border=True)
            st.caption(
                "Faltam: " + ", ".join(f"`{nome}`" for nome in faltando)
            )
        else:
            st.metric("Chat com o agente", "pronto", border=True)
            st.caption(f"Modelo `{settings.LLM_MODEL}`")

    with col_papel:
        st.metric(
            "Seu papel", ", ".join(papeis) or "não definido", border=True
        )
        st.caption(
            "Vê todos os menus."
            if e_admin(papeis)
            else "O Chat Simulador e o custo de LLM são exclusivos do admin."
        )

    with col_sessao:
        if settings.AUTH_COOKIE_KEY_GERADA:
            st.metric("Sessão", "temporária", border=True)
            st.caption("`AUTH_COOKIE_KEY` ausente: o login cai a cada reinício.")
        else:
            st.metric("Sessão", "estável", border=True)
            st.caption("Chave de cookie fixada no ambiente.")


def _os_menus() -> None:
    st.markdown(
        """
Cada menu tem um assunto:

| Menu | Para quê |
|---|---|
| **Dashboard** | Leitura. Como está a carteira: volume, distribuição pelo funil, consumo de LLM. A tabela do fim é ordenável, e clicar numa linha abre a ficha daquele lead. |
| **Leads** | Operação. Tudo que se faz com um lead: ficha, canal, agendamentos, follow-up, conversa, exclusão. |
| **Chat Simulador** | Teste. Conversar com o agente fingindo ser um lead, para ver o comportamento dele sem depender do Telegram. Só o `admin` vê este menu. |
| **Ajuda** | Esta página. |

A divisão é de assunto, não de permissão: o dashboard responde *como está a
carteira* e o menu de leads responde *o que eu faço com este lead*.
"""
    )


def _como_trabalhar_um_lead() -> None:
    st.markdown(
        """
1. **Dashboard → Carteira**, ou **Leads**, para achar quem atender. A lista
   vem ordenada por score decrescente: quem ligar primeiro está no topo.
2. **Abrir ficha.** O selo de temperatura (`quente`, `morno`, `frio`) traduz o
   score; os outros selos mostram status, intenção e região sem precisar abrir.
3. **Aba Conversa** para ler o que já foi dito, e **Ficha** para o perfil
   narrativo — o texto que o agente mantém com preferências, objeções e
   rejeições. É o que vale ler antes de ligar.
4. **Aba Agendamentos** para marcar, remarcar ou excluir uma visita. Para
   registrar que uma visita não aconteceu, o caminho é o status **cancelado** —
   excluir é para o compromisso que nunca deveria ter sido criado.
5. **Disparar follow-up** quando quiser reengajar sem esperar o robô.
6. **Salvar ficha** depois de corrigir o que o agente entendeu errado. Um campo
   apagado fica vazio de verdade, e o status que você escolher não é
   recalculado por cima.
"""
    )


_PERGUNTAS = [
    (
        "Por que o chat está desativado?",
        """
Falta configuração de LLM. A aplicação sobe de propósito sem ela — dashboard e
menu de leads funcionam, incluindo a ficha e a conversa já registrada — mas o
chat precisa de um provider.

O quadro no topo desta página nomeia as variáveis que faltam. Como defini-las
depende de onde a aplicação está rodando (arquivo `.env`, ambiente do host,
*secrets* de pipeline), e o passo a passo está na seção **Configuração** do
README.
""",
    ),
    (
        "Sumiu o menu Chat Simulador. Por quê?",
        """
Ele é exclusivo do papel `admin`. É uma ferramenta de teste: conversa com o
agente fingindo ser um lead e cria leads de mentira na base, então na tela de
quem atende de verdade seria ruído.

Pelo mesmo motivo o painel **Consumo de LLM** só aparece para o `admin` — custo
em dólar é informação de quem opera a aplicação. O *alerta* de orçamento
estourado, esse, todo mundo vê: sem ele o chat pararia de responder sem
explicação.

O papel vem de `config/credentials.yaml`. **Ele esconde links do menu e não é
controle de acesso** — quem edita esse arquivo se dá o papel que quiser.
""",
    ),
    (
        "Fui deslogado sem motivo. O que houve?",
        """
Provavelmente a variável `AUTH_COOKIE_KEY` não está definida. Sem ela a
aplicação sorteia uma chave nova a cada inicialização do processo, e os cookies
emitidos antes deixam de valer — ou seja, todo reinício derruba as sessões.

Dá para usar assim; é o padrão em desenvolvimento. Para a sessão sobreviver a
reinícios, defina `AUTH_COOKIE_KEY` no ambiente. O quadro no topo desta página
diz em que situação esta instalação está.

**Trocar o papel de um usuário também exige sair e entrar de novo:** o papel
viaja no cookie, e o que já foi emitido continua carregando o papel antigo.
""",
    ),
    (
        "O que é o perfil narrativo?",
        """
Um texto que o agente mantém e reescreve ao longo da conversa, com
preferências, contexto de vida, objeções e — o mais valioso — **rejeições**:
*"descartou o de Moema por causa do condomínio de R$ 1.800"*.

É diferente dos campos estruturados (orçamento, bairro, quartos), que existem
para filtrar o catálogo. O perfil narrativo existe para o corretor ler antes de
ligar, e para o follow-up retomar a conversa de onde parou em vez de recomeçar.

Você pode editá-lo na ficha do lead.
""",
    ),
    (
        "Como funciona o follow-up?",
        """
Quatro réguas, escolhidas pelo estágio do lead no funil:

| Régua | Quando | Tentativas |
|---|---|---|
| Lead novo sem resposta | 2h de silêncio | 3 |
| Qualificação interrompida | 6h de silêncio | 3 |
| Pós-envio de imóveis | 24h de silêncio | 2 |
| Pós-agendamento | até 24h antes da visita | 2 |

Um job varre os leads a cada 30 minutos, mas ele roda **junto do processo do
Telegram**. Sem esse processo no ar, o disparo automático não acontece.

O botão **Disparar follow-up** na ficha usa a mesma lógica com outro gatilho:
dispensa só a janela de tempo — quem está olhando o lead já decidiu que é hora
— e mantém o teto de tentativas da régua e o orçamento de LLM.

Esgotadas as tentativas de uma régua de silêncio, o lead vai para `inativo`.
Ele volta ao funil sozinho se responder.
""",
    ),
    (
        "Disparei o follow-up e a mensagem não chegou no lead.",
        """
A mensagem foi **gerada e registrada** na conversa, mas não despachada. Duas
causas possíveis:

- **O lead não tem canal vinculado.** A aba **Canal** da ficha avisa quando é o
  caso. Sem identidade de canal não há para onde enviar.
- **O canal não tem envio ativo.** Só o Telegram envia, e só com o processo do
  bot no ar. Um lead que veio do simulador não tem para onde receber push — a
  mensagem fica no histórico, visível para você.
""",
    ),
    (
        "A busca não acha o que eu esperava.",
        """
Ela varre número, nome, status, intenção, bairro, região, telefone e o
**perfil narrativo**.

Os sete primeiros aparecem na tabela, então o resultado se explica olhando a
linha. O perfil narrativo não aparece — é onde moram preferências, objeções e
rejeições, e procurar por *"piscina"* ou *"mudança de trabalho"* só funciona
nele. Quando um lead aparecer sem motivo visível, abra a ficha: o casamento
está no texto do perfil.

Ficam de fora orçamento e score, que são faixas numéricas e se filtram por
intervalo, não por trecho de texto.

Um lead sem nome aparece pelo **número**, na coluna `#`, e é por ele que se
procura.
""",
    ),
    (
        "O que faz o botão **Vincular**, na aba Canal?",
        """
Ele grava **por onde o agente fala com este lead**: o canal (hoje `telegram`
ou `streamlit`) e o identificador da pessoa nesse canal — no Telegram, o
`chat_id` numérico que o bot enxerga.

Um lead que chegou conversando já vem vinculado; um cadastrado à mão, não. Sem
vínculo, o follow-up é gerado e fica registrado na conversa, mas não tem para
onde ser despachado.

Vincular de novo corrige um identificador digitado errado ou troca qual canal é
o preferencial. O identificador **não é validado** na hora de gravar: um valor
inventado só falha quando o envio acontece.
""",
    ),
    (
        "Por que um lead saiu de *agendado* sozinho?",
        """
Porque o último compromisso dele deixou de existir — foi excluído, cancelado ou
marcado como realizado.

`agendado` não é julgamento, é fato verificável: ou existe visita marcada, ou
não existe. Por isso o status e a agenda ficam sincronizados **nos dois
sentidos** — aparecendo compromisso o lead vai para `agendado`, sumindo o último
ele volta para onde os dados o colocam (`qualificado` se já tem intenção,
orçamento, região e quartos; `em_qualificacao` caso contrário).

Isso vale inclusive por cima do status que você escolher na ficha: os outros
estágios são sua decisão, `agendado` é da agenda. `inativo` fica de fora — quem
parou de responder continua parado mesmo com uma visita antiga no calendário.
""",
    ),
    (
        "Posso cadastrar um lead na mão?",
        """
Pode: **Leads → Novo lead**. Preencha a ficha e, na aba **Canal**, ligue-o a um
canal para que o follow-up o alcance.

Uma ressalva honesta: esse caminho ainda não fecha o ciclo. O identificador do
canal não é validado na hora de vincular — um `chat_id` inventado só falha na
hora do envio — e no Telegram o bot **não consegue iniciar conversa** com quem
nunca falou com ele. Funciona bem para registrar um lead que você já atende por
fora; para o agente assumir a conversa, ainda falta trabalho.
""",
    ),
    (
        "De onde vem o score?",
        """
De cinco dimensões: completude dos dados, urgência declarada, aderência ao
catálogo, engajamento na conversa e sinal de intenção de agendamento.

Ele é recalculado quando o lead avança e quando você salva a ficha. Por isso
não é editável na mão — seria um número dizendo uma coisa e os dados dizendo
outra.
""",
    ),
    (
        "Excluí um lead. O que some junto?",
        """
Mensagens, agendamentos, tentativas de follow-up e identidades de canal.

**O consumo de LLM não é apagado**: os tokens foram gastos de verdade e os
orçamentos diário e mensal precisam continuar enxergando isso. As linhas só
perdem o vínculo com o lead — senão apagar leads viraria uma forma de zerar o
controle de custo.

A exclusão é definitiva e pede confirmação.
""",
    ),
    (
        "O que esta POC não faz?",
        """
- **O canal Telegram nunca foi exercitado** com um bot real.
- **Sem streaming**: a resposta do chat aparece inteira de uma vez.
- **Sem CRM nem agenda externa**: agendamento é uma linha no banco.
- **O custo é estimado** por tabela de preços fixa; modelo fora da tabela cai
  num preço genérico e o número vira um palpite.
- **O tom do agente degrada em conversas longas** — ele tende a voltar a listar
  opções, porque imita as próprias mensagens anteriores.
- **Autenticação simples**, por arquivo com hashes bcrypt, sem provedor de
  identidade.
""",
    ),
]


def render_ajuda() -> None:
    st.header("Ajuda", divider="gray")
    st.caption(
        "Agente SDR Imobiliário · versão "
        f"{VERSAO} · POSTECH/FIAP Tech Challenge Fase 5"
    )

    st.markdown(
        "Um agente de pré-vendas que conversa com o interessado, qualifica sem "
        "formulário, busca no catálogo, agenda visita e prepara o briefing do "
        "corretor. Esta página explica como usar e por que a aplicação se "
        "comporta como se comporta."
    )

    st.subheader("Como está esta instalação")
    _estado_da_aplicacao()

    st.subheader("Os menus")
    _os_menus()

    st.subheader("Como trabalhar um lead")
    _como_trabalhar_um_lead()

    st.subheader("Perguntas frequentes")
    for pergunta, resposta in _PERGUNTAS:
        with st.expander(pergunta):
            st.markdown(resposta)

    st.subheader("Onde está o resto")
    st.markdown(
        """
- `README.md` — instalação, configuração e limitações.
- `docs/01-visao-geral/` — plano de implementação e critérios de qualidade.
- `docs/02-arquitetura/` — estratégia do agente e contratos das tools.
- `docs/03-operacao/` — infraestrutura, autenticação e governança de custos.
- `docs/06-decisoes/adr/` — decisões arquiteturais e seus porquês.
"""
    )
