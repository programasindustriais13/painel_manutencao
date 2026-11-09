"""Executa uma exportação longa fora do processo web."""

import logging
import os
import shutil
import uuid
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from production.caldeira_export_jobs import output_path, read_job, write_job
from production.services_caldeira_fast import CaldeiraFastReader


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Gera em segundo plano uma exportação Excel da Caldeira."

    def add_arguments(self, parser):
        parser.add_argument("--job", required=True, type=uuid.UUID)

    def handle(self, *args, **options):
        job_id = str(options["job"])
        job = read_job(job_id)
        if job is None:
            raise CommandError("Exportação não encontrada.")
        if job["status"] != "queued":
            raise CommandError("Exportação já iniciada ou finalizada.")
        job["status"] = "running"
        write_job(job_id, job)
        destination = output_path(job_id)
        partial = destination.with_suffix(".xlsx.part")
        try:
            start_dt = datetime.fromisoformat(job["start"])
            end_dt = datetime.fromisoformat(job["end"])
            with CaldeiraFastReader.excel_file(start_dt, end_dt, job["generated_by"]) as source:
                with partial.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            os.replace(partial, destination)
            job["status"] = "ready"
            job["size_bytes"] = destination.stat().st_size
            write_job(job_id, job)
        except Exception:
            logger.exception("Falha na exportação da Caldeira %s", job_id)
            if partial.exists():
                partial.unlink()
            job["status"] = "failed"
            write_job(job_id, job)
            raise
