"""Leitura gerencial da Matrizaria, sem alterar o fluxo operacional.

As consultas carregam conjuntos por período, nunca relações dentro de um loop.
Datas são agrupadas no Python para preservar o fuso também em MySQL sem tabelas TZ.
"""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from math import ceil
from statistics import median
from urllib.parse import urlencode

from django.db.models import F, OuterRef, Q, Subquery
from django.urls import reverse
from django.utils import timezone

from .models import (
    CicloExecucaoMatrizaria, HistoricoTransicaoServicoMatrizaria,
    SolicitacaoServicoMatrizaria,
)


PENDING_STATES = ("SOLICITADO", "EM_EXECUCAO", "AGUARDANDO_CONFERENCIA", "AGUARDANDO_RETRABALHO")
STATUS_LABELS = dict(SolicitacaoServicoMatrizaria.STATUS_CHOICES)
EVENT_SELECTIONS = {
    "concluidas": ("CONFERENCIA_APROVADA",),
    "retrabalho": ("REJEICAO_RETRABALHO",),
    "conferencias": ("CONFERENCIA_APROVADA", "REJEICAO_RETRABALHO"),
    "canceladas": ("CANCELAMENTO",),
}
ROW_FIELDS = (
    "id", "destino", "prensa_id", "prensa__nome", "prensa_nome_snapshot",
    "tipo_servico__nome", "tipo_servico_nome_snapshot", "matriz_fisica_id",
    "matriz_fisica__identificador_estavel", "matriz_identificador_snapshot",
    "prioridade", "status", "data_solicitacao", "data_conferencia", "data_cancelamento",
    "responsavel_atribuido_nome", "responsavel_atribuido__username",
    "responsavel_atribuido__first_name", "responsavel_atribuido__last_name",
)


def duration_label(seconds):
    if seconds is None:
        return "—"
    minutes = max(0, int(seconds)) // 60
    if minutes >= 1440:
        return f"{minutes // 1440}d {(minutes % 1440) // 60}h"
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60:02d}m"
    return f"{minutes}m"


