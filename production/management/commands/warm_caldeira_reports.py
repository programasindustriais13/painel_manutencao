"""Prepara os resumos diários usados nas consultas longas da Caldeira 2."""

from datetime import datetime, timedelta, time as dt_time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from production.services_caldeira_fast import CaldeiraFastReader, report_cache


class Command(BaseCommand):
    help = "Prepara resumos históricos da Caldeira 2 no cache compartilhado."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=31,
                            help="Quantidade de dias encerrados a preparar (padrão: 31).")
        parser.add_argument("--refresh", action="store_true",
                            help="Descarta resumos antigos antes de reconstruir.")

    def handle(self, *args, **options):
        days = options["days"]
        if days < 1 or days > 31:
            raise CommandError("--days deve estar entre 1 e 31.")
        if options["refresh"]:
            report_cache.clear()
        today = timezone.localtime().date()
        start = timezone.make_aware(datetime.combine(today - timedelta(days=days), dt_time.min))
        end = timezone.make_aware(datetime.combine(today, dt_time.min)) - timedelta(milliseconds=1)
        summary = CaldeiraFastReader.summary(start, end)
        self.stdout.write(self.style.SUCCESS(
            f"{days} dias preparados: {summary['total_records']} amostras, "
            f"{summary['raw_points_count']} leituras brutas."
        ))
