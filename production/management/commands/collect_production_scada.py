import os
import sys
import time
import signal
import logging
from django.core.management.base import BaseCommand
from django.db import connections
from django.conf import settings
from production.services import ProductionStateService

logger = logging.getLogger("production.collector")


class CrossProcessLock:
    def __init__(self, lock_filename="scada_collector.lock"):
        self.lock_filepath = os.path.join(settings.BASE_DIR, lock_filename)
        self.file_handle = None

    def acquire(self) -> bool:
        try:
            self.file_handle = open(self.lock_filepath, "w")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.file_handle.write(str(os.getpid()))
            self.file_handle.flush()
            return True
        except (IOError, OSError):
            if self.file_handle:
                try:
                    self.file_handle.close()
                except Exception:
                    pass
                self.file_handle = None
            return False

    def release(self):
        if self.file_handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.file_handle.seek(0)
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file_handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.file_handle.close()
            except Exception:
                pass
            self.file_handle = None
            try:
                if os.path.exists(self.lock_filepath):
                    os.remove(self.lock_filepath)
            except Exception:
                pass


class Command(BaseCommand):
    help = "Coletor contínuo de dados do Scada-LTS e gerenciador da máquina de estados de produção."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Executa apenas um ciclo de coleta e encerra."
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=5,
            help="Intervalo em segundos entre cada ciclo de coleta (padrão: 5s)."
        )

    def handle(self, *args, **options):
        once = options.get("once", False)
        interval = max(1, options.get("interval", 5))

        lock = CrossProcessLock()
        if not lock.acquire():
            msg = "Outro coletor de produção já está em execução. Tentativa de segunda instância bloqueada."
            logger.warning(msg)
            self.stdout.write(self.style.WARNING(msg))
            return

        start_msg = f"Iniciando Coletor Scada Produção (PID {os.getpid()}, intervalo: {interval}s, once: {once})"
        logger.info(start_msg)
        self.stdout.write(self.style.SUCCESS(start_msg))

        running = True

        def signal_handler(signum, frame):
            nonlocal running
            logger.info("Sinal de interrupção recebido. Encerrando coletor...")
            self.stdout.write(self.style.WARNING("\nSinal de interrupção recebido. Encerrando coletor..."))
            running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            while running:
                start_time = time.time()
                try:
                    from production.models import ProductionMachineConfig
                    scada_vals = ProductionStateService.process_scada_cycle()
                    ProductionStateService.purge_old_rate_aggregates(days=90)
                    machines_count = ProductionMachineConfig.objects.count()
                    logger.info(f"Ciclo concluído: {machines_count} máquina(s) processada(s).")
                    self.stdout.write(".", ending="")
                    self.stdout.flush()
                except Exception as e:
                    logger.warning(f"Falha de conexão / erro transitório no ciclo do coletor Scada: {type(e).__name__}")

                connections.close_all()

                if once or not running:
                    break

                elapsed = time.time() - start_time
                sleep_time = max(0.1, interval - elapsed)

                for _ in range(int(sleep_time * 10)):
                    if not running:
                        break
                    time.sleep(0.1)

        finally:
            lock.release()
            exit_msg = "Coletor Scada encerrado com sucesso."
            logger.info(exit_msg)
            self.stdout.write(self.style.SUCCESS(f"\n{exit_msg}"))
