"""
Scheduler interno: corre bot.py cada hora dentro del mismo contenedor que server.py
Esto evita el problema de archivos compartidos entre servicios separados de Railway.
"""
import threading
import time
import logging
from datetime import datetime, timezone

log = logging.getLogger("scheduler")

def run_bot():
    try:
        log.info("Scheduler: iniciando ciclo del bot...")
        from bot import run
        run()
        log.info("Scheduler: ciclo completado.")
    except Exception as e:
        log.error(f"Scheduler: error en ciclo: {e}")

def start(interval_seconds=3600):
    """Corre el bot inmediatamente y luego cada interval_seconds."""
    def loop():
        log.info(f"Scheduler iniciado. Intervalo: {interval_seconds}s")
        run_bot()  # primera ejecucion inmediata
        while True:
            time.sleep(interval_seconds)
            run_bot()
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    log.info("Scheduler corriendo en background.")
