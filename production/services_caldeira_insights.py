"""Leitura contextual da Caldeira 2, prensas e porta de alimentação.

Os indicadores são descritivos. Limites de triagem não são limites de segurança.
"""

from collections import defaultdict, deque
from datetime import datetime, timedelta, time as dt_time
from hashlib import sha256
from math import sqrt

from django.db.models import Q
from django.utils import timezone

from .models import ProductionGlobalParameter, ScadaDataPoint, ScadaPointValue
from .services_caldeira import CaldeiraHistoricalService
from .services_caldeira_fast import CaldeiraFastReader, _number, report_cache


PRESS_STATUS_XIDS = {
    1: "DP_313874", 2: "DP_019075", 4: "DP_937745", 5: "DP_616043",
    6: "DP_852980", 7: "DP_605358", 8: "DP_305339", 9: "DP_545001",
    10: "DP_707224", 11: "DP_773376", 12: "DP_469917",
}
DOOR_XID = "DP_342748"
PLATE_PMTA_BAR = 17.7
PLATE_STEAM_KG_H = 2500


def configured_signals():
    saved = {item.chave: item.xid for item in ProductionGlobalParameter.objects.filter(
        chave__in=[*(f"caldeira_prensa_{n:02d}" for n in PRESS_STATUS_XIDS), "caldeira_porta_lenha"]
    ) if item.xid}
    press = {number: saved.get(f"caldeira_prensa_{number:02d}", xid)
             for number, xid in PRESS_STATUS_XIDS.items()}
    return press, saved.get("caldeira_porta_lenha", DOOR_XID)


def _shift_key(ts):
    local = timezone.localtime(datetime.fromtimestamp(ts / 1000, tz=timezone.utc))
    if 6 <= local.hour < 18:
        return local.date().isoformat(), "06h–18h"
    if local.hour < 6:
        return (local.date() - timedelta(days=1)).isoformat(), "18h–06h"
    return local.date().isoformat(), "18h–06h"


def _pearson(pairs):
    if len(pairs) < 6:
        return None
    xs, ys = zip(*pairs)
    avg_x, avg_y = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - avg_x) * (y - avg_y) for x, y in pairs)
    denominator = sqrt(sum((x - avg_x) ** 2 for x in xs) * sum((y - avg_y) ** 2 for y in ys))
    return numerator / denominator if denominator else None


