import io
import time
import math
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, List, Any, Optional, Tuple
from django.utils import timezone
from django.db.models import Max, Q
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import ScadaDataPoint, ScadaPointValue, ScadaPointValueAnnotation
from .services import scada_reader


# ==============================================================================
# CANONICAL INVENTORY OF THE 20 CALANDRA VARIABLES
# ==============================================================================

CALANDRA_VARIABLES_CONFIG: List[Dict[str, Any]] = [
    # ── 1. Produção / Contexto ──
    {
        "key": "passada",
        "tag_name": "CALANDRA_meta - PASSADA",
        "label": "Passada",
        "excel_header": "PASSADA",
        "group": "producao",
        "group_label": "Produção",
        "unit": "",
        "data_type": 2,  # Multistate / Contextual
        "order": 1,
        "is_numeric": False,
    },
    {
        "key": "metragem_bobinada",
        "tag_name": "CALANDRA - METRAGEM_BOBINADA",
        "label": "Metragem Bobinada",
        "excel_header": "METRAGEM BOBINADA (m)",
        "group": "producao",
        "group_label": "Produção",
        "unit": "m",
        "data_type": 3,
        "order": 2,
        "is_numeric": True,
    },
    {
        "key": "vel_calandra",
        "tag_name": "CALANDRA - VEL_CALANDRA (m/min)",
        "label": "Velocidade da Calandra",
        "excel_header": "VEL. CALANDRA (m/min)",
        "group": "producao",
        "group_label": "Produção",
        "unit": "m/min",
        "data_type": 3,
        "order": 3,
        "is_numeric": True,
    },

    # ── 2. Cargas / Tensões ──
    {
        "key": "carga_bobinamento",
        "tag_name": "CALANDRA - CARGA_BOBINAMENTO (Kg)",
        "label": "Carga Bobinamento",
        "excel_header": "CARGA BOBINAMENTO (kg)",
        "group": "cargas",
        "group_label": "Cargas",
        "unit": "kg",
        "data_type": 3,
        "order": 4,
        "is_numeric": True,
    },
    {
        "key": "carga_desbobinador",
        "tag_name": "CALANDRA - CARGA_DESBOBINADOR (Kg)",
        "label": "Carga Desbobinador",
        "excel_header": "CARGA DESBOBINADOR (kg)",
        "group": "cargas",
        "group_label": "Cargas",
        "unit": "kg",
        "data_type": 3,
        "order": 5,
        "is_numeric": True,
    },
    {
        "key": "carga_pos_calandra",
        "tag_name": "CALANDRA - CARGA_POS-CALANDRA (Kg)",
        "label": "Carga Pós-Calandra",
        "excel_header": "CARGA PÓS-CALANDRA (kg)",
        "group": "cargas",
        "group_label": "Cargas",
        "unit": "kg",
        "data_type": 3,
        "order": 6,
        "is_numeric": True,
    },
    {
        "key": "carga_quebra_trama",
        "tag_name": "CALANDRA - CARGA_QUEBRA-TRAMA (Kg)",
        "label": "Carga Quebra-Trama",
        "excel_header": "CARGA QUEBRA-TRAMA (kg)",
        "group": "cargas",
        "group_label": "Cargas",
        "unit": "kg",
        "data_type": 3,
        "order": 7,
        "is_numeric": True,
    },

    # ── 3. Espessuras ──
    {
        "key": "espessura_esq_sup",
        "tag_name": "CALANDRA - ESPESSURA_LADO ESQ SUPERIOR",
        "label": "Espessura Esq. Superior",
        "excel_header": "ESPESSURA ESQ. SUPERIOR (mm)",
        "group": "espessuras",
        "group_label": "Espessuras",
        "unit": "mm",
        "data_type": 3,
        "order": 8,
        "is_numeric": True,
    },
    {
        "key": "espessura_dir_sup",
        "tag_name": "CALANDRA - ESPESSURA_LADO DIR SUPERIOR",
        "label": "Espessura Dir. Superior",
        "excel_header": "ESPESSURA DIR. SUPERIOR (mm)",
        "group": "espessuras",
        "group_label": "Espessuras",
        "unit": "mm",
        "data_type": 3,
        "order": 9,
        "is_numeric": True,
    },
    {
        "key": "espessura_dir_inf",
        "tag_name": "CALANDRA - ESPESSURA_LADO DIR INFERIOR",
        "label": "Espessura Dir. Inferior",
        "excel_header": "ESPESSURA DIR. INFERIOR (mm)",
        "group": "espessuras",
        "group_label": "Espessuras",
        "unit": "mm",
        "data_type": 3,
        "order": 10,
        "is_numeric": True,
    },
    {
        "key": "espessura_esq_inf",
        "tag_name": "CALANDRA - ESPESSURA_LADO ESQ INFERIOR",
        "label": "Espessura Esq. Inferior",
        "excel_header": "ESPESSURA ESQ. INFERIOR (mm)",
        "group": "espessuras",
        "group_label": "Espessuras",
        "unit": "mm",
        "data_type": 3,
        "order": 11,
        "is_numeric": True,
    },

    # ── 4. Temperaturas da Borracha ──
    {
        "key": "temp_borracha_saida_extrusao",
        "tag_name": "CALANDRA - TEMPERATURA_BORRACHA_SAIDA_EXTRUSAO (°C)",
        "label": "Saída Extrusão",
        "excel_header": "TEMP. BORRACHA SAÍDA EXTRUSÃO (°C)",
        "group": "temperatura_borracha",
        "group_label": "Temperatura da Borracha",
        "unit": "°C",
        "data_type": 3,
        "order": 12,
        "is_numeric": True,
    },
    {
        "key": "temp_borracha_ent_calandra",
        "tag_name": "CALANDRA - TEMPERATURA_BORRACHA_ENT_CALANDRA (°C)",
        "label": "Entrada Calandra",
        "excel_header": "TEMP. BORRACHA ENTRADA CALANDRA (°C)",
        "group": "temperatura_borracha",
        "group_label": "Temperatura da Borracha",
        "unit": "°C",
        "data_type": 3,
        "order": 13,
        "is_numeric": True,
    },
    {
        "key": "temp_borracha_saida_calandra",
        "tag_name": "CALANDRA - TEMPERATURA_BORRACHA_SAIDA_CALANDRA (°C)",
        "label": "Saída Calandra",
        "excel_header": "TEMP. BORRACHA SAÍDA CALANDRA (°C)",
        "group": "temperatura_borracha",
        "group_label": "Temperatura da Borracha",
        "unit": "°C",
        "data_type": 3,
        "order": 14,
        "is_numeric": True,
    },

    # ── 5. Temperaturas do Processo / Equipamento ──
    {
        "key": "temp_cilindro_inf",
        "tag_name": "CALANDRA_TEMPERATURA - CILINDRO_INFERIOR (°C)",
        "label": "Cilindro Inferior",
        "excel_header": "TEMP. CILINDRO INFERIOR (°C)",
        "group": "temperaturas_processo",
        "group_label": "Temperaturas do Processo",
        "unit": "°C",
        "data_type": 3,
        "order": 15,
        "is_numeric": True,
    },
    {
        "key": "temp_cilindro_inter",
        "tag_name": "CALANDRA_TEMPERATURA - CILINDRO_INTERMEDIÁRIO (°C)",
        "label": "Cilindro Intermediário",
        "excel_header": "TEMP. CILINDRO INTERMEDIÁRIO (°C)",
        "group": "temperaturas_processo",
        "group_label": "Temperaturas do Processo",
        "unit": "°C",
        "data_type": 3,
        "order": 16,
        "is_numeric": True,
    },
    {
        "key": "temp_cilindro_sup",
        "tag_name": "CALANDRA_TEMPERATURA - CILINDRO_SUPERIOR (°C)",
        "label": "Cilindro Superior",
        "excel_header": "TEMP. CILINDRO SUPERIOR (°C)",
        "group": "temperaturas_processo",
        "group_label": "Temperaturas do Processo",
        "unit": "°C",
        "data_type": 3,
        "order": 17,
        "is_numeric": True,
    },
    {
        "key": "temp_furador",
        "tag_name": "CALANDRA_TEMPERATURA - FURADOR (°C)",
        "label": "Furador",
        "excel_header": "TEMP. FURADOR (°C)",
        "group": "temperaturas_processo",
        "group_label": "Temperaturas do Processo",
        "unit": "°C",
        "data_type": 3,
        "order": 18,
        "is_numeric": True,
    },
    {
        "key": "temp_aquecedor",
        "tag_name": "CALANDRA_TEMPERATURA - AQUECEDOR",
        "label": "Aquecedor",
        "excel_header": "TEMP. AQUECEDOR (°C)",
        "group": "temperaturas_processo",
        "group_label": "Temperaturas do Processo",
        "unit": "°C",
        "data_type": 3,
        "order": 19,
        "is_numeric": True,
    },
    {
        "key": "temp_tcu_extrusora",
        "tag_name": "CALANDRA_TEMPERATURA - TCU_EXTRUSORA (°C)",
        "label": "TCU Extrusora",
        "excel_header": "TEMP. TCU EXTRUSORA (°C)",
        "group": "temperaturas_processo",
        "group_label": "Temperaturas do Processo",
        "unit": "°C",
        "data_type": 3,
        "order": 20,
        "is_numeric": True,
    },
]


