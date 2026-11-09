"""Planilha analítica da caldeira com os mesmos critérios da tela."""

from datetime import datetime, timezone as dt_timezone
from io import BytesIO

from django.utils import timezone
from openpyxl import Workbook


def _local_excel_time(timestamp_ms):
    aware = datetime.fromtimestamp(timestamp_ms / 1000, tz=dt_timezone.utc)
    return timezone.localtime(aware).replace(tzinfo=None)


def build_insights_excel(analysis):
    book = Workbook(write_only=True)
    overview = book.create_sheet("Resumo")
    overview.append(["Análise da Caldeira 2", "Valor"])
    overview.append(["Início", timezone.localtime(analysis["start"]).strftime("%d/%m/%Y %H:%M")])
    overview.append(["Fim", timezone.localtime(analysis["end"]).strftime("%d/%m/%Y %H:%M")])
    overview.append(["Queda mínima observada (bar)", analysis["drop_bar"]])
    overview.append(["Duração mínima (min)", analysis["min_minutes"]])
    overview.append(["Recuos observados", analysis["drop_total"]])
    overview.append(["Aberturas da porta", analysis["door_openings"] if analysis["door_available"] else None])
    overview.append(["Tempo de porta aberta (min)", analysis["door_open_minutes"] if analysis["door_available"] else None])
    overview.append(["Média por abertura concluída (min)", analysis["door_average_minutes"]])
    overview.append(["Prensas acompanhadas", analysis["press_count"]])
    overview.append(["Maior pressão medida (bar)", analysis["max_pressure"]])
    overview.append(["Observação", "Turnos identificam horários, não pessoas. Abertura longa não comprova alimentação."])

    shifts = book.create_sheet("Turnos")
    shifts.append(["Data", "Turno", "Horas observadas", "Leituras pressão", "Recuos", "Recuos por 12h",
                   "Menor pressão em recuo (bar)", "Maior queda (bar)", "Aberturas",
                   "Porta aberta (min)", "Média abertura (min)", "Rápidas <1min",
                   "Longas >=1min", "Média longas (min)"])
    for row in analysis["shifts"]:
        shifts.append([row["date"], row["label"], row["covered_hours"], row["pressure_samples"],
                       row["drop_count"], row["drops_per_12h"], row["drop_pressure_min"], row["drop_magnitude_max"],
                       row["door_openings"], row["door_open_minutes"], row["door_average_minutes"],
                       row["door_quick_count"], row["door_long_count"], row["door_long_average_minutes"]])

    drops = book.create_sheet("Recuos")
    drops.append(["Início", "Turno", "Pico anterior (bar)", "Menor pressão (bar)",
                  "Queda (bar)", "Duração observada (min)", "Prensas ON", "Porta abriu até 15min antes"])
    for row in reversed(analysis["drops"]):
        drops.append([_local_excel_time(row["ts"]), row["shift"], row["peak_pressure"],
                      row["minimum_pressure"], row["drop_bar"], row["duration_min"],
                      row["active_presses"], "Sim" if row["door_near"] else "Não"])

    door = book.create_sheet("Aberturas da Porta")
    door.append(["Início", "Turno", "Tempo aberta (s)", "Rápida <1min"])
    for row in reversed(analysis["door_events"]):
        door.append([_local_excel_time(row["ts"]), row["shift"], row["duration_seconds"],
                     "Sim" if row["quick"] else "Não"])

    hours = book.create_sheet("Horas")
    hours.append(["Hora", "Parcial", "Prensas ON (média)", "Cobertura prensas (%)",
                  "Condensado (L)", "Pressão média (bar)", "Menor pressão (bar)",
                  "Aberturas porta", "Porta aberta (min)", "Recuos", "Leituras pressão"])
    for row in analysis["hours"]:
        hours.append([row["label"], "Sim" if row["partial"] else "Não", row["active_presses"],
                      row["coverage"], row["cond_liters"], row["pressure_avg"], row["pressure_min"],
                      row["door_openings"], row["door_open_minutes"], row["drop_count"],
                      row["pressure_samples"]])

    output = BytesIO()
    book.save(output)
    output.seek(0)
    return output