class CaldeiraInsightsService:
    MAX_DAYS = 31

    @classmethod
    def _resolve(cls):
        press_xids, door_xid = configured_signals()
        boiler = CaldeiraHistoricalService.resolve_caldeira_datapoints()
        ids = {}
        for key in ("pressao_caldeira", "volume_condensado"):
            dp_id = boiler.get(key, {}).get("dp_id")
            if dp_id:
                ids[dp_id] = "pressure" if key == "pressao_caldeira" else "condensate"
        tags = [*press_xids.values(), door_xid]
        points = list(ScadaDataPoint.objects.using("scada").filter(
            Q(xid__in=tags) | Q(point_name__in=tags)
        ).values("id", "xid", "point_name"))
        by_xid = {point["xid"]: point["id"] for point in points}
        by_name = {point["point_name"]: point["id"] for point in points if point["point_name"]}
        missing = []
        for number, xid in press_xids.items():
            dp_id = by_xid.get(xid) or by_name.get(xid)
            if dp_id:
                ids[dp_id] = f"press_{number:02d}"
            else:
                missing.append(f"Prensa {number:02d}")
        door_id = by_xid.get(door_xid) or by_name.get(door_xid)
        if door_id:
            ids[door_id] = "door"
        return ids, missing, bool(door_id)

    @classmethod
    def _seeds(cls, ids, start_ms):
        state = {key: None for key in ids.values()}
        for dp_id, key in ids.items():
            previous = (ScadaPointValue.objects.using("scada")
                        .filter(data_point_id=dp_id, ts__lt=start_ms)
                        .order_by("-ts", "-id")
                        .values_list("point_value", flat=True).first())
            if previous is not None:
                state[key] = bool(previous == 1) if key.startswith("press_") or key == "door" else _number(previous)
        return state

    @classmethod
    def analyze(cls, start_dt, end_dt, drop_bar=1.0, min_minutes=2, operating_floor_bar=None):
        ids, missing, door_available = cls._resolve()
        start_ms, end_ms = int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
        signature = sha256(repr((start_ms, end_ms, sorted(ids.items()), drop_bar,
                                 min_minutes, operating_floor_bar)).encode()).hexdigest()
        cache_key = f"caldeira-insights-v2:{signature}"
        cached = report_cache.get(cache_key)
        if cached is not None:
            return cached
        state = cls._seeds(ids, start_ms)
        press_keys = [key for key in ids.values() if key.startswith("press_")]
        hours = defaultdict(lambda: {"active_ms": 0, "press_covered_ms": 0, "cond_liters": 0.0, "cond_reads": 0,
                                     "cond_deltas": 0,
                                     "pressure_sum": 0.0, "pressure_count": 0, "pressure_min": None,
                                     "door_openings": 0, "door_open_ms": 0,
                                     "drop_count": 0, "below_floor_count": 0})
        shifts = defaultdict(lambda: {"door_openings": 0, "drop_count": 0,
                                      "door_near_drops": 0, "pressure_samples": 0,
                                      "door_open_ms": 0, "door_complete_count": 0,
                                      "door_duration_sum_ms": 0, "door_quick_count": 0,
                                      "door_long_count": 0, "door_long_sum_ms": 0,
                                      "drop_pressure_min": None, "drop_magnitude_max": None})
        previous_cond = state.get("condensate")
        previous_door = state.get("door")
        door_has_data = previous_door is not None
        door_open_started = None
        door_events = []
        last_ts = start_ms
        pressure_peak = deque()
        drop_started = None
        drop_context = None
        last_pressure_ts = None
        max_pressure = None
        latest_door_open = None
        drop_events = []
        cond_resets = 0
        below_floor_total = 0

        def add_interval(begin, finish):
            while begin < finish:
                hour_start = begin // 3600000 * 3600000
                segment_end = min(finish, hour_start + 3600000)
                duration = segment_end - begin
                if press_keys and all(state.get(key) is not None for key in press_keys):
                    active = sum(state[key] is True for key in press_keys)
                    hours[hour_start]["active_ms"] += active * duration
                    hours[hour_start]["press_covered_ms"] += duration
                if state.get("door") is True:
                    hours[hour_start]["door_open_ms"] += duration
                    shifts[_shift_key(begin)]["door_open_ms"] += duration
                begin = segment_end

        def finish_drop(end_ts):
            nonlocal drop_started, drop_context
            if drop_started is not None and end_ts - drop_started >= min_minutes * 60000:
                shift = _shift_key(drop_started)
                shifts[shift]["drop_count"] += 1
                if drop_context["door_near"]:
                    shifts[shift]["door_near_drops"] += 1
                minimum = drop_context["minimum"]
                magnitude = round(drop_context["peak"] - minimum, 2)
                shift_data = shifts[shift]
                shift_data["drop_pressure_min"] = (minimum if shift_data["drop_pressure_min"] is None
                                                   else min(shift_data["drop_pressure_min"], minimum))
                shift_data["drop_magnitude_max"] = (magnitude if shift_data["drop_magnitude_max"] is None
                                                    else max(shift_data["drop_magnitude_max"], magnitude))
                hours[drop_started // 3600000 * 3600000]["drop_count"] += 1
                local_started = timezone.localtime(datetime.fromtimestamp(drop_started / 1000, tz=timezone.utc))
                drop_events.append({"ts": drop_started, "time_label": local_started.strftime("%d/%m %H:%M"),
                                    "duration_min": round((end_ts - drop_started) / 60000, 1),
                                    "peak_pressure": round(drop_context["peak"], 2),
                                    "minimum_pressure": round(minimum, 2), "drop_bar": magnitude,
                                    "active_presses": drop_context["active_presses"],
                                    "door_near": drop_context["door_near"],
                                    "shift": shift[1]})
            drop_started = drop_context = None

        def finish_door(end_ts):
            nonlocal door_open_started
            if door_open_started is not None and end_ts >= door_open_started:
                duration = end_ts - door_open_started
                shift = _shift_key(door_open_started)
                shift_data = shifts[shift]
                shift_data["door_complete_count"] += 1
                shift_data["door_duration_sum_ms"] += duration
                if duration < 60000:
                    shift_data["door_quick_count"] += 1
                else:
                    shift_data["door_long_count"] += 1
                    shift_data["door_long_sum_ms"] += duration
                local_start = timezone.localtime(datetime.fromtimestamp(door_open_started / 1000, tz=timezone.utc))
                door_events.append({"ts": door_open_started, "time_label": local_start.strftime("%d/%m %H:%M:%S"),
                                    "duration_seconds": round(duration / 1000),
                                    "duration_min": round(duration / 60000, 1),
                                    "quick": duration < 60000, "shift": shift[1]})
            door_open_started = None

        for dp_id, _, raw_value, ts, _ in CaldeiraFastReader._records(ids, start_ms, end_ms):
            add_interval(last_ts, ts)
            last_ts = ts
            key = ids[dp_id]
            if key.startswith("press_"):
                state[key] = None if raw_value is None else raw_value == 1.0
            elif key == "door":
                current = None if raw_value is None else raw_value == 1.0
                door_has_data = door_has_data or current is not None
                if current is True and previous_door is False:
                    shifts[_shift_key(ts)]["door_openings"] += 1
                    hours[ts // 3600000 * 3600000]["door_openings"] += 1
                    latest_door_open = ts
                    door_open_started = ts
                elif previous_door is True and current is False:
                    finish_door(ts)
                elif current is None:
                    door_open_started = None
                previous_door = current
                state[key] = current
            elif key == "condensate":
                current = _number(raw_value)
                if current is not None and current >= 0:
                    hours[ts // 3600000 * 3600000]["cond_reads"] += 1
                    if previous_cond is not None:
                        delta = current - previous_cond
                        if delta < 0:
                            cond_resets += 1
                        else:
                            hours[ts // 3600000 * 3600000]["cond_liters"] += delta
                            hours[ts // 3600000 * 3600000]["cond_deltas"] += 1
                    previous_cond = current
            elif key == "pressure":
                pressure = _number(raw_value)
                if pressure is None:
                    continue
                hour = hours[ts // 3600000 * 3600000]
                shifts[_shift_key(ts)]["pressure_samples"] += 1
                hour["pressure_sum"] += pressure
                hour["pressure_count"] += 1
                hour["pressure_min"] = pressure if hour["pressure_min"] is None else min(hour["pressure_min"], pressure)
                if operating_floor_bar is not None and pressure < operating_floor_bar:
                    hour["below_floor_count"] += 1
                    below_floor_total += 1
                max_pressure = pressure if max_pressure is None else max(max_pressure, pressure)
                if last_pressure_ts is not None and ts - last_pressure_ts > 5 * 60000:
                    finish_drop(last_pressure_ts)
                    pressure_peak.clear()
                last_pressure_ts = ts
                while pressure_peak and pressure_peak[0][0] < ts - 30 * 60000:
                    pressure_peak.popleft()
                while pressure_peak and pressure_peak[-1][1] <= pressure:
                    pressure_peak.pop()
                pressure_peak.append((ts, pressure))
                below = pressure_peak[0][1] - pressure >= drop_bar
                if below and drop_started is None:
                    active = sum(state.get(p) is True for p in press_keys) if all(state.get(p) is not None for p in press_keys) else None
                    near_door = latest_door_open is not None and 0 <= ts - latest_door_open <= 15 * 60000
                    drop_started = ts
                    drop_context = {"active_presses": active, "door_near": near_door,
                                    "peak": pressure_peak[0][1], "minimum": pressure}
                elif below and drop_context is not None:
                    drop_context["minimum"] = min(drop_context["minimum"], pressure)
                elif not below and drop_started is not None:
                    finish_drop(ts)

        add_interval(last_ts, end_ms)
        if drop_started is not None and last_pressure_ts is not None:
            finish_drop(last_pressure_ts)
        hour_rows = []
        correlation_pairs = []
        cursor = start_ms // 3600000 * 3600000
        while cursor < end_ms:
            row = hours[cursor]
            start = max(cursor, start_ms)
            finish = min(cursor + 3600000, end_ms)
            full_hour = finish - start >= 3599000
            coverage = row["press_covered_ms"] / max(1, finish - start)
            avg_active = row["active_ms"] / row["press_covered_ms"] if row["press_covered_ms"] else None
            if full_hour and coverage >= 0.8 and avg_active is not None and row["cond_deltas"] > 0:
                correlation_pairs.append((avg_active, row["cond_liters"]))
            local = timezone.localtime(datetime.fromtimestamp(cursor / 1000, tz=timezone.utc))
            hour_rows.append({"label": local.strftime("%d/%m %Hh"), "partial": not full_hour,
                              "active_presses": round(avg_active, 1) if avg_active is not None else None,
                              "coverage": round(coverage * 100),
                              "cond_liters": round(row["cond_liters"], 1) if row["cond_deltas"] else None,
                              "pressure_avg": round(row["pressure_sum"] / row["pressure_count"], 2) if row["pressure_count"] else None,
                              "pressure_min": round(row["pressure_min"], 2) if row["pressure_min"] is not None else None,
                              "door_openings": row["door_openings"],
                              "door_open_minutes": round(row["door_open_ms"] / 60000, 1),
                              "drop_count": row["drop_count"],
                              "pressure_samples": row["pressure_count"]})
            cursor += 3600000
        correlation = _pearson(correlation_pairs)
        if len(press_keys) < 8 or len(correlation_pairs) < 6:
            relationship = "Ainda não há horas completas suficientes com os sinais das prensas e do condensado."
        elif correlation is not None and correlation >= 0.5:
            relationship = "Nesta janela, mais prensas em vulcanização coincidiram com maior volume de condensado medido. É uma associação, não uma medida de eficiência."
        elif correlation is not None and correlation <= -0.5:
            relationship = "O padrão observado é inverso ao esperado; confira o alcance e a calibração do medidor de condensado."
        else:
            relationship = "Não apareceu uma relação consistente entre prensas em vulcanização e condensado nesta janela."
        shift_rows = []
        current_date = timezone.localtime(start_dt).date() - timedelta(days=1)
        last_date = timezone.localtime(end_dt).date()
        while current_date <= last_date:
            for hour, label in ((6, "06h–18h"), (18, "18h–06h")):
                shift_start = timezone.make_aware(datetime.combine(current_date, dt_time(hour)))
                shift_end = shift_start + timedelta(hours=12)
                overlap = max(timedelta(0), min(end_dt, shift_end) - max(start_dt, shift_start))
                covered_hours = overlap.total_seconds() / 3600
                if covered_hours > 0:
                    values = shifts[(current_date.isoformat(), label)]
                    shift_rows.append({"date": current_date.isoformat(),
                                       "date_label": current_date.strftime("%d/%m/%Y"), "label": label,
                                       "covered_hours": round(covered_hours, 1),
                                       "partial": covered_hours < 11.99,
                                       "drops_per_12h": round(values["drop_count"] * 12 / covered_hours, 1)
                                       if values["pressure_samples"] else None,
                                       "door_open_minutes": round(values["door_open_ms"] / 60000, 1),
                                       "door_average_minutes": round(values["door_duration_sum_ms"] / values["door_complete_count"] / 60000, 1)
                                       if values["door_complete_count"] else None,
                                       "door_long_average_minutes": round(values["door_long_sum_ms"] / values["door_long_count"] / 60000, 1)
                                       if values["door_long_count"] else None,
                                       **values})
            current_date += timedelta(days=1)
        result = {"hours": hour_rows, "shifts": shift_rows, "drops": drop_events[::-1],
                "door_events": door_events[::-1],
                "drop_total": len(drop_events), "door_available": door_available and door_has_data,
                "door_open_minutes": round(sum(row["door_open_ms"] for row in hours.values()) / 60000, 1),
                "door_average_minutes": round(sum(event["duration_seconds"] for event in door_events) / len(door_events) / 60, 1)
                if door_events else None,
                "pressure_samples": sum(row["pressure_samples"] for row in hour_rows),
                "door_openings": sum(row["door_openings"] for row in hour_rows),
                "press_count": len(press_keys), "press_total": len(PRESS_STATUS_XIDS),
                "press_missing": missing, "cond_resets": cond_resets,
                "relationship": relationship, "correlation_hours": len(correlation_pairs),
                "max_pressure": round(max_pressure, 2) if max_pressure is not None else None,
                "above_pmta": max_pressure is not None and max_pressure > PLATE_PMTA_BAR,
                "below_floor_count": below_floor_total,
                "operating_floor_bar": operating_floor_bar,
                "start": start_dt, "end": end_dt, "drop_bar": drop_bar,
                "min_minutes": min_minutes}
        report_cache.set(cache_key, result, timeout=300)
        return result