class CalandraHistoricalService:
    """
    Serviço especializado para consulta histórica, sincronização temporal (forward-fill),
    visualização gráfica agrupada e exportação Excel das variáveis da CALANDRA.
    """

    MAX_QUERY_DAYS = 31  # Proteção contra períodos excessivos ao SCADA

    @classmethod
    def get_variables_config(cls) -> List[Dict[str, Any]]:
        """
        Retorna as 20 configurações de variáveis da Calandra.
        Verifica no banco 'default' (ProductionGlobalParameter) se o usuário customizou
        algum XID via Central de Configuração SCADA. Caso contrário, utiliza o padrão canônico.
        """
        from .models import ProductionGlobalParameter
        configs = [dict(c) for c in CALANDRA_VARIABLES_CONFIG]
        try:
            db_params = {
                p.chave: p.xid
                for p in ProductionGlobalParameter.objects.filter(chave__startswith="calandra_")
                if p.xid and p.xid.strip()
            }
            if db_params:
                for c in configs:
                    db_key = f"calandra_{c['key']}"
                    if db_key in db_params:
                        c["tag_name"] = db_params[db_key].strip()
        except Exception:
            pass
        return configs

    @classmethod
    def format_passada_label(cls, val: Any) -> str:
        """
        Formata o valor da variável PASSADA em rótulo contextual:
        - 1 / '1': PASSADA 1 (1ª face)
        - 2 / '2': PASSADA 2 (2ª face / face oposta)
        """
        if val is None or val == "":
            return "Não informada"
        s = str(val).strip()
        try:
            f = float(s)
            int_v = int(f)
            if int_v == 1:
                return "PASSADA 1 (1ª face)"
            elif int_v == 2:
                return "PASSADA 2 (2ª face / face oposta)"
            return f"PASSADA {int_v}"
        except (ValueError, TypeError):
            if s == "1":
                return "PASSADA 1 (1ª face)"
            elif s == "2":
                return "PASSADA 2 (2ª face / face oposta)"
            return s

    @classmethod
    def parse_period_filters(
        cls,
        periodo: Optional[str] = None,
        data_inicio: Optional[str] = None,
        hora_inicio: Optional[str] = None,
        data_final: Optional[str] = None,
        hora_final: Optional[str] = None,
    ) -> Tuple[datetime, datetime, str, Optional[str]]:
        """
        Interpreta filtros de período retornando (start_dt, end_dt, periodo_ativo, error_msg).
        Respeita o timezone do Django (America/Sao_Paulo).
        """
        now = timezone.localtime()
        today_date = now.date()
        error_msg = None

        if periodo == "ontem":
            yesterday = today_date - timedelta(days=1)
            start_dt = timezone.make_aware(datetime.combine(yesterday, dt_time(0, 0, 0)))
            end_dt = timezone.make_aware(datetime.combine(yesterday, dt_time(23, 59, 59, 999000)))
            return start_dt, end_dt, "ontem", None

        elif periodo == "7d":
            start_date = today_date - timedelta(days=7)
            start_dt = timezone.make_aware(datetime.combine(start_date, dt_time(0, 0, 0)))
            end_dt = now
            return start_dt, end_dt, "7d", None

        elif periodo == "30d":
            start_date = today_date - timedelta(days=30)
            start_dt = timezone.make_aware(datetime.combine(start_date, dt_time(0, 0, 0)))
            end_dt = now
            return start_dt, end_dt, "30d", None

        elif periodo == "personalizado" or (data_inicio and data_final):
            try:
                # Tratar data_inicio
                d_ini = datetime.strptime(data_inicio.strip(), "%Y-%m-%d").date()
                if hora_inicio and hora_inicio.strip():
                    h_ini = datetime.strptime(hora_inicio.strip(), "%H:%M").time()
                else:
                    h_ini = dt_time(0, 0, 0)
                start_dt = timezone.make_aware(datetime.combine(d_ini, h_ini))

                # Tratar data_final
                d_fim = datetime.strptime(data_final.strip(), "%Y-%m-%d").date()
                if hora_final and hora_final.strip():
                    h_fim = datetime.strptime(hora_final.strip(), "%H:%M").time()
                else:
                    h_fim = dt_time(23, 59, 59, 999000)
                end_dt = timezone.make_aware(datetime.combine(d_fim, h_fim))

                if start_dt > end_dt:
                    error_msg = "A data/hora inicial não pode ser maior que a data/hora final."
                    start_dt = timezone.make_aware(datetime.combine(today_date, dt_time(0, 0, 0)))
                    end_dt = now
                    return start_dt, end_dt, "hoje", error_msg

                # Proteção contra períodos excessivos (> 31 dias)
                if (end_dt - start_dt).days > cls.MAX_QUERY_DAYS:
                    error_msg = f"O intervalo máximo permitido para consulta é de {cls.MAX_QUERY_DAYS} dias."
                    start_dt = end_dt - timedelta(days=cls.MAX_QUERY_DAYS)

                return start_dt, end_dt, "personalizado", error_msg
            except Exception as e:
                error_msg = f"Parâmetros de data/hora inválidos: {e}"
                start_dt = timezone.make_aware(datetime.combine(today_date, dt_time(0, 0, 0)))
                end_dt = now
                return start_dt, end_dt, "hoje", error_msg

        # Padrão: Hoje
        start_dt = timezone.make_aware(datetime.combine(today_date, dt_time(0, 0, 0)))
        end_dt = now
        return start_dt, end_dt, "hoje", None

    @classmethod
    def resolve_calandra_datapoints(cls) -> Dict[str, Dict[str, Any]]:
        """
        Localiza os DataPoints do Scada-LTS para as 20 variáveis.
        Busca de forma flexível por `xid` ou `pointName` para garantir compatibilidade.
        Retorna dicionário {var_key: {'dp_id': int, 'xid': str, 'point_name': str, 'config': dict}}.
        """
        configs = cls.get_variables_config()
        tag_names = [c["tag_name"] for c in configs]

        resolved: Dict[str, Dict[str, Any]] = {}
        try:
            dps = list(
                ScadaDataPoint.objects.using("scada")
                .filter(Q(xid__in=tag_names) | Q(point_name__in=tag_names))
                .values("id", "xid", "point_name")
            )
            dp_by_xid = {dp["xid"]: dp for dp in dps}
            dp_by_name = {dp["point_name"]: dp for dp in dps if dp.get("point_name")}

            for c in configs:
                tag = c["tag_name"]
                dp_match = dp_by_xid.get(tag) or dp_by_name.get(tag)
                if dp_match:
                    resolved[c["key"]] = {
                        "dp_id": dp_match["id"],
                        "xid": dp_match["xid"],
                        "point_name": dp_match["point_name"],
                        "config": c,
                    }
                else:
                    # Registra entrada mesmo que datapoint não exista ainda no banco
                    resolved[c["key"]] = {
                        "dp_id": None,
                        "xid": tag,
                        "point_name": tag,
                        "config": c,
                    }
        except Exception:
            for c in configs:
                resolved[c["key"]] = {
                    "dp_id": None,
                    "xid": c["tag_name"],
                    "point_name": c["tag_name"],
                    "config": c,
                }

        return resolved

    @classmethod
    def get_synchronized_history(
        cls,
        start_dt: datetime,
        end_dt: datetime,
    ) -> Dict[str, Any]:
        """
        Executa a consulta histórica indexada e executa o algoritmo de forward-fill temporal.
        Retorna:
        {
            'timeline': List[Dict[str, Any]], # Lista de estados conhecidos por timestamp
            'raw_points_count': int,
            'variables_found_count': int,
            'variables_missing': List[str],
            'chart_datasets': Dict[str, Any], # Datasets preparados para os 5 gráficos
            'start_dt': datetime,
            'end_dt': datetime,
        }
        """
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)

        resolved_dps = cls.resolve_calandra_datapoints()
        dp_id_to_key: Dict[int, str] = {}
        active_dp_ids: List[int] = []
        variables_missing: List[str] = []

        for key, info in resolved_dps.items():
            if info["dp_id"]:
                dp_id_to_key[info["dp_id"]] = key
                active_dp_ids.append(info["dp_id"])
            else:
                variables_missing.append(info["config"]["label"])

        if not active_dp_ids:
            return {
                "timeline": [],
                "raw_points_count": 0,
                "variables_found_count": 0,
                "variables_missing": variables_missing,
                "chart_datasets": cls._empty_chart_datasets(),
                "start_dt": start_dt,
                "end_dt": end_dt,
            }

        # 1. Obter estado inicial anterior ao start_ms para cada DP (seed do forward-fill)
        initial_state: Dict[str, Any] = {}
        for key in resolved_dps:
            initial_state[key] = None

        try:
            prior_max_ts_records = (
                ScadaPointValue.objects.using("scada")
                .filter(data_point_id__in=active_dp_ids, ts__lt=start_ms)
                .values("data_point_id")
                .annotate(max_ts=Max("ts"))
            )
            prior_map = {r["data_point_id"]: r["max_ts"] for r in prior_max_ts_records if r.get("max_ts")}
            if prior_map:
                q_prior = Q()
                for dp_id, max_ts in prior_map.items():
                    q_prior |= Q(data_point_id=dp_id, ts=max_ts)

                prior_values = (
                    ScadaPointValue.objects.using("scada")
                    .filter(q_prior)
                    .select_related("annotation")
                )
                for pv in prior_values:
                    v_key = dp_id_to_key.get(pv.data_point_id)
                    if v_key:
                        norm_val, _ = scada_reader.normalize_value(pv.data_type, pv.point_value, getattr(pv, "annotation", None))
                        initial_state[v_key] = norm_val
        except Exception:
            pass

        # 2. Consultar todos os registros no intervalo [start_ms, end_ms] indexados por ts
        try:
            point_values_qs = (
                ScadaPointValue.objects.using("scada")
                .filter(data_point_id__in=active_dp_ids, ts__gte=start_ms, ts__lte=end_ms)
                .select_related("annotation")
                .order_by("ts", "id")
            )
            raw_records = list(point_values_qs)
        except Exception:
            raw_records = []

        raw_points_count = len(raw_records)

        # 3. Algoritmo de Forward-Fill Temporal
        # Agrupar registros por timestamp único
        events_by_ts: Dict[int, Dict[str, Any]] = {}
        for pv in raw_records:
            v_key = dp_id_to_key.get(pv.data_point_id)
            if not v_key:
                continue
            norm_val, _ = scada_reader.normalize_value(pv.data_type, pv.point_value, getattr(pv, "annotation", None))
            if pv.ts not in events_by_ts:
                events_by_ts[pv.ts] = {}
            events_by_ts[pv.ts][v_key] = norm_val

        current_state = initial_state.copy()
        timeline: List[Dict[str, Any]] = []

        # Se houver estado inicial mas nenhum evento no intervalo, emitir ponto no início da janela
        if not events_by_ts and any(v is not None for v in current_state.values()):
            row_dt = timezone.localtime(timezone.datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc))
            passada_val = current_state.get("passada")
            timeline.append({
                "ts": start_ms,
                "datetime": row_dt,
                "datetime_str": row_dt.strftime("%d/%m/%Y %H:%M:%S"),
                "passada_val": passada_val,
                "passada_label": cls.format_passada_label(passada_val),
                "values": current_state.copy(),
            })

        for ts in sorted(events_by_ts.keys()):
            updates = events_by_ts[ts]
            current_state.update(updates)
            row_dt = timezone.localtime(timezone.datetime.fromtimestamp(ts / 1000, tz=timezone.utc))
            passada_val = current_state.get("passada")

            timeline.append({
                "ts": ts,
                "datetime": row_dt,
                "datetime_str": row_dt.strftime("%d/%m/%Y %H:%M:%S"),
                "passada_val": passada_val,
                "passada_label": cls.format_passada_label(passada_val),
                "values": current_state.copy(),
            })

        # 4. Preparar datasets para os 5 gráficos com amostragem inteligente se necessário
        chart_datasets = cls._build_chart_datasets(timeline)

        return {
            "timeline": timeline,
            "raw_points_count": raw_points_count,
            "variables_found_count": len(active_dp_ids),
            "variables_missing": variables_missing,
            "chart_datasets": chart_datasets,
            "start_dt": start_dt,
            "end_dt": end_dt,
        }

    @classmethod
    def _empty_chart_datasets(cls) -> Dict[str, Any]:
        return {
            "chart_a_producao": {"labels": [], "velocidade": [], "metragem": [], "passada": []},
            "chart_b_cargas": {"labels": [], "bobinamento": [], "desbobinador": [], "pos_calandra": [], "quebra_trama": []},
            "chart_c_espessuras": {"labels": [], "esq_sup": [], "dir_sup": [], "dir_inf": [], "esq_inf": []},
            "chart_d_temp_borracha": {"labels": [], "saida_extrusao": [], "ent_calandra": [], "saida_calandra": []},
            "chart_e_temp_processo": {"labels": [], "cilindro_inf": [], "cilindro_inter": [], "cilindro_sup": [], "furador": [], "aquecedor": [], "tcu_extrusora": []},
        }

    @classmethod
    def _build_chart_datasets(cls, timeline: List[Dict[str, Any]], max_chart_points: int = 1500) -> Dict[str, Any]:
        """
        Monta as séries de dados para Chart.js.
        Aplica amostragem equidistante preservando transições de PASSADA se o volume de pontos for elevado.
        """
        if not timeline:
            return cls._empty_chart_datasets()

        total = len(timeline)
        sampled_timeline: List[Dict[str, Any]] = []

        if total <= max_chart_points:
            sampled_timeline = timeline
        else:
            step = total / max_chart_points
            last_passada = None
            for i in range(max_chart_points):
                idx = min(int(i * step), total - 1)
                item = timeline[idx]
                sampled_timeline.append(item)
                last_passada = item.get("passada_val")

            # Garantir inclusão de transições de passada que poderiam ter sido puladas
            for idx in range(1, total):
                if timeline[idx].get("passada_val") != timeline[idx - 1].get("passada_val"):
                    if timeline[idx] not in sampled_timeline:
                        sampled_timeline.append(timeline[idx])

            sampled_timeline.sort(key=lambda x: x["ts"])

        # Extrair vetores
        labels = [item["datetime_str"] for item in sampled_timeline]
        passada_vals = [item.get("passada_val") for item in sampled_timeline]

        def _get_float(item: Dict[str, Any], key: str) -> Optional[float]:
            v = item["values"].get(key)
            if v is None:
                return None
            try:
                return round(float(v), 2)
            except (ValueError, TypeError):
                return None

        return {
            "chart_a_producao": {
                "labels": labels,
                "velocidade": [_get_float(item, "vel_calandra") for item in sampled_timeline],
                "metragem": [_get_float(item, "metragem_bobinada") for item in sampled_timeline],
                "passada": passada_vals,
                "passada_labels": [cls.format_passada_label(p) for p in passada_vals],
            },
            "chart_b_cargas": {
                "labels": labels,
                "bobinamento": [_get_float(item, "carga_bobinamento") for item in sampled_timeline],
                "desbobinador": [_get_float(item, "carga_desbobinador") for item in sampled_timeline],
                "pos_calandra": [_get_float(item, "carga_pos_calandra") for item in sampled_timeline],
                "quebra_trama": [_get_float(item, "carga_quebra_trama") for item in sampled_timeline],
            },
            "chart_c_espessuras": {
                "labels": labels,
                "esq_sup": [_get_float(item, "espessura_esq_sup") for item in sampled_timeline],
                "dir_sup": [_get_float(item, "espessura_dir_sup") for item in sampled_timeline],
                "dir_inf": [_get_float(item, "espessura_dir_inf") for item in sampled_timeline],
                "esq_inf": [_get_float(item, "espessura_esq_inf") for item in sampled_timeline],
            },
            "chart_d_temp_borracha": {
                "labels": labels,
                "saida_extrusao": [_get_float(item, "temp_borracha_saida_extrusao") for item in sampled_timeline],
                "ent_calandra": [_get_float(item, "temp_borracha_ent_calandra") for item in sampled_timeline],
                "saida_calandra": [_get_float(item, "temp_borracha_saida_calandra") for item in sampled_timeline],
            },
            "chart_e_temp_processo": {
                "labels": labels,
                "cilindro_inf": [_get_float(item, "temp_cilindro_inf") for item in sampled_timeline],
                "cilindro_inter": [_get_float(item, "temp_cilindro_inter") for item in sampled_timeline],
                "cilindro_sup": [_get_float(item, "temp_cilindro_sup") for item in sampled_timeline],
                "furador": [_get_float(item, "temp_furador") for item in sampled_timeline],
                "aquecedor": [_get_float(item, "temp_aquecedor") for item in sampled_timeline],
                "tcu_extrusora": [_get_float(item, "temp_tcu_extrusora") for item in sampled_timeline],
            },
        }

    @classmethod
    def generate_excel_report(
        cls,
        start_dt: datetime,
        end_dt: datetime,
    ) -> bytes:
        """
        Gera arquivo Excel (.xlsx) contendo 100% dos dados históricos sincronizados brutos.
        Primeira coluna: DATA/HORA
        Segunda coluna: PASSADA
        Demais colunas: Variáveis da Calandra
        """
        history = cls.get_synchronized_history(start_dt, end_dt)
        timeline = history["timeline"]
        configs = cls.get_variables_config()

        # Variáveis excluindo 'passada' (que fica na coluna 2)
        other_vars = [c for c in configs if c["key"] != "passada"]

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Histórico Calandra"
        ws.views.sheetView[0].showGridLines = True

        # Estilos
        font_header = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        fill_header = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        fill_header_gold = PatternFill(start_color="B8842E", end_color="B8842E", fill_type="solid")
        border_thin = Border(
            left=Side(style="thin", color="E2E8F0"),
            right=Side(style="thin", color="E2E8F0"),
            top=Side(style="thin", color="E2E8F0"),
            bottom=Side(style="thin", color="E2E8F0"),
        )
        font_data = Font(name="Segoe UI", size=10, color="0F172A")
        font_passada1 = Font(name="Segoe UI", size=10, bold=True, color="0369A1")
        font_passada2 = Font(name="Segoe UI", size=10, bold=True, color="B45309")
        align_center = Alignment(horizontal="center", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")
        align_left = Alignment(horizontal="left", vertical="center")

        # Cabeçalhos
        headers = ["DATA/HORA", "PASSADA"] + [c["excel_header"] for c in other_vars]
        ws.append(headers)

        # Formatar Linha 1 (Cabeçalho)
        ws.row_dimensions[1].height = 28
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.font = font_header
            cell.fill = fill_header_gold if col_num in (1, 2) else fill_header
            cell.alignment = align_center
            cell.border = border_thin

        # Preencher Dados
        for row_idx, item in enumerate(timeline, start=2):
            ws.row_dimensions[row_idx].height = 20
            row_dt = item["datetime"]
            passada_lbl = item["passada_label"]

            # Coluna 1: DATA/HORA (como datetime do Excel)
            c1 = ws.cell(row=row_idx, column=1, value=row_dt.strftime("%d/%m/%Y %H:%M:%S"))
            c1.font = font_data
            c1.alignment = align_center
            c1.border = border_thin

            # Coluna 2: PASSADA
            c2 = ws.cell(row=row_idx, column=2, value=passada_lbl)
            c2.font = font_passada1 if "PASSADA 1" in passada_lbl else (font_passada2 if "PASSADA 2" in passada_lbl else font_data)
            c2.alignment = align_center
            c2.border = border_thin

            # Demais colunas
            for c_idx, c_cfg in enumerate(other_vars, start=3):
                raw_v = item["values"].get(c_cfg["key"])
                cell = ws.cell(row=row_idx, column=c_idx)
                cell.border = border_thin
                cell.font = font_data

                if raw_v is None or raw_v == "":
                    cell.value = "-"
                    cell.alignment = align_center
                elif c_cfg["is_numeric"]:
                    try:
                        num_val = round(float(raw_v), 2)
                        cell.value = num_val
                        cell.alignment = align_right
                        cell.number_format = "#,##0.00" if isinstance(num_val, float) and not num_val.is_integer() else "#,##0"
                    except (ValueError, TypeError):
                        cell.value = str(raw_v)
                        cell.alignment = align_left
                else:
                    cell.value = str(raw_v)
                    cell.alignment = align_left

        # Configurações de Usabilidade
        ws.freeze_panes = "A2"
        if timeline:
            ws.auto_filter.ref = ws.dimensions

        # Auto-ajuste de largura de colunas
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or "")
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 14)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()
