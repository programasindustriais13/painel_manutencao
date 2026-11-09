"""Leitura limitada em memória para o relatório histórico da Caldeira 2."""

import math
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, time as dt_time

import openpyxl
from django.core.cache import caches
from django.db import connections
from django.utils import timezone
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.cell import WriteOnlyCell

from .services_caldeira import CALDEIRA_VARIABLES_CONFIG, CaldeiraHistoricalService


KEYS = tuple(config["key"] for config in CALDEIRA_VARIABLES_CONFIG)
report_cache = caches["caldeira_reports"]
EXCEL_HEADERS = (
    "Data e Hora", "Pressão Caldeira (bar)", "Setpoint Alta (bar)",
    "Alta Prensas 1-7 (bar)", "Alta Prensas 8-12 (bar)",
    "Desvio 1-7 × SP (bar)", "Desvio 8-12 × SP (bar)",
    "Dif. Linhas Alta (bar)", "Baixa Prensas 1-7 (bar)",
    "Baixa Prensas 8-12 (bar)", "Dif. Linhas Baixa (bar)",
    "Dif. Caldeira × 1-7 (bar)", "Dif. Caldeira × 8-12 (bar)",
    "Totalizador Condensado (L)", "Incremento Condensado (L)",
    "Ar Comprimido (bar)", "Unidade Vácuo (bar)", "Observações",
)


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _normalize(data_type, value):
    # As nove tags da caldeira são numéricas. A conversão reproduz normalize_value.
    if data_type == 3:
        if value is None:
            return 0.0
        return int(value) if value.is_integer() else round(value, 2)
    if data_type == 2:
        return int(value) if value is not None else 0
    if data_type == 1:
        return value == 1.0
    return value


def _local_datetime(ts):
    return timezone.localtime(datetime.fromtimestamp(ts / 1000, tz=timezone.utc))


def _blank_accumulator():
    return {"count": 0, "sum": 0.0, "abs_sum": 0.0, "min": None,
            "max": None, "max_abs": 0.0, "first_val": None, "last_val": None,
            "first_ts": None, "last_ts": None}


def _add(acc, value, ts):
    number = _number(value)
    if number is None:
        return
    acc["count"] += 1
    acc["sum"] += number
    acc["abs_sum"] += abs(number)
    acc["min"] = number if acc["min"] is None else min(acc["min"], number)
    acc["max"] = number if acc["max"] is None else max(acc["max"], number)
    acc["max_abs"] = max(acc["max_abs"], abs(number))
    if acc["first_ts"] is None:
        acc["first_val"] = number
        acc["first_ts"] = ts
    acc["last_val"] = number
    acc["last_ts"] = ts


def _merge_acc(destination, source):
    if not source["count"]:
        return
    if not destination["count"]:
        destination.update(source)
        return
    destination["count"] += source["count"]
    destination["sum"] += source["sum"]
    destination["abs_sum"] += source["abs_sum"]
    destination["min"] = min(destination["min"], source["min"])
    destination["max"] = max(destination["max"], source["max"])
    destination["max_abs"] = max(destination["max_abs"], source["max_abs"])
    destination["last_val"] = source["last_val"]
    destination["last_ts"] = source["last_ts"]


def _variable_result(acc):
    count = acc["count"]
    return {
        "count": count, "avg": round(acc["sum"] / count, 2) if count else None,
        "min": round(acc["min"], 2) if count else None,
        "max": round(acc["max"], 2) if count else None,
        "amplitude": round(acc["max"] - acc["min"], 2) if count else None,
        "first_val": acc["first_val"], "last_val": acc["last_val"],
        "first_ts": acc["first_ts"], "last_ts": acc["last_ts"],
        "has_data": bool(count),
    }


def _difference_result(acc):
    count = acc["count"]
    return {
        "count": count,
        "avg_signed": round(acc["sum"] / count, 2) if count else None,
        "avg_abs": round(acc["abs_sum"] / count, 2) if count else None,
        "max_abs": round(acc["max_abs"], 2) if count else None,
        "min": round(acc["min"], 2) if count else None,
        "max": round(acc["max"], 2) if count else None,
    }