class MatrizariaDashboardService:
    def __init__(self, filters, now=None):
        self.filters = filters
        self.now = now or timezone.now()
        self.start_date, self.end_date = filters["data_inicio"], filters["data_fim"]
        tz = timezone.get_current_timezone()
        self.start = timezone.make_aware(datetime.combine(self.start_date, time.min), tz)
        self.end = timezone.make_aware(datetime.combine(self.end_date + timedelta(days=1), time.min), tz)
        self.base = SolicitacaoServicoMatrizaria.objects.all()
        press = filters.get("prensa")
        if press == "__MATRIZARIA__":
            self.base = self.base.filter(destino="MATRIZARIA")
        elif press == "__SEM_PRENSA__":
            self.base = self.base.filter(destino="MAQUINA", prensa__isnull=True)
        elif press:
            self.base = self.base.filter(destino="MAQUINA", prensa=press)
        if filters.get("tipo_servico"):
            self.base = self.base.filter(tipo_servico=filters["tipo_servico"])
        matrix = filters.get("matriz")
        if matrix == "__SEM_MATRIZ__":
            self.base = self.base.filter(matriz_fisica__isnull=True)
        elif matrix:
            self.base = self.base.filter(matriz_fisica_id=matrix)
        if filters.get("prioridade"):
            self.base = self.base.filter(prioridade=filters["prioridade"])

    def params(self):
        # Fixar as datas evita que a seleção mude ao navegar à meia-noite.
        result = {"periodo": "personalizado", "data_inicio": self.start_date.isoformat(),
                  "data_fim": self.end_date.isoformat()}
        for key in ("prensa", "tipo_servico", "matriz", "prioridade"):
            value = self.filters.get(key)
            if value:
                result[key] = str(getattr(value, "pk", value))
        return result

    def details_url(self, selection="fila", **overrides):
        return reverse("matrizaria:dashboard_detalhes") + "?" + urlencode(
            {**self.params(), "visao": selection, **overrides})

    def events(self, start=None, end=None):
        return HistoricoTransicaoServicoMatrizaria.objects.filter(
            solicitacao__in=self.base, data_evento__gte=start or self.start,
            data_evento__lt=end or self.end, data_evento__lte=self.now,
        ).order_by()

    def execution_cycles(self, start=None, end=None):
        start, end = start or self.start, min(end or self.end, self.now)
        if end <= start:
            return CicloExecucaoMatrizaria.objects.none()
        return CicloExecucaoMatrizaria.objects.filter(
            solicitacao__in=self.base, data_inicio__lt=end,
        ).filter(Q(data_fim__gt=start) | Q(data_fim__isnull=True, forma_encerramento="EM_ANDAMENTO"))

    def rows(self, queryset):
        # Alterações de dados e transferências não reiniciam a idade da etapa.
        transition = HistoricoTransicaoServicoMatrizaria.objects.filter(
            solicitacao_id=OuterRef("pk"), data_evento__lte=self.now,
        ).exclude(status_anterior=F("status_novo")).order_by("-data_evento", "-id")
        records = queryset.annotate(
            etapa_desde=Subquery(transition.values("data_evento")[:1]),
            etapa_status=Subquery(transition.values("status_novo")[:1]),
        ).values(*ROW_FIELDS, "etapa_desde", "etapa_status")
        result = []
        for record in records:
            pending = record["status"] in PENDING_STATES
            final_date = (record["data_cancelamento"] if record["status"] == "CANCELADO"
                          else record["data_conferencia"] if record["status"] == "CONCLUIDO" else None)
            age = max(0, ((final_date or self.now) - record["data_solicitacao"]).total_seconds())
            entered = record["etapa_desde"]
            complete = bool(entered and record["etapa_status"] == record["status"]
                            and record["data_solicitacao"] <= entered <= self.now)
            phase = max(0, (self.now - entered).total_seconds()) if complete and pending else None
            full_name = " ".join(filter(None, (record["responsavel_atribuido__first_name"],
                                              record["responsavel_atribuido__last_name"])))
            result.append({
                **record,
                "equipment": ("Matrizaria / serviço interno" if record["destino"] == "MATRIZARIA"
                              else record["prensa_nome_snapshot"] or record["prensa__nome"] or "Prensa não informada"),
                "service": record["tipo_servico_nome_snapshot"] or record["tipo_servico__nome"],
                "matrix": record["matriz_identificador_snapshot"] or record["matriz_fisica__identificador_estavel"] or "Matriz não informada",
                "responsible": record["responsavel_atribuido_nome"] or full_name or record["responsavel_atribuido__username"] or "Não atribuído",
                "status_label": STATUS_LABELS[record["status"]],
                "age_seconds": age, "age": duration_label(age),
                "phase_seconds": phase, "phase": duration_label(phase),
                "history_incomplete": pending and not complete,
            })
        order = self.filters.get("ordem") or "prioridade"
        if order == "etapa":
            result.sort(key=lambda r: (r["phase_seconds"] is None, -(r["phase_seconds"] or 0), r["id"]))
        elif order == "idade":
            result.sort(key=lambda r: (-r["age_seconds"], r["id"]))
        else:
            result.sort(key=lambda r: (r["prioridade"] != "URGENTE", -r["age_seconds"], r["id"]))
        return result

    def detail_rows(self):
        selection = self.filters.get("visao") or "fila"
        day = self.filters.get("dia")
        start, end = self.start, self.end
        if day:
            tz = timezone.get_current_timezone()
            start = timezone.make_aware(datetime.combine(day, time.min), tz)
            end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)
        if selection in ("fila", "urgentes"):
            queryset = self.base.filter(status__in=PENDING_STATES)
            if selection == "urgentes":
                queryset = queryset.filter(prioridade="URGENTE")
            if self.filters.get("estado"):
                queryset = queryset.filter(status=self.filters["estado"])
        elif selection == "abertas":
            queryset = self.base.filter(data_solicitacao__gte=start, data_solicitacao__lt=end,
                                        data_solicitacao__lte=self.now)
        elif selection == "execucao":
            queryset = self.base.filter(pk__in=self.execution_cycles(start, end).values("solicitacao_id"))
        else:
            queryset = self.base.filter(pk__in=self.events(start, end).filter(
                tipo_evento__in=EVENT_SELECTIONS[selection]).values("solicitacao_id"))
        return self.rows(queryset)

    def build(self):
        opened = list(self.base.filter(data_solicitacao__gte=self.start,
            data_solicitacao__lt=self.end, data_solicitacao__lte=self.now).values(
                "id", "data_solicitacao", "tipo_servico_id", "tipo_servico__nome"))
        events = list(self.events().filter(tipo_evento__in=(
            "CONFERENCIA_APROVADA", "REJEICAO_RETRABALHO", "CANCELAMENTO",
        )).values("solicitacao_id", "tipo_evento", "data_evento",
                  "solicitacao__data_solicitacao", "solicitacao__matriz_fisica_id",
                  "solicitacao__matriz_fisica__identificador_estavel"))
        cycles = list(self.execution_cycles().order_by().values(
            "solicitacao_id", "data_inicio", "data_fim", "solicitacao__destino",
            "solicitacao__prensa_id", "solicitacao__prensa__nome"))
        pending = self.rows(self.base.filter(status__in=PENDING_STATES))
        approved = [e for e in events if e["tipo_evento"] == "CONFERENCIA_APROVADA"]
        rejected = [e for e in events if e["tipo_evento"] == "REJEICAO_RETRABALHO"]
        # Um chamado pode ter vários eventos; as entregas contam chamados distintos.
        release_by_id = {}
        for event in approved:
            key = event["solicitacao_id"]
            if key not in release_by_id or event["data_evento"] > release_by_id[key]["data_evento"]:
                release_by_id[key] = event
        release_seconds = sorted((e["data_evento"] - e["solicitacao__data_solicitacao"]).total_seconds()
                                 for e in release_by_id.values()
                                 if e["data_evento"] >= e["solicitacao__data_solicitacao"])
        inspections = len(approved) + len(rejected)
        waiting = [r for r in pending if r["status"] == "AGUARDANDO_CONFERENCIA"]
        known_waits = [r["phase_seconds"] for r in waiting if r["phase_seconds"] is not None]
        oldest = max(pending, key=lambda r: r["age_seconds"], default=None)
        metrics = {
            "opened": len(opened), "completed": len(release_by_id),
            "median_release": duration_label(median(release_seconds)) if release_seconds else "Sem dados",
            "p90_release": duration_label(release_seconds[ceil(.9 * len(release_seconds)) - 1]) if release_seconds else "Sem dados",
            "release_samples": len(release_seconds),
            "rejected": len(rejected), "inspections": inspections,
            "rejection_rate": round(100 * len(rejected) / inspections, 1) if inspections else None,
            "pending": len(pending), "urgent": sum(r["prioridade"] == "URGENTE" for r in pending),
            "waiting": len(waiting), "oldest_wait": duration_label(max(known_waits)) if known_waits else "Sem dados",
            "waiting_incomplete": sum(r["history_incomplete"] for r in waiting),
            "oldest": oldest,
            "cancelled": len({e["solicitacao_id"] for e in events if e["tipo_evento"] == "CANCELAMENTO"}),
            "incomplete": sum(r["history_incomplete"] for r in pending),
        }
        opened_by_day = Counter(timezone.localdate(e["data_solicitacao"]) for e in opened)
        completed_by_day = defaultdict(set)
        for event in release_by_id.values():
            completed_by_day[timezone.localdate(event["data_evento"])].add(event["solicitacao_id"])
        days = []
        for offset in range((self.end_date - self.start_date).days + 1):
            day = self.start_date + timedelta(days=offset)
            days.append({"date": day.strftime("%d/%m"), "opened": opened_by_day[day],
                         "completed": len(completed_by_day[day]),
                         "opened_url": self.details_url("abertas", dia=day.isoformat()),
                         "completed_url": self.details_url("concluidas", dia=day.isoformat())})
        max_daily = max(1, *(max(d["opened"], d["completed"]) for d in days))
        for index, day in enumerate(days):
            day.update(x=f"{45 + index * 710 / max(1, len(days) - 1):.2f}",
                       opened_y=f"{190 - 150 * day['opened'] / max_daily:.2f}",
                       completed_y=f"{190 - 150 * day['completed'] / max_daily:.2f}",
                       show_label=index % max(1, ceil(len(days) / 7)) == 0 or index == len(days) - 1)
        daily = {"days": days, "maximum": max_daily,
                 "opened_points": " ".join(f"{d['x']},{d['opened_y']}" for d in days),
                 "completed_points": " ".join(f"{d['x']},{d['completed_y']}" for d in days),
                 "has_data": bool(opened or approved)}

        services = Counter(e["tipo_servico_id"] for e in opened)
        names = {e["tipo_servico_id"]: e["tipo_servico__nome"] for e in opened}
        types = [{"label": names[key], "count": count,
                  "url": self.details_url("abertas", tipo_servico=key)}
                 for key, count in sorted(services.items(), key=lambda item: (-item[1], item[0]))]
        self._bar_widths(types)
        matrices = {}
        for event in rejected:
            key = event["solicitacao__matriz_fisica_id"]
            item = matrices.setdefault(key, {
                "label": event["solicitacao__matriz_fisica__identificador_estavel"] or "Matriz não informada",
                "count": 0, "ids": set(), "url": self.details_url("retrabalho", matriz=key or "__SEM_MATRIZ__"),
            })
            item["count"] += 1
            item["ids"].add(event["solicitacao_id"])
        rework = sorted(matrices.values(), key=lambda item: (-item["count"], item["label"]))[:10]
        for item in rework:
            item["requests"] = len(item.pop("ids"))
        self._bar_widths(rework)
        stages = []
        for state in PENDING_STATES:
            rows = [r for r in pending if r["status"] == state]
            waits = [r["phase_seconds"] for r in rows if r["phase_seconds"] is not None]
            stages.append({"label": STATUS_LABELS[state], "count": len(rows),
                           "oldest": duration_label(max(waits)) if waits else "Sem dados",
                           "incomplete": sum(r["history_incomplete"] for r in rows),
                           "url": self.details_url("fila", estado=state)})
        self._bar_widths(stages)
        presses = {}
        for cycle in cycles:
            internal = cycle["solicitacao__destino"] == "MATRIZARIA"
            key = "__MATRIZARIA__" if internal else cycle["solicitacao__prensa_id"] or "__SEM_PRENSA__"
            item = presses.setdefault(key, {
                "label": "Matrizaria / serviço interno" if internal else cycle["solicitacao__prensa__nome"] or "Prensa não informada",
                "ids": set(), "seconds": 0,
                "url": self.details_url("execucao", prensa=key),
            })
            item["ids"].add(cycle["solicitacao_id"])
            stop = min(cycle["data_fim"] or self.now, self.end, self.now)
            item["seconds"] += max(0, (stop - max(cycle["data_inicio"], self.start)).total_seconds())
        pareto = sorted(presses.values(), key=lambda item: (-len(item["ids"]), item["label"]))
        width = max(800, len(pareto) * 90 + 100)
        total = sum(len(item["ids"]) for item in pareto)
        maximum = max((len(item["ids"]) for item in pareto), default=1)
        accumulated = 0
        for index, item in enumerate(pareto):
            item["count"] = len(item.pop("ids"))
            accumulated += item["count"]
            item.update(duration=duration_label(item["seconds"]), cumulative=round(100 * accumulated / total, 1),
                        x=f"{60 + (index + .5) * (width - 120) / len(pareto):.2f}",
                        rect_x=f"{44 + (index + .5) * (width - 120) / len(pareto):.2f}",
                        y=f"{190 - 150 * item['count'] / maximum:.2f}",
                        height=f"{150 * item['count'] / maximum:.2f}",
                        line_y=f"{190 - 150 * accumulated / total:.2f}")
        return {"metrics": metrics, "daily": daily, "types": types, "rework": rework,
                "stages": stages, "pending_rows": pending, "pareto": {
                    "items": pareto, "width": width, "minimum_width": max(460, len(pareto) * 70 + 90), "maximum": maximum,
                    "points": " ".join(f"{p['x']},{p['line_y']}" for p in pareto)},
                "updated_at": self.now}

    @staticmethod
    def _bar_widths(items):
        maximum = max((item["count"] for item in items), default=0) or 1
        for item in items:
            item["width"] = f"{100 * item['count'] / maximum:.2f}"
