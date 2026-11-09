"""Cálculo de desempenho da caldeira fora da requisição HTTP."""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder


JOB_DIR = Path(settings.BASE_DIR) / "logs" / "caldeira_insights"


def job_key(start_dt, end_dt, drop_bar, min_minutes, floor, settings_updated=None):
    signature = ("v2", start_dt.isoformat(), end_dt.isoformat(), float(drop_bar), int(min_minutes),
                 floor, settings_updated.isoformat() if settings_updated else None)
    return sha256(repr(signature).encode()).hexdigest()


def _path(key, suffix):
    if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
        raise ValueError("Identificador de análise inválido.")
    return JOB_DIR / f"{key}.{suffix}.json"


def read_state(key):
    try:
        with _path(key, "state").open(encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_state(key, payload):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(key, "state")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(temporary, path)


def read_result(key):
    try:
        with _path(key, "result").open(encoding="utf-8") as handle:
            result = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    try:
        result["start"] = datetime.fromisoformat(result["start"])
        result["end"] = datetime.fromisoformat(result["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return result


def write_result(key, result):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(key, "result")
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, cls=DjangoJSONEncoder)
    os.replace(temporary, path)


def _cleanup_old_jobs():
    marker = JOB_DIR / ".cleanup"
    now = time.time()
    if marker.exists() and now - marker.stat().st_mtime < 3600:
        return
    for path in JOB_DIR.glob("*.json"):
        if now - path.stat().st_mtime > 2 * 86400:
            path.unlink(missing_ok=True)
    for path in JOB_DIR.glob("*.log"):
        if now - path.stat().st_mtime > 2 * 86400:
            path.unlink(missing_ok=True)
    marker.touch()


def ensure_job(key, start_dt, end_dt, drop_bar, min_minutes, floor, retry=False):
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_old_jobs()
    if read_result(key) is not None:
        return
    state = read_state(key)
    if state and state.get("status") == "ready":
        write_state(key, {**state, "status": "failed", "error": "result_missing"})
        state = read_state(key)
    if state and state.get("status") in ("queued", "running") and time.time() - state.get("created_at", 0) > 1800:
        write_state(key, {**state, "status": "failed", "error": "timeout"})
        state = read_state(key)
    if state and not retry:
        return
    if state and retry and state.get("status") in ("queued", "running"):
        return
    if state and retry:
        _path(key, "state").unlink(missing_ok=True)
    payload = {"status": "queued", "created_at": time.time(),
               "start": start_dt.isoformat(), "end": end_dt.isoformat(),
               "drop_bar": drop_bar, "min_minutes": min_minutes, "floor": floor}
    try:
        descriptor = os.open(_path(key, "state"), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    command = [sys.executable, "manage.py", "build_caldeira_insights", "--job", key]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        with (JOB_DIR / f"{key}.log").open("ab") as log_file:
            subprocess.Popen(command, cwd=str(settings.BASE_DIR), stdin=subprocess.DEVNULL,
                             stdout=log_file, stderr=log_file,
                             creationflags=flags, close_fds=True)
    except OSError:
        write_state(key, {**payload, "status": "failed"})
        return
