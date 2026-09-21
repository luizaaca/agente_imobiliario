"""Fuso horário da aplicação.

O container roda em UTC e o banco guarda `TIMESTAMP WITH TIME ZONE`, mas quem
conversa com o agente e quem lê a agenda estão em São Paulo. Sem um lugar só
para converter, cada tela resolvia por conta própria — e o resultado foi um
agendamento gravado como se "15h" fosse 15h UTC, que é meio-dia aqui.

A regra é curta: **UTC no banco, São Paulo na tela e na conversa.** Toda hora
que entra vem do relógio da pessoa e sobe para UTC; toda hora que sai desce
para o relógio dela de novo.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

FUSO_DO_LEAD = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")

DIAS_DA_SEMANA = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)


def agora() -> datetime:
    """O instante atual no relógio de quem está conversando."""
    return datetime.now(FUSO_DO_LEAD)


def para_exibir(quando: datetime) -> datetime:
    """A mesma hora, lida no relógio de São Paulo.

    Datas ingênuas são devolvidas intactas: elas já vieram de um formulário
    preenchido por gente daqui, e "converter" o que não tem fuso só inventaria
    um deslocamento.
    """
    if quando.tzinfo is None:
        return quando
    return quando.astimezone(FUSO_DO_LEAD)


def para_guardar(quando: datetime) -> datetime:
    """A hora que a pessoa disse, convertida para UTC antes de ir ao banco.

    Uma data ingênua aqui significa "hora de São Paulo": é o que o lead falou
    na conversa e o que o corretor digitou no formulário. Gravá-la sem fuso
    faria o Postgres assumir UTC e deslocar tudo em três horas.
    """
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=FUSO_DO_LEAD)
    return quando.astimezone(UTC)


def formatar(quando: datetime) -> str:
    """`26/09/2026 às 10:00`, já no relógio de São Paulo."""
    return f"{para_exibir(quando):%d/%m/%Y às %H:%M}"


def momento_atual() -> str:
    """Data, hora e dia da semana para as instruções do turno.

    Sem isto o modelo não tem como resolver "sábado que vem", "amanhã" ou
    "semana que vem" — e `agendar_reuniao` exige `YYYY-MM-DD`, então até o ano
    seria chute. Numa conversa real ele propôs "sábado, 26/09" sem saber que
    dia era hoje; acertou o dia da semana por sorte, uma chance em sete.

    O dia da semana vem escrito porque é assim que se marca visita — ninguém
    diz "dia 26", diz "sábado".
    """
    momento = agora()
    return (
        f"{DIAS_DA_SEMANA[momento.weekday()]}, {momento:%d/%m/%Y}, "
        f"{momento:%H:%M} (horário de Brasília)"
    )