def _derived(values, rounded=True):
    p1 = _number(values.get("pressao_alta_prensas_1_7"))
    p2 = _number(values.get("pressao_alta_prensas_8_12"))
    sp = _number(values.get("setpoint_pressao_alta"))
    pcal = _number(values.get("pressao_caldeira"))
    b1 = _number(values.get("pressao_baixa_prensas_1_7"))
    b2 = _number(values.get("pressao_baixa_prensas_8_12"))
    def diff(a, b):
        if a is None or b is None:
            return None
        result = a - b
        return round(result, 2) if rounded else result
    return {
        "desvio_1_7": diff(p1, sp), "desvio_8_12": diff(p2, sp),
        "diferenca_alta": diff(p1, p2), "diferenca_baixa": diff(b1, b2),
        "diferenca_caldeira_1": diff(pcal, p1),
        "diferenca_caldeira_2": diff(pcal, p2),
    }


def _row(ts, values):
    row_dt = _local_datetime(ts)
    return {"ts": ts, "datetime": row_dt,
            "datetime_str": row_dt.strftime("%d/%m/%Y %H:%M:%S"),
            "values": values.copy(), **_derived(values)}


class CaldeiraFastReader:
    PAGE_SIZE = 50
    MAX_CHART_POINTS = 1500
    EXCEL_MAX_DATA_ROWS = 1_048_575

    @classmethod
    def _resolved(cls):
        resolved = CaldeiraHistoricalService.resolve_caldeira_datapoints()
        id_to_key = {item["dp_id"]: key for key, item in resolved.items() if item["dp_id"]}
        missing = [item["config"]["label"] for item in resolved.values() if not item["dp_id"]]
        return id_to_key, missing

    @classmethod
    def _seed(cls, id_to_key, start_ms):
        state = {key: None for key in KEYS}
        for dp_id, key in id_to_key.items():
            previous = (connections["scada"].cursor())
            try:
                previous.execute(
                    "SELECT dataType, pointValue FROM pointvalues "
                    "WHERE dataPointId = %s AND ts < %s ORDER BY ts DESC, id DESC LIMIT 1",
                    [dp_id, start_ms],
                )
                record = previous.fetchone()
                if record:
                    state[key] = _normalize(*record)
            finally:
                previous.close()
        return state

    @classmethod
    def _records(cls, id_to_key, start_ms, end_ms):
        if not id_to_key:
            return
        connection = connections["scada"]
        connection.ensure_connection()
        if connection.vendor == "mysql":
            # MySQLdb usa cursor armazenado por padrão; SSCursor lê em lotes reais.
            from MySQLdb.cursors import SSCursor
            cursor = connection.connection.cursor(SSCursor)
        else:
            cursor = connection.cursor()
        placeholders = ", ".join(["%s"] * len(id_to_key))
        sql = (
            "SELECT dataPointId, dataType, pointValue, ts, id FROM pointvalues "
            f"WHERE dataPointId IN ({placeholders}) AND ts >= %s AND ts <= %s "
            "ORDER BY ts, dataPointId, id"
        )
        try:
            cursor.execute(sql, [*id_to_key, start_ms, end_ms])
            while True:
                batch = cursor.fetchmany(5000)
                if not batch:
                    break
                yield from batch
        finally:
            cursor.close()

    @classmethod
    def iter_rows(cls, start_dt, end_dt, id_to_key=None, emit_seed_if_empty=True):
        id_to_key = id_to_key if id_to_key is not None else cls._resolved()[0]
        start_ms, end_ms = int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
        state = cls._seed(id_to_key, start_ms)
        previous_condensate = _number(state["volume_condensado"])
        current_ts = None
        raw_count = 0
        condensate_delta = None
        for dp_id, data_type, value, ts, _ in cls._records(id_to_key, start_ms, end_ms):
            if current_ts is not None and ts != current_ts:
                completed = _row(current_ts, state)
                completed["cond_delta"] = condensate_delta
                yield completed, raw_count
                raw_count = 0
                condensate_delta = None
            current_ts = ts
            key = id_to_key[dp_id]
            normalized = _normalize(data_type, value)
            state[key] = normalized
            if key == "volume_condensado":
                numeric = _number(normalized)
                if numeric is not None and numeric >= 0:
                    if previous_condensate is not None:
                        condensate_delta = (condensate_delta or 0.0) + max(0, numeric - previous_condensate)
                    previous_condensate = numeric
            raw_count += 1
        if current_ts is not None:
            completed = _row(current_ts, state)
            completed["cond_delta"] = condensate_delta
            yield completed, raw_count
        elif emit_seed_if_empty and any(value is not None for value in state.values()):
            yield _row(start_ms, state), 0

    @classmethod
    def _segments(cls, start_dt, end_dt):
        current = start_dt
        while current <= end_dt:
            next_date = current.date() + timedelta(days=1)
            next_midnight = timezone.make_aware(datetime.combine(next_date, dt_time.min))
            segment_end = min(end_dt, next_midnight - timedelta(milliseconds=1))
            full_day = current.time() == dt_time.min and segment_end == next_midnight - timedelta(milliseconds=1)
            yield current, segment_end, full_day
            current = next_midnight

    @classmethod
    def _segment_summary(cls, start_dt, end_dt, id_to_key):
        start_ms, end_ms = int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
        variables = {key: _blank_accumulator() for key in KEYS}
        differences = {key: _blank_accumulator() for key in (
            "desvio_1_7", "desvio_8_12", "diferenca_alta", "diferenca_baixa",
            "diferenca_caldeira_1", "diferenca_caldeira_2")}
        count = raw_count = 0
        chart_rows = {}
        cond_first = cond_last = cond_prev = cond_first_ts = cond_last_ts = None
        cond_count = cond_resets = 0
        cond_total = 0.0
        cond_hourly = defaultdict(float)
        vacuum_buckets = {}
        for row, raw_in_timestamp in cls.iter_rows(start_dt, end_dt, id_to_key, emit_seed_if_empty=False):
            count += 1
            raw_count += raw_in_timestamp
            ts = row["ts"]
            for key, acc in variables.items():
                _add(acc, row["values"].get(key), ts)
            exact_differences = _derived(row["values"], rounded=False)
            for key, acc in differences.items():
                _add(acc, exact_differences.get(key), ts)
            bucket = min(49, (ts - start_ms) * 50 // max(1, end_ms - start_ms + 1))
            chart_rows.setdefault(bucket, row)
            vacuum = _number(row["values"].get("pressao_vacuo"))
            if vacuum is not None:
                vacuum_bucket = ts // 300000 * 300000
                current = vacuum_buckets.setdefault(vacuum_bucket, [0.0, 0, vacuum])
                current[0] += vacuum
                current[1] += 1
                current[2] = max(current[2], vacuum)
        # O totalizador usa as leituras reais, inclusive leituras repetidas no mesmo ts.
        cond_id = next((dp for dp, key in id_to_key.items() if key == "volume_condensado"), None)
        if cond_id is not None:
            seed_value = _number(cls._seed({cond_id: "volume_condensado"}, start_ms)["volume_condensado"])
            cond_prev = seed_value if seed_value is not None and seed_value >= 0 else None
            for _, data_type, value, ts, _ in cls._records({cond_id: "volume_condensado"}, start_ms, end_ms):
                numeric = _number(_normalize(data_type, value))
                if numeric is None or numeric < 0:
                    continue
                cond_count += 1
                if cond_first is None:
                    cond_first, cond_first_ts = numeric, ts
                cond_last, cond_last_ts = numeric, ts
                if cond_prev is not None:
                    delta = numeric - cond_prev
                    if delta < 0:
                        cond_resets += 1
                    else:
                        cond_total += delta
                        cond_hourly[_local_datetime(ts).strftime("%d/%m %H:00")] += delta
                cond_prev = numeric
        return {
            "variables": variables, "differences": differences,
            "count": count, "raw_count": raw_count,
            "chart_rows": [chart_rows[key] for key in sorted(chart_rows)],
            "vacuum_buckets": vacuum_buckets,
            "cond_first": cond_first, "cond_last": cond_last,
            "cond_first_ts": cond_first_ts, "cond_last_ts": cond_last_ts,
            "cond_count": cond_count, "cond_resets": cond_resets,
            "cond_total": cond_total, "cond_hourly": dict(cond_hourly),
        }

    @classmethod
    def summary(cls, start_dt, end_dt):
        id_to_key, missing = cls._resolved()
        start_ms, end_ms = int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
        ids_key = ",".join(map(str, sorted(id_to_key)))
        cache_key = f"caldeira-summary-v6:{start_ms}:{end_ms}:{ids_key}"
        saved = report_cache.get(cache_key)
        if saved is not None:
            return saved
        variables = {key: _blank_accumulator() for key in KEYS}
        differences = {key: _blank_accumulator() for key in (
            "desvio_1_7", "desvio_8_12", "diferenca_alta", "diferenca_baixa",
            "diferenca_caldeira_1", "diferenca_caldeira_2")}
        count = raw_count = cond_count = cond_resets = 0
        cond_total = 0.0
        cond_first = cond_last = cond_first_ts = cond_last_ts = None
        cond_hourly = defaultdict(float)
        chart_rows = []
        vacuum_buckets = {}
        for segment_start, segment_end, full_day in cls._segments(start_dt, end_dt):
            segment_key = (f"caldeira-day-v6:{int(segment_start.timestamp() * 1000)}:"
                           f"{int(segment_end.timestamp() * 1000)}:{ids_key}")
            part = report_cache.get(segment_key) if full_day else None
            if part is None:
                part = cls._segment_summary(segment_start, segment_end, id_to_key)
                if full_day:
                    report_cache.set(segment_key, part, timeout=30 * 86400)
            count += part["count"]
            raw_count += part["raw_count"]
            chart_rows.extend(part["chart_rows"])
            for bucket, (value_sum, value_count, maximum) in part["vacuum_buckets"].items():
                current = vacuum_buckets.setdefault(bucket, [0.0, 0, maximum])
                current[0] += value_sum
                current[1] += value_count
                current[2] = max(current[2], maximum)
            for key in variables:
                _merge_acc(variables[key], part["variables"][key])
            for key in differences:
                _merge_acc(differences[key], part["differences"][key])
            cond_count += part["cond_count"]
            cond_resets += part["cond_resets"]
            cond_total += part["cond_total"]
            if part["cond_count"]:
                if cond_first_ts is None:
                    cond_first, cond_first_ts = part["cond_first"], part["cond_first_ts"]
                cond_last, cond_last_ts = part["cond_last"], part["cond_last_ts"]
            for hour, volume in part["cond_hourly"].items():
                cond_hourly[hour] += volume
        if count == 0 and id_to_key:
            state = cls._seed(id_to_key, start_ms)
            if any(value is not None for value in state.values()):
                row = _row(start_ms, state)
                count = 1
                chart_rows = [row]
                for key in variables:
                    _add(variables[key], row["values"].get(key), start_ms)
                for key, value in _derived(state, rounded=False).items():
                    _add(differences[key], value, start_ms)
        seed_value = None
        cond_id = next((dp for dp, key in id_to_key.items() if key == "volume_condensado"), None)
        if cond_id is not None and cond_count == 1:
            seed_value = _number(cls._seed({cond_id: "volume_condensado"}, start_ms)["volume_condensado"])
        hours_covered = max(0, (cond_last_ts - cond_first_ts) / 3600000) if cond_count else 0
        avg_lh = cond_total / hours_covered if hours_covered > 0 else None
        cond_stats = {
            "has_data": bool(cond_count), "total_liters": round(cond_total, 2),
            "formatted_liters": (f"{cond_total:,.1f} L".replace(",", "X").replace(".", ",").replace("X", ".")) if cond_count > 1 or (cond_count and seed_value is not None) else ("Dados insuficientes" if cond_count else "Sem dados"),
            "avg_liters_per_hour": round(avg_lh, 2) if avg_lh is not None else None,
            "formatted_avg_lh": (f"{avg_lh:,.1f} L/h".replace(",", "X").replace(".", ",").replace("X", ".")) if avg_lh is not None else "Dados insuficientes",
            "first_cumulative": cond_first, "last_cumulative": cond_last,
            "resets_count": cond_resets, "samples_count": cond_count,
            "hours_covered": round(hours_covered, 2),
            "status_message": (
                "Sem dados de condensado no período." if not cond_count else
                "Apenas 1 leitura disponível. Dados insuficientes para calcular consumo por diferença."
                if cond_count == 1 and seed_value is None else
                f"Volume total calculado por diferenças consecutivas ({cond_resets} reset(s) detectado(s))."
                if cond_resets else "Cálculo contínuo sem resets."
            ),
            "hourly_series": [{"hour": hour, "volume": round(volume, 1)} for hour, volume in sorted(cond_hourly.items())],
        }
        var_stats = {key: _variable_result(acc) for key, acc in variables.items()}
        derived_stats = {key: _difference_result(acc) for key, acc in differences.items()}
        stats = {
            "variables": var_stats,
            "deviations": {"linha_1_7": derived_stats["desvio_1_7"], "linha_8_12": derived_stats["desvio_8_12"]},
            "comparisons": {"alta": derived_stats["diferenca_alta"], "baixa": derived_stats["diferenca_baixa"],
                            "caldeira_linha_1": derived_stats["diferenca_caldeira_1"],
                            "caldeira_linha_2": derived_stats["diferenca_caldeira_2"]},
        }
        def stat(key):
            return var_stats[key]
        stats["cards"] = {
            "pressao_caldeira": stat("pressao_caldeira"),
            "pressao_alta_1_7": {**stat("pressao_alta_prensas_1_7"), "desvio_abs_medio": derived_stats["desvio_1_7"]["avg_abs"]},
            "pressao_alta_8_12": {**stat("pressao_alta_prensas_8_12"), "desvio_abs_medio": derived_stats["desvio_8_12"]["avg_abs"]},
            "setpoint_pressao_alta": stat("setpoint_pressao_alta"),
            "condensado": {**cond_stats}, "ar_comprimido": stat("pressao_ar_comprimido"),
            "vacuo": stat("pressao_vacuo"),
        }
        charts = CaldeiraHistoricalService._build_chart_datasets(chart_rows, cond_stats)
        display_bucket_ms = max(300000, math.ceil((end_ms - start_ms) / (240 * 300000)) * 300000)
        vacuum_display = {}
        for bucket, (value_sum, value_count, maximum) in vacuum_buckets.items():
            display_bucket = bucket // display_bucket_ms * display_bucket_ms
            current = vacuum_display.setdefault(display_bucket, [0.0, 0, maximum])
            current[0] += value_sum
            current[1] += value_count
            current[2] = max(current[2], maximum)
        vacuum_times = sorted(vacuum_display)
        charts["chart_6_vacuo"] = {
            "timestamps": vacuum_times,
            "labels": [_local_datetime(ts).strftime("%d/%m %H:%M") for ts in vacuum_times],
            "vacuum_avg": [round(vacuum_display[ts][0] / vacuum_display[ts][1], 3) for ts in vacuum_times],
            "vacuum_max": [round(vacuum_display[ts][2], 3) for ts in vacuum_times],
        }
        result = {"total_records": count, "raw_points_count": raw_count,
                  "variables_found_count": len(id_to_key), "variables_missing": missing,
                  "stats": stats, "card_stats": stats["cards"], "condensate_stats": cond_stats,
                  "chart_datasets": charts, "has_data": bool(count)}
        report_cache.set(cache_key, result, timeout=300)
        return result

    @classmethod
    def page(cls, start_dt, end_dt, page_number, total_records):
        id_to_key, _ = cls._resolved()
        if not id_to_key or not total_records:
            return []
        start_ms, end_ms = int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
        offset = (page_number - 1) * cls.PAGE_SIZE
        from .models import ScadaPointValue
        timestamps = list(ScadaPointValue.objects.using("scada")
                          .filter(data_point_id__in=id_to_key, ts__gte=start_ms, ts__lte=end_ms)
                          .order_by("ts").values_list("ts", flat=True).distinct()[offset:offset + cls.PAGE_SIZE])
        if not timestamps:
            return []
        state = cls._seed(id_to_key, timestamps[0])
        records = (ScadaPointValue.objects.using("scada")
                   .filter(data_point_id__in=id_to_key, ts__in=timestamps)
                   .order_by("ts", "data_point_id", "id")
                   .values_list("data_point_id", "data_type", "point_value", "ts", "id")
                   .iterator(chunk_size=1000))
        rows = []
        current_ts = None
        for dp_id, data_type, value, ts, _ in records:
            if current_ts is not None and ts != current_ts:
                rows.append(_row(current_ts, state))
            current_ts = ts
            state[id_to_key[dp_id]] = _normalize(data_type, value)
        if current_ts is not None:
            rows.append(_row(current_ts, state))
        return rows

    @classmethod
    def excel_file(cls, start_dt, end_dt, generated_by="Sistema"):
        summary = cls.summary(start_dt, end_dt)
        wb = openpyxl.Workbook(write_only=True)
        ws1 = wb.create_sheet("Resumo Gerencial")
        ws2 = wb.create_sheet("Gráficos")
        ws3 = wb.create_sheet("Dados Históricos")
        ws1.page_setup.orientation = "landscape"
        ws1.page_setup.paperSize = "9"
        ws1.page_setup.fitToWidth = 1
        ws3.page_setup.orientation = "landscape"
        ws3.page_setup.paperSize = "9"
        ws3.freeze_panes = "A2"
        title_font = Font(name="Segoe UI", size=15, bold=True, color="0F172A")
        header_font = Font(name="Segoe UI", bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="0F172A")
        title_cell = WriteOnlyCell(ws1, "RELATÓRIO DA CALDEIRA 2")
        title_cell.font = title_font
        ws1.append([title_cell])
        ws1.append(["Período", f"{start_dt:%d/%m/%Y %H:%M} até {end_dt:%d/%m/%Y %H:%M}"])
        ws1.append(["Gerado por", generated_by])
        ws1.append(["Amostras sincronizadas", summary["total_records"]])
        ws1.append(["Leituras brutas", summary["raw_points_count"]])
        ws1.append(["Variável", "Média", "Mínimo", "Máximo", "Amplitude"])
        for config in CALDEIRA_VARIABLES_CONFIG:
            stat = summary["stats"]["variables"][config["key"]]
            ws1.append([config["friendly_name"], stat["avg"], stat["min"], stat["max"], stat["amplitude"]])
        ws1.append(["Volume de condensado", summary["condensate_stats"]["formatted_liters"]])
        ws1.append(["Média de condensado", summary["condensate_stats"]["formatted_avg_lh"]])
        ws1.append(["Resets do totalizador", summary["condensate_stats"]["resets_count"]])
        ws1.append(["Desvio médio absoluto linha 1-7", summary["stats"]["deviations"]["linha_1_7"]["avg_abs"]])
        ws1.append(["Desvio médio absoluto linha 8-12", summary["stats"]["deviations"]["linha_8_12"]["avg_abs"]])
        ws1.append(["Diferença média entre linhas de alta", summary["stats"]["comparisons"]["alta"]["avg_signed"]])
        ws1.append(["Diferença média entre linhas de baixa", summary["stats"]["comparisons"]["baixa"]["avg_signed"]])
        ws1.append(["Diferença média Caldeira × linha 1-7", summary["stats"]["comparisons"]["caldeira_linha_1"]["avg_signed"]])
        ws1.append(["Diferença média Caldeira × linha 8-12", summary["stats"]["comparisons"]["caldeira_linha_2"]["avg_signed"]])
        ws1.append(["Nota", "O volume de condensado soma diferenças positivas consecutivas; resets não subtraem consumo."])
        ws2.append(["GRÁFICOS OPERACIONAIS DA CALDEIRA 2"])
        ws2.append([f"Período: {start_dt:%d/%m/%Y %H:%M} até {end_dt:%d/%m/%Y %H:%M}"])
        ws2.page_setup.orientation = "landscape"
        ws2.page_setup.paperSize = "9"

        def new_history_sheet(sheet, number):
            sheet.freeze_panes = "A2"
            sheet.page_setup.orientation = "landscape"
            sheet.page_setup.paperSize = "9"
            sheet.column_dimensions["A"].width = 21
            for column in "BCDEFGHIJKLMNOPQR":
                sheet.column_dimensions[column].width = 19
            cells = []
            for heading in EXCEL_HEADERS:
                cell = WriteOnlyCell(sheet, heading)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")
                cells.append(cell)
            sheet.append(cells)
            sheet.auto_filter.ref = f"A1:R{min(cls.EXCEL_MAX_DATA_ROWS + 1, number + 1)}"

        new_history_sheet(ws3, summary["total_records"])
        history_sheet = ws3
        row_count = 0
        id_to_key, _ = cls._resolved()
        for row, _ in cls.iter_rows(start_dt, end_dt, id_to_key):
            if row_count and row_count % cls.EXCEL_MAX_DATA_ROWS == 0:
                history_sheet = wb.create_sheet(f"Dados Históricos {row_count // cls.EXCEL_MAX_DATA_ROWS + 1}")
                new_history_sheet(history_sheet, summary["total_records"] - row_count)
            values = row["values"]
            delta = row.get("cond_delta")
            history_sheet.append([
                row["datetime_str"], values.get("pressao_caldeira"),
                values.get("setpoint_pressao_alta"), values.get("pressao_alta_prensas_1_7"),
                values.get("pressao_alta_prensas_8_12"), row["desvio_1_7"],
                row["desvio_8_12"], row["diferenca_alta"],
                values.get("pressao_baixa_prensas_1_7"), values.get("pressao_baixa_prensas_8_12"),
                row["diferenca_baixa"], row["diferenca_caldeira_1"],
                row["diferenca_caldeira_2"], values.get("volume_condensado"), delta,
                values.get("pressao_ar_comprimido"), values.get("pressao_vacuo"),
                "OK" if row["desvio_1_7"] is not None else "Parcial",
            ])
            row_count += 1
        if row_count >= 2:
            for title, first_col, last_col, anchor in (
                ("Pressão e Setpoint", 2, 5, "A4"),
                ("Linhas de Baixa", 9, 10, "A29"),
                ("Ar Comprimido e Vácuo", 16, 17, "A54"),
            ):
                chart = LineChart()
                chart.title = title
                chart.width, chart.height = 22, 12
                chart_last_row = min(row_count + 1, cls.EXCEL_MAX_DATA_ROWS + 1, 500)
                chart.add_data(Reference(ws3, min_col=first_col, max_col=last_col,
                                         min_row=1, max_row=chart_last_row), titles_from_data=True)
                chart.set_categories(Reference(ws3, min_col=1, min_row=2, max_row=chart_last_row))
                ws2.add_chart(chart, anchor)
        else:
            ws2.append(["Não existem dados suficientes para gerar gráficos."])
        output = tempfile.TemporaryFile(mode="w+b")
        wb.save(output)
        output.seek(0)
        return output
