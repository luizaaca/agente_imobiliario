#!/usr/bin/env python3
"""Supervisor: inicia Streamlit e Telegram Bot em paralelo."""

import os
import signal
import subprocess
import sys

processes = []

def cleanup(signum, frame):
    print("\nEncerrando processos...")
    for p in processes:
        p.terminate()
    for p in processes:
        p.wait()
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    
    print("🏠 Iniciando Agente SDR Imobiliário...")
    print("="*50)
    
    # Processo 1: Streamlit
    print("💻 Iniciando Streamlit (Chat + Dashboard)...")
    p1 = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.port=8501", "--server.address=0.0.0.0"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    processes.append(p1)
    
    # Processo 2: Telegram Bot
    print("🤖 Iniciando Telegram Bot...")
    p2 = subprocess.Popen(
        [sys.executable, "run_telegram.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    processes.append(p2)
    
    print("="*50)
    print("✅ Ambos os processos iniciados!")
    print("   Streamlit: http://localhost:8501")
    print("   Telegram: Ativo via Long Polling")
    print("   Ctrl+C para encerrar")
    
    # Wait for any process to exit
    try:
        for p in processes:
            p.wait()
    except KeyboardInterrupt:
        cleanup(None, None)

if __name__ == "__main__":
    main()
