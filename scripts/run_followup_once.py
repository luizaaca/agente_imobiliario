#!/usr/bin/env python3
"""Executa um único ciclo de follow-up e imprime o resultado.

Serve para demonstrar o cenário de retomada automática sem esperar o intervalo
do scheduler. Sem o processo do Telegram no ar não há despacho ativo: as
mensagens são geradas e persistidas, e aparecem no painel do corretor.

Uso:
    python -m scripts.run_followup_once
"""

import asyncio
import logging

from src.scheduler.followup_runner import run_followup_cycle

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def main() -> None:
    stats = asyncio.run(run_followup_cycle())
    print("\nResumo do ciclo de follow-up:")
    for chave, valor in stats.items():
        print(f"- {chave}: {valor}")


if __name__ == "__main__":
    main()
