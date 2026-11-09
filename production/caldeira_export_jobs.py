"""Fila simples em arquivo para exportações longas da Caldeira 2 no Windows."""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings


JOB_DIR = Path(settings.BASE_DIR) / "logs" / "caldeira_exports"


def _job_path(job_id):
    safe_id = str(uuid.UUID(str(job_id)))
    return JOB_DIR / f"{safe_id}.json"


def output_path(job_id):
    safe_id = str(uuid.UUID(str(job_id)))
    return JOB_DIR / f"{safe_id}.xlsx"


def read_job(job_id):
    path = _job_path(job_id)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_job(job_id, payload):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = _job_path(job_id)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(temporary, path)


def start_job(user, start_dt, end_dt):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(dt_timezone.utc)
    # Reutiliza uma exportação ainda em andamento para evitar cliques duplicados.
    for path in JOB_DIR.glob("*.json"):
        try:
            existing = read_job(path.stem)
        except (ValueError, OSError, json.JSONDecodeError):
            continue
        if existing:
            created = datetime.fromisoformat(existing["created_at"])
            age = now_dt - created
            if age > timedelta(days=7):
                path.unlink(missing_ok=True)
                output_path(path.stem).unlink(missing_ok=True)
                path.with_suffix(".log").unlink(missing_ok=True)
                continue
            if existing.get("status") in ("queued", "running") and age > timedelta(hours=2):
                continue
            if existing.get("status") == "ready" and not output_path(path.stem).is_file():
                continue
        if (existing and existing.get("user_id") == user.pk
                and existing.get("start") == start_dt.isoformat()
                and existing.get("end") == end_dt.isoformat()
                and existing.get("status") in ("queued", "running", "ready")):
            return path.stem
    job_id = str(uuid.uuid4())
    now = now_dt.isoformat()
    write_job(job_id, {
        "user_id": user.pk, "start": start_dt.isoformat(), "end": end_dt.isoformat(),
        "generated_by": user.get_full_name() or user.username or "Sistema",
        "created_at": now, "status": "queued",
    })
    command = [sys.executable, "manage.py", "build_caldeira_export", "--job", job_id]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with (JOB_DIR / f"{job_id}.log").open("ab") as log_file:
            subprocess.Popen(command, cwd=str(settings.BASE_DIR), stdin=subprocess.DEVNULL,
                             stdout=log_file, stderr=log_file,
                             creationflags=flags, close_fds=True)
    except OSError:
        job = read_job(job_id)
        job["status"] = "failed"
        write_job(job_id, job)
        raise
    return job_id
