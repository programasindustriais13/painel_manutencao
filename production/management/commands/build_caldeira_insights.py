"""Processa a análise contextual da caldeira em processo separado."""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from production.caldeira_insights_jobs import read_state, write_result, write_state
from production.services_caldeira_insights import CaldeiraInsightsService


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--job", required=True)

    def handle(self, *args, **options):
        key = options["job"]
        state = read_state(key)
        if not state or state.get("status") != "queued":
            raise CommandError("Análise não encontrada ou já iniciada.")
        write_state(key, {**state, "status": "running"})
        try:
            result = CaldeiraInsightsService.analyze(
                datetime.fromisoformat(state["start"]), datetime.fromisoformat(state["end"]),
                float(state["drop_bar"]), int(state["min_minutes"]), state["floor"],
            )
            write_result(key, result)
            write_state(key, {**state, "status": "ready"})
        except Exception as exc:
            write_state(key, {**state, "status": "failed", "error": type(exc).__name__})
            raise
