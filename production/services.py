import logging
import time
from datetime import datetime, date, time as dt_time, timedelta
from typing import Dict, List, Any, Optional
from django.db import models, transaction
from django.db.models import Max, Q
from django.utils import timezone
from maintenance.models import Machine, Allocation, AllocationProgressUpdate
from .models import (
    ProductionShift,
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    ProductionMachineState,
    ProductionDowntimeEvent,
    ProductionCavityState,
    ProductionCavityDowntimeEvent,
    ProductionCavityMatrixHistory,
    ProductionMachineStateInterval,
    ProductionRateAggregate,
    ProductionParameterConfig,
    ProductionParameterAnomalyEvent,
    ProductionCycle,
    ProductionShiftAccumulated,
    ProductionMatrixCatalog,
    ProductionTarget,
    ProductionMatrixSize,
    ProductionBladder,
    ProductionPCPSetting,
    ProductionPCPPlan,
    ProductionPCPPlanShiftTarget,
    ProductionPCPPlanHistory,
    ProductionBladderChangeReason,
    ProductionBladderUsage,
    ProductionBladderSetupMismatchEvent,
    ScadaDataPoint,
    ScadaPointValue,
    ScadaPointValueAnnotation,
)

logger = logging.getLogger(__name__)


def get_active_shift(at_datetime=None) -> Dict[str, Any]:
    """
    Retorna as informações do turno ativo para uma determinada data/hora (ou timezone.localtime()).
    Suporta turnos diurnos e turnos que atravessam a meia-noite.
    """
    if at_datetime is None:
        at_datetime = timezone.localtime()
    elif timezone.is_naive(at_datetime):
        at_datetime = timezone.make_aware(at_datetime)

    active_shifts = list(ProductionShift.objects.filter(ativo=True).order_by("ordem_exibicao", "horario_inicial"))
    if not active_shifts:
        return {
            "shift": None,
            "nome": "Sem turno ativo",
            "horario_inicial_str": "",
            "horario_final_str": "",
            "effective_percent": 100.0,
            "shift_start_dt": None,
            "shift_end_dt": None,
            "active_shifts_count": 0,
            "total_active_percent": 0.0,
            "has_shifts": False,
        }

    custom_percents = [float(s.percentual_meta or 0) for s in active_shifts]
    total_custom = sum(custom_percents)
    is_custom = any(p > 0 for p in custom_percents) and abs(total_custom - 100.0) < 0.01

    curr_time = at_datetime.time()
    curr_date = at_datetime.date()

    matched_shift = None
    matched_percent = 100.0 / len(active_shifts)
    shift_start_dt = None
    shift_end_dt = None

    for s in active_shifts:
        percent = float(s.percentual_meta) if is_custom else (100.0 / len(active_shifts))
        h_ini = s.horario_inicial
        h_fim = s.horario_final

        is_match = False
        if s.atravessa_meia_noite:
            if curr_time >= h_ini or curr_time < h_fim:
                is_match = True
        else:
            if h_ini <= curr_time < h_fim:
                is_match = True

        if is_match and matched_shift is None:
            matched_shift = s
            matched_percent = percent
            if s.atravessa_meia_noite:
                if curr_time >= h_ini:
                    start_date = curr_date
                    end_date = curr_date + timezone.timedelta(days=1)
                else:
                    start_date = curr_date - timezone.timedelta(days=1)
                    end_date = curr_date
            else:
                start_date = curr_date
                end_date = curr_date

            shift_start_dt = timezone.make_aware(timezone.datetime.combine(start_date, h_ini))
            shift_end_dt = timezone.make_aware(timezone.datetime.combine(end_date, h_fim))

    if matched_shift is None:
        matched_shift = active_shifts[0]
        matched_percent = float(matched_shift.percentual_meta) if is_custom else (100.0 / len(active_shifts))
        s = matched_shift
        h_ini = s.horario_inicial
        h_fim = s.horario_final
        if s.atravessa_meia_noite:
            if curr_time >= h_ini:
                start_date = curr_date
                end_date = curr_date + timezone.timedelta(days=1)
            else:
                start_date = curr_date - timezone.timedelta(days=1)
                end_date = curr_date
        else:
            start_date = curr_date
            end_date = curr_date
        shift_start_dt = timezone.make_aware(timezone.datetime.combine(start_date, h_ini))
        shift_end_dt = timezone.make_aware(timezone.datetime.combine(end_date, h_fim))

    return {
        "shift": matched_shift,
        "nome": matched_shift.nome,
        "horario_inicial_str": matched_shift.horario_inicial.strftime("%H:%M"),
        "horario_final_str": matched_shift.horario_final.strftime("%H:%M"),
        "effective_percent": round(matched_percent, 2),
        "shift_start_dt": shift_start_dt,
        "shift_end_dt": shift_end_dt,
        "active_shifts_count": len(active_shifts),
        "total_active_percent": 100.0,
        "has_shifts": True,
    }


def normalize_matrix_value(raw_val: Any) -> str:
    """
    Normaliza o valor da matriz de forma idempotente e insensível a formatação.
    Exemplos: '12', 12, 12.0, ' 12 ' -> '12'.
    Se for None ou string vazia, retorna ''.
    """
    if raw_val is None:
        return ""
    s_val = str(raw_val).strip()
    if not s_val or s_val.lower() in ("none", "null", "n/a"):
        return ""
    try:
        f_val = float(s_val)
        if f_val.is_integer():
            return str(int(f_val))
    except (ValueError, TypeError):
        pass
    return s_val


def compose_bladder_lot(prefix: Any, number: Any) -> Dict[str, Any]:
    """
    Combina o prefixo (1ª parte / xid_produto) e o número (2ª parte / xid_lote_bladder)
    para apresentar o lote completo do bladder de forma segura.

    Exemplo completo: prefix='6154', number='161046' -> '6154 - 161046'
    Exemplo lote incompleto 1: prefix='6154', number='' -> '6154 - Não informado'
    Exemplo lote incompleto 2: prefix='', number='161046' -> 'Não informado - 161046'
    Exemplo ausente: prefix='', number='' -> 'Não informado'
    """
    def _clean(val: Any) -> str:
        if val is None:
            return ""
        s = str(val).strip()
        if not s or s.lower() in ("none", "null", "n/a", "-", "não informado", "não informada"):
            return ""
        try:
            if "." in s:
                f_val = float(s)
                if f_val.is_integer():
                    return str(int(f_val))
        except (ValueError, TypeError):
            pass
        return s

    p_clean = _clean(prefix)
    n_clean = _clean(number)

    if p_clean and n_clean:
        return {
            "display": f"{p_clean} - {n_clean}",
            "prefix": p_clean,
            "number": n_clean,
            "is_complete": True,
            "is_incomplete": False,
            "status": "COMPLETO",
        }
    elif p_clean and not n_clean:
        return {
            "display": f"{p_clean} - Não informado",
            "prefix": p_clean,
            "number": "",
            "is_complete": False,
            "is_incomplete": True,
            "status": "INCOMPLETO",
        }
    elif not p_clean and n_clean:
        return {
            "display": f"Não informado - {n_clean}",
            "prefix": "",
            "number": n_clean,
            "is_complete": False,
            "is_incomplete": True,
            "status": "INCOMPLETO",
        }
    else:
        return {
            "display": "Não informado",
            "prefix": "",
            "number": "",
            "is_complete": False,
            "is_incomplete": False,
            "status": "AUSENTE",
        }


def resolve_matrix_product_display(raw_matriz: Any) -> Dict[str, Any]:
    """
    Traduz o código da matriz lido via SCADA (xid_matriz) utilizando o catálogo canônico
    dos 43 modelos do SCADA (ProductionMatrixCatalog).
    """
    if raw_matriz is None:
        return {
            "display": "Não informado",
            "raw_code": "",
            "catalog_obj": None,
            "matrix_identified": False,
            "is_unregistered": False,
        }
    s_val = str(raw_matriz).strip()
    if not s_val or s_val.lower() in ("none", "null", "n/a", "não informada", "não informado"):
        return {
            "display": "Não informado",
            "raw_code": "",
            "catalog_obj": None,
            "matrix_identified": False,
            "is_unregistered": False,
        }

    catalog_obj = None
    if s_val.isdigit():
        catalog_obj = ProductionMatrixCatalog.objects.filter(codigo_scada=int(s_val)).first()
    if not catalog_obj:
        catalog_obj = ProductionMatrixCatalog.objects.filter(
            Q(codigo__iexact=s_val) |
            Q(nome_scada__iexact=s_val) |
            Q(nome_exibicao__iexact=s_val) |
            Q(produto__iexact=s_val)
        ).first()

    if catalog_obj:
        display_name = catalog_obj.nome_exibicao or catalog_obj.nome_scada or catalog_obj.produto or catalog_obj.descricao
        return {
            "display": display_name,
            "raw_code": s_val,
            "catalog_obj": catalog_obj,
            "matrix_identified": True,
            "is_unregistered": False,
        }
    else:
        return {
            "display": f"Código não cadastrado: {s_val}",
            "raw_code": s_val,
            "catalog_obj": None,
            "matrix_identified": False,
            "is_unregistered": True,
        }


def normalize_bladder_code(raw_val: Any) -> str:
    """
    Normaliza o código do bladder de forma idempotente e canônica para o formato BLA### (ex: BLA003).
    Suporta:
      - Inteiro / Float: 3, 3.0, 6 -> 'BLA003', 'BLA006'
      - Texto com zeros: '003', '03', '3' -> 'BLA003'
      - Texto com prefixo: 'bla003', 'BLA003', 'bla 3', 'BLA-03' -> 'BLA003'
      - Inválidos, zero, nulos ou vazios: 0, '0', '', None, 'N/A' -> ''
    """
    if raw_val is None:
        return ""
    s_val = str(raw_val).strip().upper()
    if not s_val or s_val in ("0", "0.0", "NONE", "NULL", "N/A", "NENHUM", "-"):
        return ""

    import re
    digits_match = re.search(r"(?:BLA\s*[-_]?\s*)?(\d+)(?:\.0+)?$", s_val)
    if digits_match:
        num = int(digits_match.group(1))
        if num > 0:
            return f"BLA{num:03d}"
        return ""

    if s_val.startswith("BLA"):
        clean_bla = re.sub(r"\s+", "", s_val)
        return clean_bla

    return ""


def get_expected_bladders_for_matrix(raw_matriz: Any) -> List[str]:
    """
    Retorna a lista canônica de códigos BLA autorizados/compatíveis para a matriz informada.
    Autoridade: ProductionMatrixCatalog -> medida_size -> bladders.
    """
    mat_info = resolve_matrix_product_display(raw_matriz)
    catalog_obj = mat_info.get("catalog_obj")
    if not catalog_obj or not catalog_obj.medida_size:
        return []

    bladders_qs = catalog_obj.medida_size.bladders.filter(ativo=True).values_list("codigo_bladder", flat=True)
    expected_list = [normalize_bladder_code(b) for b in bladders_qs if normalize_bladder_code(b)]
    return sorted(list(set(expected_list)))


_pending_bladder_reasons: Dict[int, Dict[str, Any]] = {}
BLADDER_REASON_WINDOW_SECONDS = 15 * 60  # 15 minutos
_setup_divergence_counter: Dict[int, int] = {}


class ScadaReaderService:
    """
    Leitura otimizada em lote das tabelas não gerenciadas do Scada-LTS (datapoints, pointvalues, pointvalueannotations).
    - Mapeamento XID -> dataPointId em lote com cache em memória (TTL 15 min).
    - Cache de falha para XIDs inexistentes (cooldown 10s).
    - Consulta dos últimos valores em lote via subquery MAX(ts).
    - Cache curto de valores (TTL 2s).
    - Normalização por dataType:
        1: Binary (True/False)
        2: Multistate (int)
        3: Numeric (float/int)
        4: String/Alphanumeric (textPointValueShort / textPointValueLong)
    - Resiliência contra timeout / falha de banco sem expor credenciais em logs.
    """

    _XID_CACHE_TTL = 900     # 15 minutos
    _FAILED_XID_TTL = 10     # 10 segundos
    _VALUE_CACHE_TTL = 2.0   # 2 segundos

    def __init__(self):
        self._xid_to_id_cache: Dict[str, int] = {}
        self._xid_cache_time: Dict[str, float] = {}
        self._failed_xids: Dict[str, float] = {}
        self._value_cache: Dict[str, dict] = {}

    def clear_caches(self):
        """Invalida todos os caches em memória."""
        self._xid_to_id_cache.clear()
        self._xid_cache_time.clear()
        self._failed_xids.clear()
        self._value_cache.clear()

    def get_data_point_ids(self, xids: List[str]) -> Dict[str, int]:
        """Retorna um dicionário mapeando {xid: data_point_id} em lote."""
        now = time.time()
        result = {}
        missing_xids = []

        for xid in xids:
            if not xid or not str(xid).strip():
                continue
            xid_clean = str(xid).strip()
            
            # Checar quarentena de XIDs que falharam recentemente
            if xid_clean in self._failed_xids:
                if now - self._failed_xids[xid_clean] < self._FAILED_XID_TTL:
                    continue
                else:
                    del self._failed_xids[xid_clean]

            # Checar cache válido
            if xid_clean in self._xid_to_id_cache:
                if now - self._xid_cache_time.get(xid_clean, 0) < self._XID_CACHE_TTL:
                    result[xid_clean] = self._xid_to_id_cache[xid_clean]
                    continue
                else:
                    del self._xid_to_id_cache[xid_clean]

            missing_xids.append(xid_clean)

        if missing_xids:
            try:
                datapoints = (
                    ScadaDataPoint.objects.using("scada")
                    .filter(xid__in=missing_xids)
                    .values("xid", "id")
                )
                found_xids = set()
                for dp in datapoints:
                    x_name = dp["xid"]
                    dp_id = dp["id"]
                    self._xid_to_id_cache[x_name] = dp_id
                    self._xid_cache_time[x_name] = now
                    result[x_name] = dp_id
                    found_xids.add(x_name)

                for m_xid in missing_xids:
                    if m_xid not in found_xids:
                        self._failed_xids[m_xid] = now
            except Exception as e:
                logger.warning(f"Falha ao consultar DataPoints no Scada-LTS: {type(e).__name__}")

        return result

    def normalize_value(self, data_type: int, raw_point_value: Optional[float], annotation=None) -> tuple[Any, str]:
        """
        Normaliza os tipos nativos do Scada-LTS:
        1: Binary (True / False)
        2: Multistate (int)
        3: Numeric (float / int)
        4: String (text_point_value_short / text_point_value_long)
        """
        if data_type == 1:  # Binary
            bool_val = (raw_point_value == 1.0) if raw_point_value is not None else False
            return bool_val, "1" if bool_val else "0"
        elif data_type == 2:  # Multistate
            int_val = int(raw_point_value) if raw_point_value is not None else 0
            return int_val, str(int_val)
        elif data_type == 3:  # Numeric
            if raw_point_value is None:
                return 0.0, "0"
            if raw_point_value.is_integer():
                return int(raw_point_value), str(int(raw_point_value))
            return round(raw_point_value, 2), f"{raw_point_value:.2f}"
        elif data_type == 4:  # String
            if annotation:
                text_val = annotation.text_point_value_short or annotation.text_point_value_long or ""
            else:
                text_val = ""
            return text_val, text_val
        else:
            str_val = str(raw_point_value) if raw_point_value is not None else ""
            return str_val, str_val

    def get_last_values_batch(self, xids: List[str]) -> Dict[str, Any]:
        """
        Retorna dicionário {xid: {'value': norm_val, 'str_value': str_val, 'ts': ts, 'data_type': dt}}
        para os XIDs solicitados em uma única query em lote.
        """
        now = time.time()
        xids_clean = [str(x).strip() for x in xids if x and str(x).strip()]
        result = {}
        xids_to_fetch = []

        for xid in xids_clean:
            if xid in self._value_cache:
                entry = self._value_cache[xid]
                if now - entry.get("_cached_at", 0) < self._VALUE_CACHE_TTL:
                    result[xid] = entry
                    continue
            xids_to_fetch.append(xid)

        if not xids_to_fetch:
            return result

        xid_to_dp_id = self.get_data_point_ids(xids_to_fetch)
        if not xid_to_dp_id:
            return result

        dp_id_to_xid = {dp_id: xid for xid, dp_id in xid_to_dp_id.items()}
        dp_ids = list(dp_id_to_xid.keys())

        try:
            latest_ts_records = (
                ScadaPointValue.objects.using("scada")
                .filter(data_point_id__in=dp_ids)
                .values("data_point_id")
                .annotate(max_ts=Max("ts"))
            )

            latest_map = {item["data_point_id"]: item["max_ts"] for item in latest_ts_records if item["max_ts"] is not None}

            if not latest_map:
                return result

            q_filter = Q()
            for dp_id, max_ts in latest_map.items():
                q_filter |= Q(data_point_id=dp_id, ts=max_ts)

            values_qs = (
                ScadaPointValue.objects.using("scada")
                .filter(q_filter)
                .select_related("annotation")
            )

            for pv in values_qs:
                xid = dp_id_to_xid.get(pv.data_point_id)
                if not xid:
                    continue

                annotation_obj = getattr(pv, "annotation", None)
                norm_val, str_val = self.normalize_value(pv.data_type, pv.point_value, annotation_obj)

                entry = {
                    "xid": xid,
                    "data_point_id": pv.data_point_id,
                    "data_type": pv.data_type,
                    "raw_point_value": pv.point_value,
                    "value": norm_val,
                    "str_value": str_val,
                    "ts": pv.ts,
                    "is_null": False,
                    "_cached_at": now,
                }
                self._value_cache[xid] = entry
                result[xid] = entry

        except Exception as e:
            logger.warning(f"Erro ao buscar últimos valores em lote no Scada-LTS: {type(e).__name__}")

        return result


scada_reader = ScadaReaderService()


CAVITY_REASON_MAP: Dict[int, str] = {
    0: "Normal",
    1: "Troca de Matriz",
    2: "Troca de Blader",
    3: "Troca de Anel Blader",
    4: "Troca Anel Center Post",
    5: "Ajuste Matriz",
    6: "Falta de Material",
    7: "Ajuste de Blader",
    8: "IA / Lixo",
    9: "Mecânico",
    10: "Elétrica",
    11: "Outros",
}

PRESS_REASON_MAP: Dict[int, str] = {
    0: "Normal",
    6: "Falta de Material",
    9: "Mecânico",
    10: "Elétrica",
    11: "Outros",
}


class ProductionStateService:
    """
    Serviço agregador e de persistência da máquina de estados do módulo de produção:
    - Carrega configurações de máquinas, cavidades, parâmetros e alarmes.
    - Consulta o Scada-LTS em lote de forma otimizada.
    - Mantém a máquina de estados (Produzindo, Parada, Sem comunicação, Dado desatualizado).
    - Persiste transições de estado de forma idempotente em ProductionMachineState e ProductionDowntimeEvent.
    """

    @classmethod
    def resolve_cavity_status_and_reason(
        cls, cav: ProductionCavityConfig, scada_values: Dict[str, Any]
    ) -> tuple[str, str, str, str]:
        """
        Retorna (status_code, status_label, badge_class, motivo_exibido) para a cavidade.
        - valor numérico 0: cavidade Normal (badge Normal, motivo_exibido = "")
        - valores numéricos de 1 a 11: cavidade Parada (badge Parada, motivo correspondente)
        - código numérico não mapeado != 0: "Motivo não mapeado — código X" (badge Parada)
        - valor nulo, indisponível, falha de leitura ou inválido: "Status da cavidade indisponível" (badge Indeterminado)
        """
        if not cav.xid_motivo_parada or not str(cav.xid_motivo_parada).strip():
            return "INDETERMINADO", "Indeterminado", "secondary", "Status da cavidade indisponível"

        motivo_entry = scada_values.get(cav.xid_motivo_parada)
        if not motivo_entry or motivo_entry.get("ts") is None:
            return "INDETERMINADO", "Indeterminado", "secondary", "Status da cavidade indisponível"

        raw_val = motivo_entry.get("value")
        if raw_val is None:
            raw_val_str = motivo_entry.get("str_value")
            if raw_val_str is None or str(raw_val_str).strip() == "":
                return "INDETERMINADO", "Indeterminado", "secondary", "Status da cavidade indisponível"
            raw_val = raw_val_str

        raw_str = str(raw_val).strip()
        if not raw_str:
            return "INDETERMINADO", "Indeterminado", "secondary", "Status da cavidade indisponível"

        try:
            code = int(float(raw_str))
        except (ValueError, TypeError):
            return "INDETERMINADO", "Indeterminado", "secondary", "Status da cavidade indisponível"

        if code == 0:
            return "NORMAL", "Normal", "success", ""
        elif code in CAVITY_REASON_MAP:
            return "PARADA", "Parada", "danger", CAVITY_REASON_MAP[code]
        else:
            return "PARADA", "Parada", "danger", f"Motivo não mapeado — código {code}"

    @classmethod
    def format_press_reason(cls, raw_val: Any, state: str) -> str:
        """
        Prensa:
        - se estiver Produzindo, não destacar motivo geral residual;
        - se estiver Parada e o motivo geral estiver entre 6, 9, 10 e 11, mostrar o texto correspondente;
        - se estiver Parada e o motivo for 0, vazio ou nulo, mostrar: "Motivo da prensa não informado";
        - código desconhecido: "Motivo não mapeado — código X".
        """
        if state == "PRODUZINDO":
            return ""

        if raw_val is None:
            return "Motivo da prensa não informado"

        raw_str = str(raw_val).strip()
        if not raw_str or raw_str.lower() in ("none", "null"):
            return "Motivo da prensa não informado"

        try:
            code = int(float(raw_str))
            if code == 0:
                return "Motivo da prensa não informado"
            elif code in PRESS_REASON_MAP:
                return PRESS_REASON_MAP[code]
            else:
                return f"Motivo não mapeado — código {code}"
        except (ValueError, TypeError):
            if raw_str == "0":
                return "Motivo da prensa não informado"
            return raw_str

    @staticmethod
    def format_elapsed_seconds(seconds: int) -> str:
        if seconds <= 0:
            return "0s"
        mins = seconds // 60
        hours = mins // 60
        days = hours // 24

        if days > 0:
            rem_hours = hours % 24
            return f"{days}d {rem_hours}h"
        elif hours > 0:
            rem_mins = mins % 60
            return f"{hours}h {rem_mins}m"
        elif mins > 0:
            rem_secs = seconds % 60
            return f"{mins}m {rem_secs}s"
        else:
            return f"{seconds}s"

    @staticmethod
    def format_elapsed_seconds_human(seconds: int, state: str) -> str:
        if seconds <= 0:
            mins_str = "0min"
        else:
            mins = seconds // 60
            hours = mins // 60
            rem_mins = mins % 60
            if hours > 0:
                mins_str = f"{hours:02d}h {rem_mins:02d}min"
            elif mins > 0:
                mins_str = f"{mins}min"
            else:
                mins_str = f"{seconds}s"

        if state == "PRODUZINDO":
            return f"Produzindo há {mins_str}"
        elif state == "PARADA":
            return f"Parada há {mins_str}"
        elif state == "SEM_COMUNICACAO":
            return "Sem comunicação"
        else:
            return mins_str

    @classmethod
    def format_elapsed_time(cls, timestamp_ms: Optional[int]) -> str:
        if not timestamp_ms:
            return "N/A"
        now_ms = int(time.time() * 1000)
        diff_secs = max(0, int((now_ms - timestamp_ms) / 1000))
        return cls.format_elapsed_seconds(diff_secs)

    @classmethod
    def calculate_loss_estimate(
        cls,
        cavity_config: ProductionCavityConfig,
        duracao_parada_segundos: int,
        produto: Optional[str] = None,
        matriz: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calcula a estimativa de perda de produção (pneus não fabricados) para uma cavidade e duração de parada.
        Utiliza fallback progressivo em 4 níveis:
          1. Cavidade + Produto + Matriz
          2. Cavidade + Produto
          3. Cavidade
          4. Máquina (Prensa)
        Exige amostragem mínima de 3 intervalos válidos (ou 45 minutos acumulados).
        Retorna dicionário com status de disponibilidade, perda_pneus, taxa_pneus_hora, qtd_amostras, nivel_fallback e texto_formatado.
        """
        duracao_parada_minutos = max(0, float(duracao_parada_segundos) / 60.0)
        
        levels = []
        if produto and matriz:
            levels.append((
                1,
                f"Média de {cavity_config.nome} com {produto} e Matriz {matriz}",
                Q(cavity_config=cavity_config, produto=produto, matriz=matriz)
            ))

        if produto:
            levels.append((
                2,
                f"Média de {cavity_config.nome} com {produto}",
                Q(cavity_config=cavity_config, produto=produto)
            ))

        levels.append((
            3,
            f"Média de {cavity_config.nome}",
            Q(cavity_config=cavity_config)
        ))

        levels.append((
            4,
            f"Média da máquina {cavity_config.machine_config.machine.nome}",
            Q(cavity_config__machine_config=cavity_config.machine_config)
        ))

        for level_num, level_label, q_filter in levels:
            records = list(ProductionRateAggregate.objects.filter(q_filter))
            total_samples = sum(r.quantidade_amostras for r in records)
            total_minutos = sum(r.minutos_produzindo for r in records)

            if total_samples >= 3 or total_minutos >= 45:
                total_prod = sum(r.quantidade_produzida for r in records)
                if total_minutos > 0:
                    taxa_pneus_hora = (float(total_prod) / (float(total_minutos) / 60.0))
                    perda_pneus = int(round((duracao_parada_minutos / 60.0) * taxa_pneus_hora))
                    taxa_fmt = round(taxa_pneus_hora, 1)

                    return {
                        "disponivel": True,
                        "perda_pneus": perda_pneus,
                        "taxa_pneus_hora": taxa_fmt,
                        "qtd_amostras": total_samples,
                        "nivel_fallback": level_num,
                        "nivel_label": level_label,
                        "texto_formatado": f"Perda estimada: aproximadamente {perda_pneus} pneus (Base: média de {taxa_fmt} pneus/hora em {total_samples} intervalos válidos)",
                    }

        return {
            "disponivel": False,
            "perda_pneus": None,
            "taxa_pneus_hora": None,
            "qtd_amostras": 0,
            "nivel_fallback": None,
            "nivel_label": "",
            "texto_formatado": "Estimativa indisponível — ainda não existem dados suficientes para uma média confiável.",
        }

    @classmethod
    def purge_old_rate_aggregates(cls, days: int = 90) -> int:
        """Purga agregados de taxa de produção com mais de `days` dias no banco default."""
        limit_dt = timezone.now() - timezone.timedelta(days=days)
        deleted_count, _ = ProductionRateAggregate.objects.filter(inicio_intervalo__lt=limit_dt).delete()
        return deleted_count

    @classmethod
    def build_cavities_data(
        cls,
        config: ProductionMachineConfig,
        scada_values: Dict[str, Any],
        shift_info: Optional[Dict[str, Any]] = None
    ) -> tuple[List[Dict[str, Any]], int, int, int, int]:
        if shift_info is None:
            shift_info = get_active_shift()

        cavities_list = []
        total_prod = 0
        total_meta = 0

        effective_percent = shift_info.get("effective_percent", 100.0) if shift_info else 100.0
        has_shifts = shift_info.get("has_shifts", False) if shift_info else False

        for cav in config.cavities.all():
            # Produção atual
            c_prod_entry = scada_values.get(cav.xid_producao) if cav.xid_producao else None
            c_prod = int(c_prod_entry["value"]) if c_prod_entry and isinstance(c_prod_entry.get("value"), (int, float)) else 0

            # Limite de Produção do Bladder (Scada - xid_meta)
            limite_entry = scada_values.get(cav.xid_meta) if cav.xid_meta else None
            limite_bladder_scada = None
            if limite_entry and isinstance(limite_entry.get("value"), (int, float)):
                limite_bladder_scada = int(limite_entry["value"])
            elif limite_entry and limite_entry.get("str_value") and str(limite_entry["str_value"]).isdigit():
                limite_bladder_scada = int(limite_entry["str_value"])

            limite_bladder_str = str(limite_bladder_scada) if limite_bladder_scada is not None else "N/A"

            # Matriz
            matriz_entry = scada_values.get(cav.xid_matriz) if cav.xid_matriz else None
            matriz_val = str(matriz_entry.get("str_value", "")).strip() if matriz_entry else ""

            # Produto e Lote do Bladder
            prod_entry = scada_values.get(cav.xid_produto) if cav.xid_produto else None
            prod_val = str(prod_entry.get("str_value", "")).strip() if prod_entry else ""

            lote_entry = scada_values.get(cav.xid_lote_bladder) if cav.xid_lote_bladder else None
            lote_val = str(lote_entry.get("str_value", "")).strip() if lote_entry else ""

            # Resolução de Meta (PCP Target Ativo vs Fallback Legado)
            s_obj = shift_info.get("shift_obj") if shift_info else None
            mat_catalog = None
            if matriz_val and matriz_val != "Não informada":
                mat_catalog = ProductionMatrixCatalog.objects.filter(
                    Q(codigo__iexact=matriz_val) |
                    Q(nome_scada__iexact=matriz_val) |
                    Q(nome_exibicao__iexact=matriz_val) |
                    Q(produto__iexact=matriz_val)
                ).first()

            pcp_info = PCPCalculationService.resolve_pcp_target_for_cavity(
                cavity=cav,
                machine_config=config,
                mat_catalog=mat_catalog,
                matriz_val=matriz_val,
                shift_obj=s_obj
            )

            if pcp_info["is_pcp"]:
                c_meta_turno = pcp_info["meta_turno"]
                c_meta_diaria = pcp_info["meta_turno"]
                is_pcp = True
                pcp_divergencia = pcp_info.get("pcp_divergencia")
            else:
                is_pcp = False
                pcp_divergencia = None
                target_obj = None
                if matriz_val:
                    target_obj = ProductionTarget.objects.filter(
                        date=timezone.now().date(),
                        status="ATIVO",
                        matriz_codigo__iexact=matriz_val
                    ).filter(
                        Q(shift=s_obj) | Q(shift__isnull=True)
                    ).order_by("-shift_id").first()

                if target_obj:
                    c_meta_turno = target_obj.planned_quantity
                    c_meta_diaria = target_obj.planned_quantity
                else:
                    c_meta_diaria = cav.meta_producao_manual or 0
                    if has_shifts:
                        c_meta_turno = round(c_meta_diaria * (effective_percent / 100.0))
                    else:
                        c_meta_turno = c_meta_diaria

            if has_shifts and s_obj:
                acc_rec = ProductionShiftAccumulated.objects.filter(
                    date=timezone.now().date(),
                    shift=s_obj,
                    cavity_config=cav
                ).first()
                c_prod_turno = acc_rec.quantity_accumulated if acc_rec else c_prod
            else:
                c_prod_turno = c_prod

            diferenca_meta_turno = c_prod_turno - c_meta_turno
            diferenca_meta_turno_str = f"+{diferenca_meta_turno}" if diferenca_meta_turno > 0 else str(diferenca_meta_turno)

            total_prod += c_prod
            total_meta += c_meta_diaria

            percent = round((c_prod / c_meta_diaria) * 100) if c_meta_diaria > 0 else 0
            percent_bar = min(100, max(0, percent)) if c_meta_diaria > 0 else 0

            percent_turno = round((c_prod_turno / c_meta_turno) * 100) if c_meta_turno > 0 else 0
            percent_turno_bar = min(100, max(0, percent_turno)) if c_meta_turno > 0 else 0

            # Regras de composição para matriz/produto e lote do bladder:
            bladder_lot_info = compose_bladder_lot(prod_val, lote_val)
            mat_info = resolve_matrix_product_display(matriz_val)

            if mat_info["matrix_identified"]:
                model_name = mat_info["display"]
                if bladder_lot_info["status"] != "AUSENTE":
                    produto_lote_str = f"{model_name} | Lote: {bladder_lot_info['display']}"
                else:
                    produto_lote_str = model_name
            else:
                if bladder_lot_info["status"] != "AUSENTE":
                    produto_lote_str = f"Lote: {bladder_lot_info['display']}"
                else:
                    produto_lote_str = "Não informado"

            # Status e motivo da cavidade inferidos via SPEC 05C
            c_status_code, c_status_label, c_badge_class, c_motivo_exibido = cls.resolve_cavity_status_and_reason(cav, scada_values)

            cav_state_obj = getattr(cav, "state", None)
            dur_parada_secs = 0
            if cav_state_obj and cav_state_obj.estado_atual == "PARADA" and cav_state_obj.inicio_estado_atual:
                dur_parada_secs = max(0, int((timezone.now() - cav_state_obj.inicio_estado_atual).total_seconds()))

            perda_est = cls.calculate_loss_estimate(cav, dur_parada_secs, prod_val, matriz_val)

            cavities_list.append({
                "id": cav.id,
                "nome": cav.nome,
                "ordem": cav.ordem,
                "status_code": c_status_code,
                "status_label": c_status_label,
                "badge_class": c_badge_class,
                "matriz": matriz_val if matriz_val else "Não informada",
                "matriz_nome": mat_info["display"],
                "lote_display": bladder_lot_info["display"],
                "produto_val": prod_val,
                "lote_val": lote_val,
                "produto_lote_str": produto_lote_str,
                "producao": c_prod,
                "meta": c_meta_diaria,
                "meta_diaria": c_meta_diaria,
                "meta_turno": c_meta_turno,
                "is_pcp": is_pcp,
                "pcp_divergencia": pcp_divergencia,
                "producao_turno": c_prod_turno,
                "diferenca_meta_turno": diferenca_meta_turno,
                "diferenca_meta_turno_str": diferenca_meta_turno_str,
                "percentual": percent,
                "percentual_bar": percent_bar,
                "percentual_turno": percent_turno,
                "percentual_turno_bar": percent_turno_bar,
                "limite_bladder_scada": limite_bladder_scada,
                "limite_bladder_str": limite_bladder_str,
                "contador_ciclo_scada": c_prod,
                "producao_acumulada_turno": c_prod_turno,
                "motivo_parada": c_motivo_exibido,
                "perda_estimada": perda_est,
            })

        total_percent = round((total_prod / total_meta) * 100) if total_meta > 0 else 0
        total_percent_bar = min(100, max(0, total_percent)) if total_meta > 0 else 0

        return cavities_list, total_prod, total_meta, total_percent, total_percent_bar

    @classmethod
    def process_incremental_production(cls, cav: ProductionCavityConfig, scada_values: Dict[str, Any], now=None):
        """
        Processa o acúmulo incremental de produção por cavidade e turno com suporte a resets e trocas de matriz/bladder.
        Garante idempotência contra timestamp duplicado/releitura.
        """
        if now is None:
            now = timezone.now()

        if not cav.xid_producao:
            return

        prod_entry = scada_values.get(cav.xid_producao)
        if not prod_entry:
            return

        raw_val = prod_entry.get("value")
        if raw_val is None or not isinstance(raw_val, (int, float)):
            return

        c_prod = int(raw_val)
        ts_ms = prod_entry.get("timestamp") or int(now.timestamp() * 1000)

        mat_entry = scada_values.get(cav.xid_matriz) if cav.xid_matriz else None
        mat_val = str(mat_entry.get("str_value", mat_entry.get("value", ""))).strip() if mat_entry else ""

        prod_spec_entry = scada_values.get(cav.xid_produto) if cav.xid_produto else None
        prod_val = str(prod_spec_entry.get("str_value", prod_spec_entry.get("value", ""))).strip() if prod_spec_entry else ""

        lote_entry = scada_values.get(cav.xid_lote_bladder) if cav.xid_lote_bladder else None
        lote_val = str(lote_entry.get("str_value", lote_entry.get("value", ""))).strip() if lote_entry else ""

        shift_info = get_active_shift(now)
        shift_obj = shift_info.get("shift_obj") if shift_info else None
        if not shift_obj:
            shift_obj = ProductionShift.objects.filter(ativo=True).order_by("ordem_exibicao").first()
        if not shift_obj:
            return

        today_date = now.date()

        accumulated, _ = ProductionShiftAccumulated.objects.get_or_create(
            date=today_date,
            shift=shift_obj,
            cavity_config=cav,
            defaults={
                "matriz": mat_val,
                "produto": prod_val,
                "quantity_accumulated": 0,
                "last_scada_counter": c_prod,
                "last_scada_ts": ts_ms,
            }
        )

        # Checagem de idempotência: se o timestamp Scada já foi processado ou for antigo, ignora incremento
        if accumulated.last_scada_ts and ts_ms <= accumulated.last_scada_ts and accumulated.quantity_accumulated > 0:
            return

        active_cycle = ProductionCycle.objects.filter(
            cavity_config=cav, ended_at__isnull=True
        ).order_by("-started_at").first()

        last_counter = accumulated.last_scada_counter

        # Detecção de Reset ou Troca de Insumos (Matriz / Bladder)
        is_counter_reset = (c_prod < last_counter)
        is_matrix_changed = bool(active_cycle and active_cycle.matriz and mat_val and mat_val != active_cycle.matriz)
        is_bladder_changed = bool(
            active_cycle and (
                (active_cycle.lote_bladder and lote_val and lote_val != active_cycle.lote_bladder) or
                (active_cycle.produto and prod_val and prod_val != active_cycle.produto)
            )
        )

        if is_counter_reset:
            increment = c_prod
        else:
            increment = max(0, c_prod - last_counter)

        if is_counter_reset or is_matrix_changed or is_bladder_changed:
            close_reason = "TROCA_MATRIZ" if is_matrix_changed else ("TROCA_BLADDER" if is_bladder_changed else "RESET_CONTADOR")
            if active_cycle:
                active_cycle.ended_at = now
                active_cycle.final_counter = last_counter
                active_cycle.close_reason = close_reason
                active_cycle.save()

            active_cycle = ProductionCycle.objects.create(
                cavity_config=cav,
                matriz=mat_val,
                produto=prod_val,
                lote_bladder=lote_val,
                started_at=now,
                initial_counter=c_prod,
                quantity_produced=0,
                last_scada_ts=ts_ms
            )

            # Acumulado no turno: preserva o valor acumulado anterior no turno e adiciona os pneus pós-reset
            accumulated.quantity_accumulated += c_prod
        else:
            if not active_cycle:
                active_cycle = ProductionCycle.objects.create(
                    cavity_config=cav,
                    matriz=mat_val,
                    produto=prod_val,
                    lote_bladder=lote_val,
                    started_at=now,
                    initial_counter=c_prod,
                    quantity_produced=0,
                    last_scada_ts=ts_ms
                )
                accumulated.quantity_accumulated += c_prod
            else:
                if increment > 0:
                    active_cycle.quantity_produced += increment
                    active_cycle.last_scada_ts = ts_ms
                    active_cycle.save(update_fields=["quantity_produced", "last_scada_ts", "updated_at"])

                    accumulated.quantity_accumulated += increment

        accumulated.matriz = mat_val
        accumulated.produto = prod_val
        accumulated.last_scada_counter = c_prod
        accumulated.last_scada_ts = ts_ms
        accumulated.save()

        # Rastreabilidade e Vida Útil do Bladder (SPEC 01)
        cls.process_bladder_tracking(
            cav=cav,
            scada_values=scada_values,
            c_prod=c_prod,
            increment=increment,
            is_counter_reset=is_counter_reset,
            ts_ms=ts_ms,
            now=now
        )

        # Validação Automática de Setup e Auditoria de Divergência (SPEC 03)
        cls.process_bladder_setup_validation(
            cav=cav,
            scada_values=scada_values,
            increment=increment,
            now=now
        )

    @classmethod
    def process_bladder_tracking(
        cls,
        cav: ProductionCavityConfig,
        scada_values: Dict[str, Any],
        c_prod: int,
        increment: int,
        is_counter_reset: bool,
        ts_ms: Optional[int] = None,
        now: Optional[datetime] = None
    ) -> Optional[ProductionBladderUsage]:
        """
        Gerencia o ciclo de vida físico e a contagem de passadas de cada utilização de bladder
        (ProductionBladderUsage) por cavidade de forma idempotente, transacional e resistente a resets.
        """
        if now is None:
            now = timezone.now()
        now_ts = now.timestamp()

        raw_bla = ""
        if cav.xid_bla_real:
            bla_entry = scada_values.get(cav.xid_bla_real)
            if bla_entry:
                raw_bla = str(bla_entry.get("str_value", bla_entry.get("value", ""))).strip()

        norm_bla = normalize_bladder_code(raw_bla)

        prod_entry = scada_values.get(cav.xid_produto) if cav.xid_produto else None
        prod_val = str(prod_entry.get("str_value", prod_entry.get("value", ""))).strip() if prod_entry else ""

        lote_entry = scada_values.get(cav.xid_lote_bladder) if cav.xid_lote_bladder else None
        lote_val = str(lote_entry.get("str_value", lote_entry.get("value", ""))).strip() if lote_entry else ""

        lot_info = compose_bladder_lot(prod_val, lote_val)

        # Captura e buffer do motivo da troca
        if cav.xid_motivo_troca_bladder:
            mot_entry = scada_values.get(cav.xid_motivo_troca_bladder)
            if mot_entry:
                raw_mot = str(mot_entry.get("str_value", mot_entry.get("value", ""))).strip()
                try:
                    mot_code = int(float(raw_mot))
                    if 1 <= mot_code <= 8:
                        _pending_bladder_reasons[cav.id] = {
                            "code": mot_code,
                            "raw": raw_mot,
                            "timestamp": now_ts,
                        }
                except (ValueError, TypeError):
                    pass

        limite_entry = scada_values.get(cav.xid_meta) if cav.xid_meta else None
        limite_val = None
        if limite_entry and isinstance(limite_entry.get("value"), (int, float)):
            limite_val = int(limite_entry["value"])
        elif limite_entry and limite_entry.get("str_value") and str(limite_entry["str_value"]).isdigit():
            limite_val = int(limite_entry["str_value"])

        active_usage = ProductionBladderUsage.objects.filter(
            cavity_config=cav, status="EM_USO", ended_at__isnull=True
        ).order_by("-started_at").first()

        is_complete_identity = bool(norm_bla and lot_info["is_complete"])

        if is_complete_identity:
            p_name = cav.machine_config.machine.nome if cav.machine_config and cav.machine_config.machine else ""
            c_name = cav.nome

            if not active_usage:
                active_usage = ProductionBladderUsage.objects.create(
                    cavity_config=cav,
                    machine_name_snapshot=p_name,
                    cavity_name_snapshot=c_name,
                    codigo_bla_real=norm_bla,
                    raw_bla_value=raw_bla,
                    lote_prefixo=lot_info["prefix"],
                    lote_numero=lot_info["number"],
                    lote_completo_snapshot=lot_info["display"],
                    started_at=now,
                    timestamp_scada_inicio=ts_ms,
                    passadas_acumuladas=0,
                    limite_vida_snapshot=limite_val,
                    status="EM_USO",
                    last_scada_counter=c_prod,
                    last_scada_ts=ts_ms,
                )
            else:
                is_changed = (
                    active_usage.codigo_bla_real != norm_bla or
                    active_usage.lote_prefixo != lot_info["prefix"] or
                    active_usage.lote_numero != lot_info["number"]
                )
                if is_changed:
                    # Encerra o active_usage anterior
                    reason_info = _pending_bladder_reasons.pop(cav.id, None)
                    reason_code = ProductionBladderChangeReason.NENHUM
                    reason_raw = ""
                    if reason_info and (now_ts - reason_info.get("timestamp", 0) <= BLADDER_REASON_WINDOW_SECONDS):
                        reason_code = reason_info.get("code", ProductionBladderChangeReason.NENHUM)
                        reason_raw = reason_info.get("raw", "")

                    active_usage.ended_at = now
                    active_usage.timestamp_scada_fim = ts_ms
                    active_usage.status = "FINALIZADO"
                    active_usage.motivo_troca = reason_code
                    active_usage.motivo_troca_raw = reason_raw
                    active_usage.save()

                    # Abre novo segmento de utilização para o novo bladder
                    active_usage = ProductionBladderUsage.objects.create(
                        cavity_config=cav,
                        machine_name_snapshot=p_name,
                        cavity_name_snapshot=c_name,
                        codigo_bla_real=norm_bla,
                        raw_bla_value=raw_bla,
                        lote_prefixo=lot_info["prefix"],
                        lote_numero=lot_info["number"],
                        lote_completo_snapshot=lot_info["display"],
                        started_at=now,
                        timestamp_scada_inicio=ts_ms,
                        passadas_acumuladas=0,
                        limite_vida_snapshot=limite_val,
                        status="EM_USO",
                        last_scada_counter=c_prod,
                        last_scada_ts=ts_ms,
                    )
                else:
                    # Mesma identidade: incrementa passadas
                    if increment > 0:
                        active_usage.passadas_acumuladas += increment
                    active_usage.last_scada_counter = c_prod
                    active_usage.last_scada_ts = ts_ms
                    if limite_val is not None and not active_usage.limite_vida_snapshot:
                        active_usage.limite_vida_snapshot = limite_val
                    active_usage.save(update_fields=[
                        "passadas_acumuladas", "last_scada_counter", "last_scada_ts", "limite_vida_snapshot", "updated_at"
                    ])
        else:
            # Identidade incompleta: se já houver active_usage, não encerra; apenas acumula passadas
            if active_usage and increment > 0:
                active_usage.passadas_acumuladas += increment
                active_usage.last_scada_counter = c_prod
                active_usage.last_scada_ts = ts_ms
                active_usage.save(update_fields=["passadas_acumuladas", "last_scada_counter", "last_scada_ts", "updated_at"])

        return active_usage

    @classmethod
    def process_bladder_setup_validation(
        cls,
        cav: ProductionCavityConfig,
        scada_values: Dict[str, Any],
        increment: int,
        now: Optional[datetime] = None
    ) -> Optional[ProductionBladderSetupMismatchEvent]:
        """
        Valida a compatibilidade física entre a Matriz instalada e o Bladder real em operação na cavidade.
        Utiliza motor de estabilização contra falsos positivos transitórios (3 ciclos consecutivos).
        Registra e audita ProductionBladderSetupMismatchEvent contabilizando passadas produzidas sob divergência.
        """
        if now is None:
            now = timezone.now()

        raw_mat = ""
        if cav.xid_matriz:
            mat_entry = scada_values.get(cav.xid_matriz)
            if mat_entry:
                raw_mat = str(mat_entry.get("str_value", mat_entry.get("value", ""))).strip()

        raw_bla = ""
        if cav.xid_bla_real:
            bla_entry = scada_values.get(cav.xid_bla_real)
            if bla_entry:
                raw_bla = str(bla_entry.get("str_value", bla_entry.get("value", ""))).strip()

        prod_entry = scada_values.get(cav.xid_produto) if cav.xid_produto else None
        prod_val = str(prod_entry.get("str_value", prod_entry.get("value", ""))).strip() if prod_entry else ""

        lote_entry = scada_values.get(cav.xid_lote_bladder) if cav.xid_lote_bladder else None
        lote_val = str(lote_entry.get("str_value", lote_entry.get("value", ""))).strip() if lote_entry else ""

        lot_info = compose_bladder_lot(prod_val, lote_val)

        norm_bla = normalize_bladder_code(raw_bla)
        mat_info = resolve_matrix_product_display(raw_mat)
        expected_bladders = get_expected_bladders_for_matrix(raw_mat)

        # Avaliação de incompatibilidade
        is_mismatch = False
        if mat_info["matrix_identified"] and expected_bladders and norm_bla:
            if norm_bla not in expected_bladders:
                is_mismatch = True

        open_event = ProductionBladderSetupMismatchEvent.objects.filter(
            cavity_config=cav, status="EM_ABERTO", ended_at__isnull=True
        ).order_by("-started_at").first()

        current_count = _setup_divergence_counter.get(cav.id, 0)

        if is_mismatch:
            _setup_divergence_counter[cav.id] = current_count + 1

            # Abertura após estabilização (3 ciclos)
            if _setup_divergence_counter[cav.id] >= 3:
                p_name = cav.machine_config.machine.nome if cav.machine_config and cav.machine_config.machine else ""
                c_name = cav.nome
                mat_name = mat_info["display"]
                exp_str = ", ".join(expected_bladders)

                if not open_event:
                    open_event = ProductionBladderSetupMismatchEvent.objects.create(
                        cavity_config=cav,
                        machine_name_snapshot=p_name,
                        cavity_name_snapshot=c_name,
                        matriz_instalada_raw=raw_mat,
                        matriz_nome_snapshot=mat_name,
                        codigo_bla_instalado=norm_bla,
                        lote_bladder_snapshot=lot_info["display"],
                        bladders_esperados_snapshot=exp_str,
                        started_at=now,
                        passadas_produzidas_em_divergencia=increment if increment > 0 else 0,
                        status="EM_ABERTO",
                    )
                else:
                    # Acumula passadas produzidas sob divergência
                    if increment > 0:
                        open_event.passadas_produzidas_em_divergencia += increment
                        open_event.save(update_fields=["passadas_produzidas_em_divergencia", "updated_at"])
        else:
            _setup_divergence_counter[cav.id] = 0

            # Se houver evento em aberto e a divergência cessou, finaliza o evento
            if open_event:
                dur = max(0, int((now - open_event.started_at).total_seconds()))
                open_event.ended_at = now
                open_event.duracao_segundos = dur
                open_event.status = "FINALIZADO"
                open_event.resolvido_por = "SETUP_CORRIGIDO"
                open_event.save()

        return open_event

    @classmethod
    @transaction.atomic
    def process_scada_cycle(cls, scada_values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executa um ciclo completo da máquina de estados para todas as máquinas configuradas.
        Garante persistência idempotente no banco default.
        """
        configs = list(
            ProductionMachineConfig.objects.select_related("machine", "machine__setor")
            .prefetch_related("cavities")
            .order_by("ordem_exibicao", "machine__nome")
        )

        if scada_values is None:
            all_xids = set()
            for cfg in configs:
                if cfg.xid_status_prensa:
                    all_xids.add(cfg.xid_status_prensa)
                if cfg.xid_abertura:
                    all_xids.add(cfg.xid_abertura)
                if cfg.xid_motivo_parada_geral:
                    all_xids.add(cfg.xid_motivo_parada_geral)
                for cav in cfg.cavities.all():
                    if cav.xid_matriz:
                        all_xids.add(cav.xid_matriz)
                    if cav.xid_produto:
                        all_xids.add(cav.xid_produto)
                    if cav.xid_lote_bladder:
                        all_xids.add(cav.xid_lote_bladder)
                    if cav.xid_producao:
                        all_xids.add(cav.xid_producao)
                    if cav.xid_meta:
                        all_xids.add(cav.xid_meta)
                    if cav.xid_motivo_parada:
                        all_xids.add(cav.xid_motivo_parada)
                    if cav.xid_bla_real:
                        all_xids.add(cav.xid_bla_real)
                    if cav.xid_motivo_troca_bladder:
                        all_xids.add(cav.xid_motivo_troca_bladder)
            for p_cfg in ProductionParameterConfig.objects.filter(ativo=True):
                if p_cfg.xid:
                    all_xids.add(p_cfg.xid)
            scada_values = scada_reader.get_last_values_batch(list(all_xids))

        now = timezone.now()
        now_ms = int(time.time() * 1000)

        for cfg in configs:
            state_obj, _ = ProductionMachineState.objects.get_or_create(machine_config=cfg)

            status_entry = scada_values.get(cfg.xid_status_prensa) if cfg.xid_status_prensa else None
            motivo_entry = scada_values.get(cfg.xid_motivo_parada_geral) if cfg.xid_motivo_parada_geral else None
            motivo_str = str(motivo_entry.get("str_value", "")) if motivo_entry else ""

            # Caso 1: Sem comunicação / Scada offline ou XID de status sem leitura
            if not status_entry or status_entry.get("ts") is None:
                state_obj.sem_comunicacao = True
                state_obj.dado_desatualizado = False
                state_obj.save()
                is_stale = False
                is_producing = False
                raw_val = ""
                scada_dt = now
                ts_ms = None
            else:
                ts_ms = status_entry["ts"]
                age_seconds = (now_ms - ts_ms) / 1000.0
                is_stale = (age_seconds > cfg.stale_limit_seconds)
                scada_dt = timezone.datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
                raw_val = str(status_entry.get("str_value", status_entry.get("value", ""))).strip().lower()
                target_val = str(cfg.produzindo_value).strip().lower()
                is_producing = (raw_val == target_val)

                # Caso 2: Dado Desatualizado (Stale) -> Preservar estado industrial sem abrir/fechar eventos de parada
                if is_stale:
                    state_obj.sem_comunicacao = False
                    state_obj.dado_desatualizado = True
                    state_obj.ultima_leitura_scada = scada_dt
                    state_obj.ultimo_timestamp_scada = ts_ms
                    state_obj.ultimo_valor_status = raw_val
                    state_obj.save()
                else:
                    # Caso 3: Comunicação OK e Dado Atualizado
                    state_obj.sem_comunicacao = False
                    state_obj.dado_desatualizado = False
                    state_obj.ultima_leitura_scada = scada_dt
                    state_obj.ultimo_timestamp_scada = ts_ms
                    state_obj.ultimo_valor_status = raw_val
                    state_obj.motivo_atual = motivo_str

                    open_event = ProductionDowntimeEvent.objects.filter(
                        machine_config=cfg, fim__isnull=True
                    ).order_by("-inicio").first()

                    if not is_producing:
                        # Máquina Parada
                        if open_event:
                            if motivo_str and open_event.motivo_geral != motivo_str:
                                open_event.motivo_geral = motivo_str
                                open_event.save(update_fields=["motivo_geral", "updated_at"])
                            if state_obj.estado_atual != "PARADA":
                                state_obj.estado_atual = "PARADA"
                                state_obj.inicio_estado_atual = open_event.inicio
                        else:
                            event_start = scada_dt
                            open_event = ProductionDowntimeEvent.objects.create(
                                machine_config=cfg,
                                inicio=event_start,
                                motivo_geral=motivo_str,
                                snapshot_valor_status=raw_val,
                                timestamp_inicial_scada=ts_ms,
                                origem="SCADA"
                            )
                            state_obj.estado_atual = "PARADA"
                            state_obj.inicio_estado_atual = event_start
                    else:
                        # Máquina Produzindo
                        if open_event:
                            event_end = scada_dt
                            duration = max(0, int((event_end - open_event.inicio).total_seconds()))
                            open_event.fim = event_end
                            open_event.duracao_segundos = duration
                            open_event.timestamp_final_scada = ts_ms
                            open_event.save()

                            state_obj.estado_atual = "PRODUZINDO"
                            state_obj.inicio_estado_atual = event_end
                            state_obj.motivo_atual = ""
                        else:
                            if state_obj.estado_atual != "PRODUZINDO" or not state_obj.inicio_estado_atual:
                                state_obj.estado_atual = "PRODUZINDO"
                                state_obj.inicio_estado_atual = scada_dt
                                state_obj.motivo_atual = ""

                    state_obj.save()

            # Atualizar intervalos operacionais da prensa (ProductionMachineStateInterval)
            if state_obj.sem_comunicacao or state_obj.dado_desatualizado:
                target_interval_state = "SEM_COMUNICACAO"
            elif is_producing:
                target_interval_state = "PRODUZINDO"
            else:
                target_interval_state = "PARADA"

            open_interval = ProductionMachineStateInterval.objects.filter(
                machine_config=cfg, ended_at__isnull=True
            ).order_by("-started_at").first()

            if open_interval:
                if open_interval.state != target_interval_state:
                    open_interval.ended_at = now
                    open_interval.save(update_fields=["ended_at", "updated_at"])
                    ProductionMachineStateInterval.objects.create(
                        machine_config=cfg,
                        state=target_interval_state,
                        started_at=now,
                        status_raw_value=raw_val
                    )
            else:
                ProductionMachineStateInterval.objects.create(
                    machine_config=cfg,
                    state=target_interval_state,
                    started_at=now,
                    status_raw_value=raw_val
                )

            # Atualizar máquina de estados e histórico de matrizes por cavidade
            for cav in cfg.cavities.all():
                cav_state_obj, _ = ProductionCavityState.objects.get_or_create(cavity_config=cav)

                # Se o dado estiver desatualizado (stale) ou sem comunicação, congela o estado da cavidade
                if not (state_obj.sem_comunicacao or state_obj.dado_desatualizado):
                    c_code, c_label, c_badge, c_motivo = cls.resolve_cavity_status_and_reason(cav, scada_values)
                    motivo_entry = scada_values.get(cav.xid_motivo_parada) if cav.xid_motivo_parada else None
                    raw_motivo = str(motivo_entry.get("str_value", motivo_entry.get("value", ""))) if motivo_entry else ""

                    open_cav_event = ProductionCavityDowntimeEvent.objects.filter(
                        cavity_config=cav, fim__isnull=True
                    ).order_by("-inicio").first()

                    if c_code == "PARADA":
                        if open_cav_event:
                            if c_motivo and open_cav_event.motivo_parada != c_motivo:
                                open_cav_event.motivo_parada = c_motivo
                                open_cav_event.save(update_fields=["motivo_parada", "updated_at"])
                            if cav_state_obj.estado_atual != "PARADA":
                                cav_state_obj.estado_atual = "PARADA"
                                cav_state_obj.inicio_estado_atual = open_cav_event.inicio
                                cav_state_obj.ultimo_motivo = c_motivo
                                cav_state_obj.save()
                        else:
                            open_cav_event = ProductionCavityDowntimeEvent.objects.create(
                                cavity_config=cav,
                                inicio=now,
                                motivo_parada=c_motivo or "Parada de Cavidade",
                                snapshot_valor_motivo=raw_motivo,
                                timestamp_inicial_scada=ts_ms,
                                origem="SCADA"
                            )
                            cav_state_obj.estado_atual = "PARADA"
                            cav_state_obj.inicio_estado_atual = now
                            cav_state_obj.ultimo_motivo = c_motivo
                            cav_state_obj.save()
                    else:
                        if open_cav_event:
                            duration = max(0, int((now - open_cav_event.inicio).total_seconds()))
                            open_cav_event.fim = now
                            open_cav_event.duracao_segundos = duration
                            open_cav_event.timestamp_final_scada = ts_ms
                            open_cav_event.save()

                            cav_state_obj.estado_atual = "NORMAL"
                            cav_state_obj.inicio_estado_atual = now
                            cav_state_obj.ultimo_motivo = ""
                            cav_state_obj.save()
                        else:
                            if cav_state_obj.estado_atual != "NORMAL" or not cav_state_obj.inicio_estado_atual:
                                cav_state_obj.estado_atual = "NORMAL"
                                cav_state_obj.inicio_estado_atual = now
                                cav_state_obj.ultimo_motivo = ""
                                cav_state_obj.save()

                mat_entry = scada_values.get(cav.xid_matriz) if cav.xid_matriz else None
                raw_mat = mat_entry.get("str_value", mat_entry.get("value")) if mat_entry else None
                norm_mat = normalize_matrix_value(raw_mat)

                if norm_mat:
                    open_history = ProductionCavityMatrixHistory.objects.filter(
                        cavity_config=cav, ended_at__isnull=True
                    ).order_by("-started_at").first()

                    if open_history:
                        if open_history.matrix_value != norm_mat:
                            open_history.ended_at = now
                            open_history.save(update_fields=["ended_at", "updated_at"])
                            ProductionCavityMatrixHistory.objects.create(
                                cavity_config=cav,
                                matrix_value=norm_mat,
                                started_at=now
                            )
                    else:
                        ProductionCavityMatrixHistory.objects.create(
                            cavity_config=cav,
                            matrix_value=norm_mat,
                            started_at=now
                        )

                # Processar acúmulo incremental e detecção de resets conforme SPEC 07B
                cls.process_incremental_production(cav, scada_values, now=now)

        # Avaliação de anomalias de parâmetros de processo (ProductionParameterConfig / ProductionParameterAnomalyEvent)
        for p_cfg in ProductionParameterConfig.objects.filter(ativo=True).select_related("machine_config", "cavity_config"):
            m_cfg = p_cfg.machine_config or (p_cfg.cavity_config.machine_config if p_cfg.cavity_config else None)
            if not m_cfg:
                continue

            m_state = getattr(m_cfg, "state", None) or ProductionMachineState.objects.filter(machine_config=m_cfg).first()
            if not m_state or m_state.sem_comunicacao or m_state.dado_desatualizado:
                # Congela a anomalia em estado desatualizado/sem comunicação
                continue

            p_entry = scada_values.get(p_cfg.xid) if p_cfg.xid else None
            if not p_entry:
                continue

            raw_p_val = p_entry.get("value")
            if raw_p_val is None:
                continue

            try:
                p_val = float(raw_p_val)
            except (ValueError, TypeError):
                continue

            min_violated = (p_cfg.limite_minimo is not None and p_val < p_cfg.limite_minimo)
            max_violated = (p_cfg.limite_maximo is not None and p_val > p_cfg.limite_maximo)

            open_anomaly = ProductionParameterAnomalyEvent.objects.filter(
                parameter_config=p_cfg,
                fim__isnull=True
            ).order_by("-inicio").first()

            if open_anomaly:
                open_anomaly.menor_valor = min(open_anomaly.menor_valor, p_val)
                open_anomaly.maior_valor = max(open_anomaly.maior_valor, p_val)
                open_anomaly.ultimo_valor = p_val

                should_close = False
                if open_anomaly.tipo_limite == "MINIMO":
                    close_thresh = (p_cfg.limite_minimo or 0.0) + (p_cfg.histerese or 0.0)
                    if p_val >= close_thresh:
                        should_close = True
                elif open_anomaly.tipo_limite == "MAXIMO":
                    close_thresh = (p_cfg.limite_maximo or 0.0) - (p_cfg.histerese or 0.0)
                    if p_val <= close_thresh:
                        should_close = True

                if should_close:
                    dur = max(0, int((now - open_anomaly.inicio).total_seconds()))
                    open_anomaly.fim = now
                    open_anomaly.duracao_segundos = dur
                    open_anomaly.save()
                else:
                    open_anomaly.save(update_fields=["menor_valor", "maior_valor", "ultimo_valor"])
            else:
                if min_violated or max_violated:
                    prod_snap = ""
                    mat_snap = ""
                    lote_snap = ""

                    if p_cfg.cavity_config:
                        mat_item = scada_values.get(p_cfg.cavity_config.xid_matriz) if p_cfg.cavity_config.xid_matriz else None
                        mat_snap = str(mat_item.get("str_value", mat_item.get("value", ""))) if mat_item else ""

                        prod_item = scada_values.get(p_cfg.cavity_config.xid_produto) if p_cfg.cavity_config.xid_produto else None
                        prod_snap = str(prod_item.get("str_value", prod_item.get("value", ""))) if prod_item else ""

                        lote_item = scada_values.get(p_cfg.cavity_config.xid_lote_bladder) if p_cfg.cavity_config.xid_lote_bladder else None
                        lote_snap = str(lote_item.get("str_value", lote_item.get("value", ""))) if lote_item else ""

                    active_downtime = ProductionDowntimeEvent.objects.filter(
                        machine_config=m_cfg,
                        fim__isnull=True
                    ).order_by("-inicio").first()

                    ProductionParameterAnomalyEvent.objects.create(
                        parameter_config=p_cfg,
                        machine_config=m_cfg,
                        cavity_config=p_cfg.cavity_config,
                        inicio=now,
                        inicio_fora_faixa=now,
                        menor_valor=p_val,
                        maior_valor=p_val,
                        ultimo_valor=p_val,
                        tipo_limite="MINIMO" if min_violated else "MAXIMO",
                        produto_snapshot=prod_snap,
                        matriz_snapshot=mat_snap,
                        lote_snapshot=lote_snap,
                        downtime_event=active_downtime
                    )

        return scada_values

    @classmethod
    def get_dashboard_state(
        cls,
        data_inicio_str: Optional[str] = None,
        data_final_str: Optional[str] = None,
        periodo: Optional[str] = None,
        scada_values: Optional[Dict[str, Any]] = None
    ) -> dict:
        active_shift_info = get_active_shift()

        configs = list(
            ProductionMachineConfig.objects.select_related("machine", "machine__setor")
            .prefetch_related("cavities")
            .order_by("ordem_exibicao", "machine__nome")
        )
        global_params = list(
            ProductionGlobalParameter.objects.exclude(
                Q(chave__startswith="calandra_") | Q(nome__istartswith="calandra")
            ).order_by("ordem", "nome")
        )
        global_alarms = list(ProductionGlobalAlarm.objects.all().order_by("ordem", "nome"))

        all_xids = set()
        for cfg in configs:
            if cfg.xid_status_prensa:
                all_xids.add(cfg.xid_status_prensa)
            if cfg.xid_abertura:
                all_xids.add(cfg.xid_abertura)
            if cfg.xid_motivo_parada_geral:
                all_xids.add(cfg.xid_motivo_parada_geral)
            for cav in cfg.cavities.all():
                if cav.xid_matriz:
                    all_xids.add(cav.xid_matriz)
                if cav.xid_produto:
                    all_xids.add(cav.xid_produto)
                if cav.xid_lote_bladder:
                    all_xids.add(cav.xid_lote_bladder)
                if cav.xid_producao:
                    all_xids.add(cav.xid_producao)
                if cav.xid_meta:
                    all_xids.add(cav.xid_meta)
                if cav.xid_motivo_parada:
                    all_xids.add(cav.xid_motivo_parada)
                if cav.xid_bla_real:
                    all_xids.add(cav.xid_bla_real)
                if cav.xid_motivo_troca_bladder:
                    all_xids.add(cav.xid_motivo_troca_bladder)

        for p in global_params:
            if p.xid:
                all_xids.add(p.xid)
        for a in global_alarms:
            if a.xid:
                all_xids.add(a.xid)

        if scada_values is None:
            scada_values = scada_reader.get_last_values_batch(list(all_xids))

        # Sincronizar máquina de estados com o Scada-LTS de forma idempotente
        cls.process_scada_cycle(scada_values)

        now = timezone.now()
        now_ms = int(time.time() * 1000)
        machines_data = []
        produzindo_count = 0
        paradas_count = 0
        sem_comunicacao_count = 0

        for cfg in configs:
            m_name = cfg.machine.nome
            setor_nome = cfg.machine.setor.nome if cfg.machine.setor else "Geral"
            state_obj = getattr(cfg, "state", None)

            if state_obj:
                state = state_obj.estado_atual
                sem_comunicacao = state_obj.sem_comunicacao
                is_stale = state_obj.dado_desatualizado
                timestamp_ms = state_obj.ultimo_timestamp_scada
                motivo_geral_val = state_obj.motivo_atual
            else:
                state = "SEM_COMUNICACAO"
                sem_comunicacao = True
                is_stale = False
                timestamp_ms = None
                motivo_geral_val = ""

            if sem_comunicacao:
                state = "SEM_COMUNICACAO"
                state_label = "Sem comunicação"
                badge_class = "secondary"
                sem_comunicacao_count += 1
            elif state == "PRODUZINDO":
                state_label = "Produzindo"
                badge_class = "success"
                produzindo_count += 1
            else:
                state = "PARADA"
                state_label = "Parada"
                badge_class = "danger"
                paradas_count += 1

            open_event = ProductionDowntimeEvent.objects.filter(
                machine_config=cfg, fim__isnull=True
            ).order_by("-inicio").first()

            motivo_entry = scada_values.get(cfg.xid_motivo_parada_geral) if cfg.xid_motivo_parada_geral else None
            raw_motivo = (
                (open_event.motivo_geral if open_event and open_event.motivo_geral else None)
                or (motivo_entry.get("str_value", motivo_entry.get("value", "")) if motivo_entry else None)
                or (state_obj.motivo_atual if state_obj else None)
            )

            motivo_geral_val = cls.format_press_reason(raw_motivo, state)

            if open_event:
                timer_secs = max(0, int((now - open_event.inicio).total_seconds()))
            elif state_obj and state_obj.inicio_estado_atual:
                timer_secs = max(0, int((now - state_obj.inicio_estado_atual).total_seconds()))
            else:
                timer_secs = 0

            tempo_decorrido_str = cls.format_elapsed_seconds_human(timer_secs, state)

            alerta_parada_5min = (state == "PARADA" and not sem_comunicacao and not is_stale and timer_secs >= 300)
            motivo_prensa_pendente = (state == "PARADA" and (motivo_geral_val == "Motivo da prensa não informado" or not motivo_geral_val))

            abertura_entry = scada_values.get(cfg.xid_abertura) if cfg.xid_abertura else None
            abertura_val = abertura_entry.get("str_value", "") if abertura_entry else None

            cavities_list, total_prod, total_meta, total_percent, total_percent_bar = cls.build_cavities_data(
                cfg, scada_values, shift_info=active_shift_info
            )

            machines_data.append({
                "id": cfg.id,
                "machine_id": cfg.machine_id,
                "nome": m_name,
                "setor": setor_nome,
                "ordem": cfg.ordem_exibicao,
                "state": state,
                "state_label": state_label,
                "badge_class": badge_class,
                "is_stale": is_stale,
                "stale_limit_seconds": cfg.stale_limit_seconds,
                "timestamp_ms": timestamp_ms,
                "timer_secs": timer_secs,
                "tempo_decorrido_str": tempo_decorrido_str,
                "abertura": abertura_val,
                "motivo_geral": motivo_geral_val,
                "motivo_prensa_pendente": motivo_prensa_pendente,
                "alerta_parada_5min": alerta_parada_5min,
                "cavidades": cavities_list,
                "tem_cavidade_parada": any(c["status_code"] == "PARADA" for c in cavities_list),
                "producao_total": total_prod,
                "meta_total": total_meta,
                "percentual_total": total_percent,
                "percentual_total_bar": total_percent_bar,
            })

        params_data = []
        for p in global_params:
            p_entry = scada_values.get(p.xid) if p.xid else None
            val = p_entry.get("str_value", "N/A") if p_entry else "N/A"
            ts = p_entry.get("ts") if p_entry else None
            p_stale = False
            if ts:
                p_stale = ((now_ms - ts) / 1000.0) > 300

            params_data.append({
                "nome": p.nome,
                "chave": p.chave,
                "unidade": p.unidade or "",
                "valor": val,
                "is_stale": p_stale,
            })

        alarms_data = []
        for a in global_alarms:
            a_entry = scada_values.get(a.xid) if a.xid else None
            bool_val = a_entry.get("value", False) if a_entry else False
            is_active = bool(bool_val) and str(bool_val).lower() not in ("false", "0", "")

            alarms_data.append({
                "nome": a.nome,
                "chave": a.chave,
                "is_active": is_active,
                "status_label": "ALERTA / ATIVO" if is_active else "NORMAL",
                "badge_class": "danger" if is_active else "success",
            })

        # ==============================================================================
        # CARD GERAL DAS MATRIZES (A: RESUMO ATUAL, B: HISTÓRICO DE MATRIZES)
        # ==============================================================================
        matrix_summary_map = {}
        for cfg in configs:
            for cav in cfg.cavities.all():
                mat_entry = scada_values.get(cav.xid_matriz) if cav.xid_matriz else None
                raw_mat = mat_entry.get("str_value", mat_entry.get("value")) if mat_entry else None
                norm_mat = normalize_matrix_value(raw_mat)

                c_code, _, _, _ = cls.resolve_cavity_status_and_reason(cav, scada_values)

                key = norm_mat if norm_mat else ""
                if key not in matrix_summary_map:
                    mat_disp = resolve_matrix_product_display(norm_mat)["display"] if norm_mat else "Matriz não informada"
                    matrix_summary_map[key] = {
                        "matriz": norm_mat,
                        "label": mat_disp,
                        "is_informada": bool(norm_mat),
                        "normais": 0,
                        "paradas": 0,
                        "indeterminadas": 0,
                        "total": 0,
                    }

                if c_code == "NORMAL":
                    matrix_summary_map[key]["normais"] += 1
                elif c_code == "PARADA":
                    matrix_summary_map[key]["paradas"] += 1
                else:
                    matrix_summary_map[key]["indeterminadas"] += 1
                matrix_summary_map[key]["total"] += 1

        matrix_summary = sorted(
            matrix_summary_map.values(),
            key=lambda x: (0 if x["is_informada"] else 1, x["label"])
        )

        matrix_history_error = None
        if periodo == "hoje":
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            periodo_ativo = "hoje"
        elif periodo == "7d":
            end_dt = now
            start_dt = (end_dt - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
            periodo_ativo = "7d"
        elif periodo == "30d":
            end_dt = now
            start_dt = (end_dt - timezone.timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
            periodo_ativo = "30d"
        elif data_inicio_str and data_final_str:
            try:
                d_start = timezone.datetime.strptime(data_inicio_str, "%Y-%m-%d").date()
                d_end = timezone.datetime.strptime(data_final_str, "%Y-%m-%d").date()
                if d_start > d_end:
                    matrix_history_error = "Data inicial não pode ser maior que a data final."
                    start_dt = (now - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_dt = now
                    periodo_ativo = "custom"
                else:
                    start_dt = timezone.make_aware(timezone.datetime.combine(d_start, timezone.datetime.min.time()))
                    end_dt = timezone.make_aware(timezone.datetime.combine(d_end, timezone.datetime.max.time()))
                    periodo_ativo = "custom"
            except ValueError:
                end_dt = now
                start_dt = (end_dt - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                periodo_ativo = "7d"
        else:
            end_dt = now
            start_dt = (end_dt - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
            periodo_ativo = "7d"

        matrix_history = []
        if not matrix_history_error:
            history_qs = ProductionCavityMatrixHistory.objects.select_related(
                "cavity_config",
                "cavity_config__machine_config",
                "cavity_config__machine_config__machine"
            ).filter(
                Q(started_at__lte=end_dt) & (Q(ended_at__isnull=True) | Q(ended_at__gte=start_dt))
            )

            raw_history = list(history_qs)
            raw_history.sort(key=lambda r: (0 if r.ended_at is None else 1, -r.started_at.timestamp()))

            for rec in raw_history:
                is_open = (rec.ended_at is None)
                dur_end = rec.ended_at or now
                eff_start = max(rec.started_at, start_dt)
                eff_end = min(dur_end, end_dt)
                dur_secs = max(0, int((eff_end - eff_start).total_seconds()))

                mat_info = resolve_matrix_product_display(rec.matrix_value)
                matrix_history.append({
                    "id": rec.id,
                    "maquina_nome": rec.cavity_config.machine_config.machine.nome,
                    "cavidade_nome": rec.cavity_config.nome,
                    "matriz_value": mat_info["display"],
                    "matriz_code": rec.matrix_value,
                    "started_at": rec.started_at,
                    "ended_at": rec.ended_at,
                    "duracao_str": cls.format_elapsed_seconds(dur_secs),
                    "is_open": is_open,
                    "situacao_label": "Em uso" if is_open else "Finalizada",
                    "situacao_badge": "success" if is_open else "secondary",
                })

        cavidades_paradas_count = sum(1 for m in machines_data for c in m["cavidades"] if c["status_code"] == "PARADA")
        pcp_plan_summary = cls.get_pcp_plan_summary(date=timezone.now().date(), shift_obj=active_shift_info.get("shift_obj") if active_shift_info else None)

        active_mismatch_events = list(
            ProductionBladderSetupMismatchEvent.objects.filter(status="EM_ABERTO", ended_at__isnull=True)
            .select_related("cavity_config", "cavity_config__machine_config", "cavity_config__machine_config__machine")
            .order_by("-started_at")
        )

        return {
            "active_shift": active_shift_info,
            "machines": machines_data,
            "total_count": len(configs),
            "produzindo_count": produzindo_count,
            "paradas_count": paradas_count,
            "sem_comunicacao_count": sem_comunicacao_count,
            "cavidades_paradas_count": cavidades_paradas_count,
            "global_parameters": params_data,
            "global_alarms": alarms_data,
            "matrix_summary": matrix_summary,
            "matrix_history": matrix_history,
            "matrix_history_error": matrix_history_error,
            "pcp_plan_summary": pcp_plan_summary,
            "active_mismatch_events": active_mismatch_events,
            "mismatch_count": len(active_mismatch_events),
            "matrix_filters": {
                "data_inicio_str": start_dt.strftime("%Y-%m-%d"),
                "data_final_str": end_dt.strftime("%Y-%m-%d"),
                "periodo_ativo": periodo_ativo,
            },
            "scada_offline": (len(scada_values) == 0 and len(all_xids) > 0),
            "last_updated_str": timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
        }

    @classmethod
    def format_general_downtime_reason(cls, raw_val: Any) -> str:
        if raw_val is None:
            return "Sem parada geral"
        raw_str = str(raw_val).strip()
        if not raw_str or raw_str.lower() in ("0", "none", "null", "normal", "sem parada", "sem parada geral"):
            return "Sem parada geral"
        try:
            code = int(float(raw_str))
            if code == 0:
                return "Sem parada geral"
            if code in PRESS_REASON_MAP:
                return PRESS_REASON_MAP[code]
            if code in CAVITY_REASON_MAP:
                return CAVITY_REASON_MAP[code]
            return f"Motivo desconhecido (código {code})"
        except (ValueError, TypeError):
            return raw_str

    @classmethod
    def format_cavity_downtime_reason(cls, raw_val: Any) -> str:
        if raw_val is None:
            return "Sem parada"
        raw_str = str(raw_val).strip()
        if not raw_str or raw_str.lower() in ("0", "none", "null", "normal", "sem parada"):
            return "Sem parada"
        try:
            code = int(float(raw_str))
            if code == 0:
                return "Sem parada"
            if code in CAVITY_REASON_MAP:
                return CAVITY_REASON_MAP[code]
            return f"Motivo desconhecido (código {code})"
        except (ValueError, TypeError):
            return raw_str

    @classmethod
    def get_machine_detail(
        cls,
        config_id: int,
        inicio_str: Optional[str] = None,
        fim_str: Optional[str] = None,
        data_inicio_str: Optional[str] = None,
        data_final_str: Optional[str] = None,
        periodo: Optional[str] = None,
        page: Any = 1
    ) -> Dict[str, Any]:
        """
        Retorna o contexto detalhado de uma máquina específica para a view /producao/maquinas/<id>/,
        incluindo estado atual, cavidades, histórico de paradas filtrado por data/hora (datetime-local),
        sobreposição temporal, motivos de parada por cavidade históricos, paginação backend e KPIs do período.
        """
        cfg = (
            ProductionMachineConfig.objects.select_related("machine", "machine__setor")
            .prefetch_related("cavities")
            .get(pk=config_id)
        )

        now = timezone.now()
        date_error_msg = None

        def parse_dt_param(val_str: Optional[str]) -> Optional[timezone.datetime]:
            if not val_str or not str(val_str).strip():
                return None
            v = str(val_str).strip()
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    dt = timezone.datetime.strptime(v, fmt)
                    if timezone.is_naive(dt):
                        dt = timezone.make_aware(dt)
                    return dt
                except ValueError:
                    continue
            return None

        dt_inicio = parse_dt_param(inicio_str)
        dt_fim = parse_dt_param(fim_str)

        if inicio_str or fim_str:
            if dt_inicio and dt_fim:
                if dt_inicio > dt_fim:
                    date_error_msg = "O início do período não pode ser posterior ao fim."
                    start_dt = (now - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_dt = now
                    periodo_ativo = "custom"
                else:
                    start_dt = dt_inicio
                    end_dt = dt_fim
                    periodo_ativo = "custom"
            elif dt_inicio:
                start_dt = dt_inicio
                end_dt = now
                periodo_ativo = "custom"
            elif dt_fim:
                start_dt = (dt_fim - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_dt = dt_fim
                periodo_ativo = "custom"
            else:
                date_error_msg = "Formato de data e horário inválido."
                start_dt = (now - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_dt = now
                periodo_ativo = "7d"
        elif periodo == "hoje":
            start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            periodo_ativo = "hoje"
        elif periodo == "7d":
            end_dt = now
            start_dt = (end_dt - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
            periodo_ativo = "7d"
        elif periodo == "30d":
            end_dt = now
            start_dt = (end_dt - timezone.timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
            periodo_ativo = "30d"
        elif data_inicio_str and data_final_str:
            try:
                d_start = timezone.datetime.strptime(data_inicio_str, "%Y-%m-%d").date()
                d_end = timezone.datetime.strptime(data_final_str, "%Y-%m-%d").date()
                if d_start > d_end:
                    date_error_msg = "O início do período não pode ser posterior ao fim."
                    start_dt = (now - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_dt = now
                    periodo_ativo = "custom"
                else:
                    start_dt = timezone.make_aware(timezone.datetime.combine(d_start, timezone.datetime.min.time()))
                    end_dt = timezone.make_aware(timezone.datetime.combine(d_end, timezone.datetime.max.time()))
                    periodo_ativo = "custom"
            except ValueError:
                date_error_msg = "Formato de data inválido."
                end_dt = now
                start_dt = (end_dt - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                periodo_ativo = "7d"
        else:
            end_dt = now
            start_dt = (end_dt - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
            periodo_ativo = "7d"

        # Coletar XIDs da máquina
        all_xids = set()
        if cfg.xid_status_prensa:
            all_xids.add(cfg.xid_status_prensa)
        if cfg.xid_abertura:
            all_xids.add(cfg.xid_abertura)
        if cfg.xid_motivo_parada_geral:
            all_xids.add(cfg.xid_motivo_parada_geral)
        for cav in cfg.cavities.all():
            if cav.xid_matriz:
                all_xids.add(cav.xid_matriz)
            if cav.xid_produto:
                all_xids.add(cav.xid_produto)
            if cav.xid_lote_bladder:
                all_xids.add(cav.xid_lote_bladder)
            if cav.xid_producao:
                all_xids.add(cav.xid_producao)
            if cav.xid_meta:
                all_xids.add(cav.xid_meta)
            if cav.xid_motivo_parada:
                all_xids.add(cav.xid_motivo_parada)
            if cav.xid_bla_real:
                all_xids.add(cav.xid_bla_real)
            if cav.xid_motivo_troca_bladder:
                all_xids.add(cav.xid_motivo_troca_bladder)

        scada_values = scada_reader.get_last_values_batch(list(all_xids))

        # Garantir estado sincronizado no BD
        cls.process_scada_cycle(scada_values)

        state_obj = getattr(cfg, "state", None)
        if state_obj:
            state = state_obj.estado_atual
            sem_comunicacao = state_obj.sem_comunicacao
            is_stale = state_obj.dado_desatualizado
            timestamp_ms = state_obj.ultimo_timestamp_scada
            motivo_geral_val = state_obj.motivo_atual
        else:
            state = "SEM_COMUNICACAO"
            sem_comunicacao = True
            is_stale = False
            timestamp_ms = None
            motivo_geral_val = ""

        if sem_comunicacao:
            state = "SEM_COMUNICACAO"
            state_label = "Sem comunicação"
            badge_class = "secondary"
        elif state == "PRODUZINDO":
            state_label = "Produzindo"
            badge_class = "success"
        else:
            state = "PARADA"
            state_label = "Parada"
            badge_class = "danger"

        open_event = ProductionDowntimeEvent.objects.filter(
            machine_config=cfg, fim__isnull=True
        ).order_by("-inicio").first()

        motivo_entry = scada_values.get(cfg.xid_motivo_parada_geral) if cfg.xid_motivo_parada_geral else None
        raw_motivo = (
            (open_event.motivo_geral if open_event and open_event.motivo_geral else None)
            or (motivo_entry.get("str_value", motivo_entry.get("value", "")) if motivo_entry else None)
            or (state_obj.motivo_atual if state_obj else None)
        )

        motivo_geral_val = cls.format_press_reason(raw_motivo, state)

        if open_event:
            timer_secs = max(0, int((now - open_event.inicio).total_seconds()))
        elif state_obj and state_obj.inicio_estado_atual:
            timer_secs = max(0, int((now - state_obj.inicio_estado_atual).total_seconds()))
        else:
            timer_secs = 0

        tempo_decorrido_str = cls.format_elapsed_seconds_human(timer_secs, state)

        active_shift_info = get_active_shift()

        alerta_parada_5min = (state == "PARADA" and not sem_comunicacao and not is_stale and timer_secs >= 300)
        motivo_prensa_pendente = not (motivo_geral_val and str(motivo_geral_val).strip())

        cavities_list, total_prod, total_meta, total_percent, total_percent_bar = cls.build_cavities_data(
            cfg, scada_values, shift_info=active_shift_info
        )

        # Query de eventos de parada gerais com regra de sobreposição temporal (Django ORM)
        events_qs = ProductionDowntimeEvent.objects.filter(
            machine_config=cfg
        ).filter(
            Q(inicio__lte=end_dt) & (Q(fim__isnull=True) | Q(fim__gte=start_dt))
        ).order_by("-inicio")

        total_downtime_seconds = 0
        maior_parada_seconds = 0
        qtd_paradas = 0

        for ev_id, ev_inicio, ev_fim in events_qs.values_list("id", "inicio", "fim"):
            eff_start = max(ev_inicio, start_dt)
            eff_end = min(ev_fim or now, end_dt)
            eff_dur = max(0, int((eff_end - eff_start).total_seconds()))

            total_downtime_seconds += eff_dur
            qtd_paradas += 1
            if eff_dur > maior_parada_seconds:
                maior_parada_seconds = eff_dur

        duracao_media_seconds = round(total_downtime_seconds / qtd_paradas) if qtd_paradas > 0 else 0

        # Paginação no Backend (10 eventos por página)
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
        paginator = Paginator(events_qs, 10)
        try:
            page_obj = paginator.page(page)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # Buscar eventos de parada por cavidade (historico real) sobrepostos ao periodo
        cavity_ids = list(cfg.cavities.values_list("id", flat=True))
        cavity_events_qs = ProductionCavityDowntimeEvent.objects.filter(
            cavity_config_id__in=cavity_ids
        ).filter(
            Q(inicio__lte=end_dt) & (Q(fim__isnull=True) | Q(fim__gte=start_dt))
        ).select_related("cavity_config").order_by("inicio")
        cavity_events_list = list(cavity_events_qs)

        events_data = []
        for ev in page_obj:
            ev_start = ev.inicio
            ev_end = ev.fim or now
            eff_start = max(ev_start, start_dt)
            eff_end = min(ev_end, end_dt)
            eff_dur = max(0, int((eff_end - eff_start).total_seconds()))

            is_open = (ev.fim is None)
            motivo_geral_friendly = cls.format_general_downtime_reason(ev.motivo_geral)

            # Encontrar eventos por cavidade sobrepostos a este evento geral
            overlapping_cavities = []
            seen_cavity_motivos = set()

            for cav_ev in cavity_events_list:
                c_start = cav_ev.inicio
                c_end = cav_ev.fim or now

                # Checar sobreposição com o intervalo do evento geral
                if c_start <= eff_end and c_end >= eff_start:
                    c_reason_raw = cav_ev.motivo_parada or cav_ev.snapshot_valor_motivo or ""
                    c_reason_clean = str(c_reason_raw).strip()

                    if not c_reason_clean or c_reason_clean.lower() in ("0", "normal", "sem parada", "sem parada de cavidade", "none", "null"):
                        continue

                    c_reason_friendly = cls.format_cavity_downtime_reason(c_reason_raw)

                    c_eff_start = max(c_start, eff_start)
                    c_eff_end = min(c_end, eff_end)
                    c_eff_dur = max(0, int((c_eff_end - c_eff_start).total_seconds()))

                    dedup_key = (cav_ev.cavity_config.nome, c_reason_friendly, c_eff_start, c_eff_end)
                    if dedup_key in seen_cavity_motivos:
                        continue
                    seen_cavity_motivos.add(dedup_key)

                    overlapping_cavities.append({
                        "cavity_name": cav_ev.cavity_config.nome,
                        "reason": c_reason_friendly,
                        "start": c_eff_start,
                        "end": c_eff_end if cav_ev.fim else None,
                        "is_open": cav_ev.fim is None,
                        "duracao_str": cls.format_elapsed_seconds(c_eff_dur),
                        "text_compact": f"{cav_ev.cavity_config.nome}: {c_reason_friendly}",
                        "text_detailed": f"{cav_ev.cavity_config.nome} ({c_eff_start.strftime('%H:%M:%S')}–{c_eff_end.strftime('%H:%M:%S') if cav_ev.fim else 'em andamento'}): {c_reason_friendly}",
                    })

            if overlapping_cavities:
                cavities_summary = "; ".join(c["text_compact"] for c in overlapping_cavities)
            else:
                cavities_summary = "Nenhuma parada por cavidade"

            events_data.append({
                "id": ev.id,
                "inicio": ev.inicio,
                "fim": ev.fim,
                "duracao_segundos": eff_dur,
                "duracao_str": cls.format_elapsed_seconds(eff_dur),
                "motivo_geral": motivo_geral_friendly,
                "raw_motivo_geral": ev.motivo_geral,
                "is_open": is_open,
                "status_label": "Em andamento" if is_open else "Fechado",
                "cavidades_motivos": overlapping_cavities,
                "cavidades_summary": cavities_summary,
                "has_cavity_reasons": len(overlapping_cavities) > 0,
            })

        # ==============================================================================
        # LINHA DO TEMPO OPERACIONAL E KPIS COMPLEMENTARES DA MÁQUINA
        # ==============================================================================
        intervals_qs = ProductionMachineStateInterval.objects.filter(
            machine_config=cfg
        ).filter(
            Q(started_at__lte=end_dt) & (Q(ended_at__isnull=True) | Q(ended_at__gte=start_dt))
        ).order_by("started_at")

        tempo_produzindo_sec = 0
        tempo_parado_sec = 0
        tempo_sem_comunicacao_sec = 0
        qtd_ciclos_producao = 0
        qtd_paradas_linha_tempo = 0
        timeline_segments = []

        total_period_seconds = max(1, int((end_dt - start_dt).total_seconds()))

        for inv in intervals_qs:
            eff_start = max(inv.started_at, start_dt)
            eff_end = min(inv.ended_at or now, end_dt)
            eff_dur = max(0, int((eff_end - eff_start).total_seconds()))

            if inv.state == "PRODUZINDO":
                tempo_produzindo_sec += eff_dur
                qtd_ciclos_producao += 1
                state_label_seg = "Produzindo"
                badge_class_seg = "success"
                color_hex = "#22c55e"
            elif inv.state == "PARADA":
                tempo_parado_sec += eff_dur
                qtd_paradas_linha_tempo += 1
                state_label_seg = "Parada"
                badge_class_seg = "danger"
                color_hex = "#ef4444"
            else:
                tempo_sem_comunicacao_sec += eff_dur
                state_label_seg = "Sem comunicação"
                badge_class_seg = "secondary"
                color_hex = "#9ca3af"

            width_pct = round((eff_dur / total_period_seconds) * 100, 2)
            is_open = (inv.ended_at is None)

            timeline_segments.append({
                "id": inv.id,
                "state": inv.state,
                "state_label": state_label_seg,
                "badge_class": badge_class_seg,
                "color_hex": color_hex,
                "started_at": inv.started_at,
                "ended_at": inv.ended_at,
                "eff_start": eff_start,
                "eff_end": eff_end,
                "duracao_segundos": eff_dur,
                "duracao_str": cls.format_elapsed_seconds(eff_dur),
                "width_pct": width_pct,
                "is_open": is_open,
            })

        denom = tempo_produzindo_sec + tempo_parado_sec
        if denom > 0:
            percentual_produzindo = round((tempo_produzindo_sec / denom) * 100, 1)
            percentual_parado = round((tempo_parado_sec / denom) * 100, 1)
        else:
            percentual_produzindo = 0.0
            percentual_parado = 0.0

        # Buscar responsáveis ativos e histórico de atualizações parciais da manutenção
        open_allocs = (
            Allocation.objects.filter(maquina=cfg.machine, data_fim__isnull=True, status__in=["EM_ATENDIMENTO", "EM_PAUSA"])
            .select_related("tecnico")
            .prefetch_related("progress_updates")
        )
        tech_names = list(dict.fromkeys(a.tecnico.nome for a in open_allocs if a.tecnico))
        responsaveis_label = ", ".join(tech_names) if tech_names else "Responsável ainda não atribuído"

        progress_updates_qs = (
            AllocationProgressUpdate.objects.filter(allocation__maquina=cfg.machine)
            .select_related("allocation", "allocation__tecnico", "autor")
            .order_by("-criado_em")[:50]
        )

        atualizacoes_manutencao = [
            {
                "autor": pu.autor.get_full_name() or pu.autor.username if pu.autor else "Sistema",
                "tecnico": pu.allocation.tecnico.nome if (pu.allocation and pu.allocation.tecnico) else "N/A",
                "descricao": pu.descricao,
                "criado_em_str": pu.criado_em.strftime("%d/%m/%Y %H:%M"),
                "status_alocacao": pu.allocation.get_status_display() if pu.allocation else "",
            }
            for pu in progress_updates_qs
        ]

        # Anomalias de parâmetros de processo
        active_anomalies_qs = ProductionParameterAnomalyEvent.objects.filter(
            machine_config=cfg,
            fim__isnull=True
        ).select_related("parameter_config", "cavity_config").order_by("-inicio")

        anomalias_ativas = [
            {
                "id": a.id,
                "parametro": a.parameter_config.nome,
                "unidade": a.parameter_config.unidade,
                "tipo_limite": a.tipo_limite,
                "limite": a.parameter_config.limite_minimo if a.tipo_limite == "MINIMO" else a.parameter_config.limite_maximo,
                "valor_atual": a.ultimo_valor,
                "menor_valor": a.menor_valor,
                "maior_valor": a.maior_valor,
                "inicio_str": a.inicio.strftime("%d/%m/%Y %H:%M"),
                "cavidade_nome": a.cavity_config.nome if a.cavity_config else "Máquina Geral",
                "produto": a.produto_snapshot or "N/A",
                "matriz": a.matriz_snapshot or "N/A",
            }
            for a in active_anomalies_qs
        ]

        # Construir query string para os botões de paginação
        query_params = []
        if inicio_str:
            query_params.append(f"inicio={inicio_str}")
        if fim_str:
            query_params.append(f"fim={fim_str}")
        if data_inicio_str and not inicio_str:
            query_params.append(f"data_inicio={data_inicio_str}")
        if data_final_str and not fim_str:
            query_params.append(f"data_final={data_final_str}")
        if periodo and not (inicio_str or fim_str or data_inicio_str):
            query_params.append(f"periodo={periodo}")

        querystring = "&".join(query_params)

        return {
            "config": cfg,
            "machine": cfg.machine,
            "setor_nome": cfg.machine.setor.nome if cfg.machine.setor else "Geral",
            "active_shift": active_shift_info,
            "state": state,
            "state_label": state_label,
            "badge_class": badge_class,
            "is_stale": is_stale,
            "sem_comunicacao": sem_comunicacao,
            "tempo_decorrido_str": tempo_decorrido_str,
            "timer_secs": timer_secs,
            "alerta_parada_5min": alerta_parada_5min,
            "motivo_prensa_pendente": motivo_prensa_pendente,
            "motivo_geral": motivo_geral_val,
            "ultima_leitura_str": state_obj.ultima_leitura_scada.strftime("%d/%m/%Y %H:%M:%S") if (state_obj and state_obj.ultima_leitura_scada) else "N/A",
            "cavidades": cavities_list,
            "producao_total": total_prod,
            "meta_total": total_meta,
            "percentual_total": total_percent,
            "percentual_total_bar": total_percent_bar,
            "events": events_data,
            "page_obj": page_obj,
            "paginator": paginator,
            "querystring": querystring,
            "timeline_segments": timeline_segments,
            "total_period_seconds": total_period_seconds,
            "date_error_msg": date_error_msg,
            "responsaveis_manutencao": responsaveis_label,
            "responsaveis_lista": tech_names,
            "atualizacoes_manutencao": atualizacoes_manutencao,
            "anomalias_ativas": anomalias_ativas,
            "precisao_temporal_notice": "Precisão temporal das anomalias vinculada ao intervalo de leitura do coletor (60s)",
            "kpi": {
                "tempo_total_parado_str": cls.format_elapsed_seconds(total_downtime_seconds),
                "total_downtime_seconds": total_downtime_seconds,
                "qtd_paradas": qtd_paradas,
                "maior_parada_str": cls.format_elapsed_seconds(maior_parada_seconds),
                "duracao_media_str": cls.format_elapsed_seconds(duracao_media_seconds),
                "tempo_produzindo_str": cls.format_elapsed_seconds(tempo_produzindo_sec),
                "tempo_parado_str": cls.format_elapsed_seconds(tempo_parado_sec),
                "tempo_sem_comunicacao_str": cls.format_elapsed_seconds(tempo_sem_comunicacao_sec),
                "percentual_produzindo": percentual_produzindo,
                "percentual_parado": percentual_parado,
                "qtd_ciclos_producao": qtd_ciclos_producao,
                "qtd_paradas_linha_tempo": qtd_paradas_linha_tempo,
            },
            "filters": {
                "inicio_str": start_dt.strftime("%Y-%m-%dT%H:%M"),
                "fim_str": end_dt.strftime("%Y-%m-%dT%H:%M"),
                "data_inicio_str": start_dt.strftime("%Y-%m-%d"),
                "data_final_str": end_dt.strftime("%Y-%m-%d"),
                "periodo_ativo": periodo_ativo,
            },
        }

    @classmethod
    def get_pcp_plan_summary(cls, date=None, shift_obj=None) -> Dict[str, Any]:
        """
        Retorna o resumo consolidado do plano do turno do PCP (Fase 7 e 9).
        """
        if date is None:
            date = timezone.now().date()

        if shift_obj is None:
            active_info = get_active_shift()
            shift_obj = active_info.get("shift_obj") if active_info else None

        targets_qs = ProductionTarget.objects.select_related(
            "shift", "matrix_catalog", "predicted_machine", "predicted_cavity"
        ).filter(
            date=date,
            status__in=["PLANEJADA", "AGUARDANDO_INSTALACAO", "EM_PRODUCAO", "ATINGIDA", "CONCLUIDA_PARCIAL", "ATIVO"]
        )

        if shift_obj:
            targets_qs = targets_qs.filter(Q(shift=shift_obj) | Q(shift__isnull=True))

        targets_list = []
        meta_total = 0
        produzido_total = 0
        em_producao_count = 0
        aguardando_count = 0

        acc_qs = ProductionShiftAccumulated.objects.filter(
            date=date,
            shift=shift_obj
        ) if shift_obj else []

        acc_by_matrix = {}
        for acc in acc_qs:
            mat = (acc.matriz or "").strip()
            if mat:
                acc_by_matrix[mat] = acc_by_matrix.get(mat, 0) + acc.quantity_accumulated

        for t in targets_qs.order_by("priority", "-date"):
            meta_total += t.planned_quantity

            cat = t.matrix_catalog
            prod_target = 0
            code_scada = str(cat.codigo_scada) if cat and cat.codigo_scada else (t.matriz_codigo or "")

            for mat_key, qty in acc_by_matrix.items():
                if code_scada and (code_scada == mat_key or code_scada in mat_key):
                    prod_target += qty

            produzido_total += prod_target
            restante_t = max(0, t.planned_quantity - prod_target)
            pct_t = round((prod_target / t.planned_quantity * 100), 1) if t.planned_quantity > 0 else 0.0

            if t.status in ["EM_PRODUCAO", "ATIVO"]:
                em_producao_count += 1
            elif t.status in ["PLANEJADA", "AGUARDANDO_INSTALACAO"]:
                aguardando_count += 1

            matrix_label = cat.nome_exibicao if cat else (t.matriz_codigo or "Geral")
            destination_label = f"{t.predicted_machine.nome}" if t.predicted_machine else "A definir"

            targets_list.append({
                "id": t.id,
                "priority": t.priority,
                "modelo": matrix_label,
                "codigo_scada": cat.codigo_scada if cat else t.matriz_codigo,
                "destino": destination_label,
                "meta": t.planned_quantity,
                "produzido": prod_target,
                "restante": restante_t,
                "percentual": pct_t,
                "situacao": t.get_status_display(),
                "status_code": t.status,
            })

        restante_total = max(0, meta_total - produzido_total)
        cumprimento_percent = round((produzido_total / meta_total * 100), 1) if meta_total > 0 else 0.0

        return {
            "meta_total": meta_total,
            "produzido_total": produzido_total,
            "restante_total": restante_total,
            "cumprimento_percent": cumprimento_percent,
            "total_metas": len(targets_list),
            "em_producao_count": em_producao_count,
            "aguardando_count": aguardando_count,
            "metas_resumidas": targets_list,
        }

    @classmethod
    def get_cavity_detail(cls, machine_id: int, cavity_id: int) -> Dict[str, Any]:
        """
        Retorna o contexto detalhado da cavidade com todos os 13 atributos exigidos pela SPEC 06F
        e os metadados do Plano PCP (Fase 8).
        """
        cavity = (
            ProductionCavityConfig.objects.select_related(
                "machine_config",
                "machine_config__machine",
                "machine_config__machine__setor"
            )
            .filter(id=cavity_id, machine_config_id=machine_id)
            .first()
        )

        if not cavity:
            return {}

        cfg = cavity.machine_config
        active_shift_info = get_active_shift()

        scada_values = cls.process_scada_cycle()

        mat_entry = scada_values.get(cavity.xid_matriz) if cavity.xid_matriz else None
        matriz_val = str(mat_entry.get("str_value", mat_entry.get("value", ""))).strip() if mat_entry else ""

        prod_entry = scada_values.get(cavity.xid_produto) if cavity.xid_produto else None
        prod_val = str(prod_entry.get("str_value", prod_entry.get("value", ""))).strip() if prod_entry else ""

        lote_entry = scada_values.get(cavity.xid_lote_bladder) if cavity.xid_lote_bladder else None
        lote_val = str(lote_entry.get("str_value", lote_entry.get("value", ""))).strip() if lote_entry else ""

        bladder_lot_info = compose_bladder_lot(prod_val, lote_val)
        matrix_info = resolve_matrix_product_display(matriz_val)

        # Produção e Limites conforme SPEC 07A
        c_prod_entry = scada_values.get(cavity.xid_producao) if cavity.xid_producao else None
        contador_ciclo_scada = int(c_prod_entry["value"]) if c_prod_entry and isinstance(c_prod_entry.get("value"), (int, float)) else 0

        limite_entry = scada_values.get(cavity.xid_meta) if cavity.xid_meta else None
        limite_bladder_scada = None
        if limite_entry and isinstance(limite_entry.get("value"), (int, float)):
            limite_bladder_scada = int(limite_entry["value"])
        elif limite_entry and limite_entry.get("str_value") and str(limite_entry["str_value"]).isdigit():
            limite_bladder_scada = int(limite_entry["str_value"])

        limite_bladder_str = str(limite_bladder_scada) if limite_bladder_scada is not None else "N/A"

        s_obj = active_shift_info.get("shift_obj") if active_shift_info else None

        if active_shift_info and active_shift_info.get("shift_obj"):
            s_obj = active_shift_info["shift_obj"]
            acc_rec = ProductionShiftAccumulated.objects.filter(
                date=timezone.now().date(),
                shift=s_obj,
                cavity_config=cavity
            ).first()
            producao_acumulada_turno = acc_rec.quantity_accumulated if acc_rec else contador_ciclo_scada
        else:
            producao_acumulada_turno = contador_ciclo_scada

        # Resolução do Catálogo Canônico e Meta PCP (Fase 8)
        matrix_catalog_obj = None
        matrix_identified = False
        if matriz_val and matriz_val not in ["Não informada", "", "None"]:
            matrix_identified = True
            if matriz_val.isdigit():
                matrix_catalog_obj = ProductionMatrixCatalog.objects.filter(codigo_scada=int(matriz_val)).first()
            if not matrix_catalog_obj:
                matrix_catalog_obj = ProductionMatrixCatalog.objects.filter(
                    Q(codigo__iexact=matriz_val) |
                    Q(nome_scada__iexact=matriz_val) |
                    Q(nome_exibicao__iexact=matriz_val) |
                    Q(produto__iexact=matriz_val)
                ).first()

        pcp_info = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=cavity,
            machine_config=cavity.machine_config,
            mat_catalog=matrix_catalog_obj,
            matriz_val=matriz_val,
            shift_obj=s_obj
        )

        if pcp_info["is_pcp"]:
            c_meta_turno = pcp_info["meta_turno"]
            c_meta_diaria = pcp_info["meta_turno"]
            meta_total_modelo = pcp_info["meta_total_turno"]
            is_pcp = True
            pcp_divergencia = pcp_info.get("pcp_divergencia")
        else:
            is_pcp = False
            pcp_divergencia = None
            target_obj = None
            if matrix_catalog_obj:
                target_obj = ProductionTarget.objects.filter(
                    date=timezone.now().date(),
                    matrix_catalog=matrix_catalog_obj,
                    status__in=["PLANEJADA", "AGUARDANDO_INSTALACAO", "EM_PRODUCAO", "ATINGIDA", "CONCLUIDA_PARCIAL", "ATIVO"]
                ).filter(
                    Q(shift=s_obj) | Q(shift__isnull=True)
                ).order_by("-shift_id").first()
            elif matriz_val and matriz_val != "Não informada":
                target_obj = ProductionTarget.objects.filter(
                    date=timezone.now().date(),
                    matriz_codigo__iexact=matriz_val,
                    status__in=["PLANEJADA", "AGUARDANDO_INSTALACAO", "EM_PRODUCAO", "ATINGIDA", "CONCLUIDA_PARCIAL", "ATIVO"]
                ).filter(
                    Q(shift=s_obj) | Q(shift__isnull=True)
                ).order_by("-shift_id").first()

            meta_total_modelo = target_obj.planned_quantity if target_obj else 0
            if target_obj:
                c_meta_turno = target_obj.planned_quantity
                c_meta_diaria = target_obj.planned_quantity
            else:
                c_meta_diaria = cavity.meta_producao_manual or 0
                effective_percent = active_shift_info.get("effective_percent", 100.0) if active_shift_info else 100.0
                has_shifts = active_shift_info.get("has_shifts", False) if active_shift_info else False
                if has_shifts:
                    c_meta_turno = round(c_meta_diaria * (effective_percent / 100.0))
                else:
                    c_meta_turno = c_meta_diaria

        producao_total_modelo = 0
        if s_obj and matrix_catalog_obj and matrix_catalog_obj.codigo_scada:
            code_str = str(matrix_catalog_obj.codigo_scada)
            accs = ProductionShiftAccumulated.objects.filter(
                date=timezone.now().date(),
                shift=s_obj
            )
            for acc in accs:
                if acc.matriz and code_str in str(acc.matriz):
                    producao_total_modelo += acc.quantity_accumulated
        else:
            producao_total_modelo = producao_acumulada_turno

        restante_cavidade = max(0, c_meta_turno - producao_acumulada_turno)
        percentual_realizado = round((producao_acumulada_turno / c_meta_turno * 100), 1) if c_meta_turno > 0 else 0.0

        c_code, c_label, c_badge, c_motivo = cls.resolve_cavity_status_and_reason(cavity, scada_values)

        open_cav_event = (
            ProductionCavityDowntimeEvent.objects.filter(cavity_config=cavity, fim__isnull=True)
            .order_by("-inicio")
            .first()
        )

        inicio_parada = open_cav_event.inicio if open_cav_event else None
        dur_parada_secs = 0
        if open_cav_event:
            dur_parada_secs = max(0, int((timezone.now() - open_cav_event.inicio).total_seconds()))
        elif c_code == "PARADA":
            cav_state = getattr(cavity, "state", None)
            if cav_state and cav_state.inicio_estado_atual:
                inicio_parada = cav_state.inicio_estado_atual
                dur_parada_secs = max(0, int((timezone.now() - cav_state.inicio_estado_atual).total_seconds()))

        tempo_parado_str = cls.format_elapsed_seconds(dur_parada_secs) if dur_parada_secs > 0 else "00:00:00"

        perda_estimada = cls.calculate_loss_estimate(cavity, dur_parada_secs, prod_val, matriz_val)

        active_allocations = (
            Allocation.objects.filter(
                maquina=cfg.machine,
                status__in=["EM_ATENDIMENTO", "EM_PAUSA"]
            ).select_related("tecnico")
        )

        tech_names = list(set([a.tecnico.nome for a in active_allocations if a.tecnico]))
        responsaveis_label = ", ".join(tech_names) if tech_names else "Responsável ainda não atribuído"

        progress_updates_qs = (
            AllocationProgressUpdate.objects.filter(allocation__maquina=cfg.machine)
            .select_related("autor", "allocation", "allocation__tecnico")
            .order_by("-criado_em")[:15]
        )

        atualizacoes_manutencao = [
            {
                "id": pu.id,
                "autor": pu.autor.get_full_name() or pu.autor.username if pu.autor else "Sistema",
                "tecnico": pu.allocation.tecnico.nome if (pu.allocation and pu.allocation.tecnico) else "N/A",
                "descricao": pu.descricao,
                "criado_em_str": pu.criado_em.strftime("%d/%m/%Y %H:%M"),
                "status_alocacao": pu.allocation.get_status_display() if pu.allocation else "",
            }
            for pu in progress_updates_qs
        ]

        anomalias_qs = (
            ProductionParameterAnomalyEvent.objects.filter(
                cavity_config=cavity,
                fim__isnull=True
            ).select_related("parameter_config")
        )

        anomalias_relacionadas = [
            {
                "id": a.id,
                "parametro": a.parameter_config.nome,
                "tipo_limite": a.get_tipo_limite_display(),
                "valor_atual": a.ultimo_valor,
                "unidade": a.parameter_config.unidade or "",
                "inicio_str": a.inicio.strftime("%d/%m/%Y %H:%M"),
            }
            for a in anomalias_qs
        ]

        historico_eventos_qs = (
            ProductionCavityDowntimeEvent.objects.filter(cavity_config=cavity)
            .order_by("-inicio")[:10]
        )

        historico_eventos = [
            {
                "id": e.id,
                "inicio_str": e.inicio.strftime("%d/%m/%Y %H:%M"),
                "fim_str": e.fim.strftime("%d/%m/%Y %H:%M") if e.fim else "Em andamento",
                "duracao_str": cls.format_elapsed_seconds(e.duracao_segundos) if e.fim else cls.format_elapsed_seconds(max(0, int((timezone.now() - e.inicio).total_seconds()))),
                "motivo_parada": e.motivo_parada,
                "is_open": e.fim is None,
            }
            for e in historico_eventos_qs
        ]

        return {
            "cavity": cavity,
            "config": cfg,
            "machine": cfg.machine,
            "setor_nome": cfg.machine.setor.nome if cfg.machine.setor else "Geral",
            "active_shift": active_shift_info,
            "status_code": c_code,
            "status_label": c_label,
            "badge_class": c_badge,
            "inicio_parada": inicio_parada,
            "inicio_parada_str": inicio_parada.strftime("%d/%m/%Y %H:%M:%S") if inicio_parada else "N/A",
            "tempo_parado_str": tempo_parado_str,
            "motivo_parada": c_motivo or "Nenhum motivo de parada ativo",
            "produto": prod_val or "Não informado",
            "matriz": matriz_val or "Não informada",
            "lote_bladder": lote_val or "Não informado",
            "matriz_produto_display": matrix_info["display"],
            "lote_completo_bladder": bladder_lot_info["display"],
            "lote_bladder_info": bladder_lot_info,
            "matrix_info": matrix_info,
            "prefixo_lote": bladder_lot_info["prefix"],
            "numero_lote": bladder_lot_info["number"],
            "limite_bladder_scada": limite_bladder_scada,
            "limite_bladder_str": limite_bladder_str,
            "contador_ciclo_scada": contador_ciclo_scada,
            "producao_acumulada_turno": producao_acumulada_turno,
            "meta_diaria": c_meta_diaria,
            "meta_turno": c_meta_turno,
            "matrix_identified": matrix_info["matrix_identified"],
            "matrix_catalog_obj": matrix_info["catalog_obj"],
            "target_obj": target_obj,
            "meta_total_modelo": meta_total_modelo,
            "producao_total_modelo": producao_total_modelo,
            "restante_cavidade": restante_cavidade,
            "percentual_realizado": percentual_realizado,
            "responsaveis_manutencao": responsaveis_label,
            "responsaveis_lista": tech_names,
            "atualizacoes_manutencao": atualizacoes_manutencao,
            "perda_estimada": perda_estimada,
            "anomalias_relacionadas": anomalias_relacionadas,
            "historico_eventos": historico_eventos,
            "precisao_temporal_notice": "Precisão temporal das anomalias vinculada ao intervalo de leitura do coletor (60s)",
        }


class PCPCalculationService:
    """
    Motor de Cálculo e Domínio para Programação Industrial PCP.
    """

    @classmethod
    def get_pcp_settings(cls) -> Dict[str, Any]:
        """
        Resgata as configurações globais de PCP do banco default com fallbacks seguros.
        """
        s_interv = ProductionPCPSetting.objects.filter(chave="intervalo_operacional_segundos").first()
        s_lixo = ProductionPCPSetting.objects.filter(chave="perda_lixo_percentual").first()
        s_ia = ProductionPCPSetting.objects.filter(chave="perda_ia_percentual").first()

        try:
            interval_sec = int(s_interv.valor) if s_interv and s_interv.valor else 90
        except ValueError:
            interval_sec = 90

        try:
            lixo_pct = float(s_lixo.valor.replace(",", ".")) if s_lixo and s_lixo.valor else 0.50
        except ValueError:
            lixo_pct = 0.50

        try:
            ia_pct = float(s_ia.valor.replace(",", ".")) if s_ia and s_ia.valor else 1.00
        except ValueError:
            ia_pct = 1.00

        return {
            "intervalo_operacional_segundos": max(0, interval_sec),
            "perda_lixo_percentual": max(0.0, lixo_pct),
            "perda_ia_percentual": max(0.0, ia_pct),
        }

    @classmethod
    def get_available_cavities_limit(cls) -> int:
        """
        Infere o limite máximo de cavidades ativas configuradas no sistema.
        """
        count = ProductionCavityConfig.objects.count()
        return max(4, count)

    @classmethod
    def get_compatible_bladders(cls, matrix_catalog: ProductionMatrixCatalog) -> Dict[str, Any]:
        """
        Identifica os bladders compatíveis pela MEDIDA/TAMANHO da matriz.
        """
        if not matrix_catalog:
            return {"bladders": [], "warning": "Matriz não informada", "auto_selected": None}

        size_obj = matrix_catalog.medida_size
        size_str = matrix_catalog.medida_str

        qs = ProductionBladder.objects.filter(ativo=True)
        if size_obj:
            qs = qs.filter(medidas=size_obj)
        elif size_str:
            qs = qs.filter(medidas__medida__iexact=size_str)
        else:
            qs = ProductionBladder.objects.none()

        bladders = list(qs.distinct().order_by("codigo_bladder"))
        warning = None
        auto_selected = None

        if not bladders:
            warning = "BLADDER NÃO CADASTRADO PARA ESTA MEDIDA"
        elif len(bladders) == 1:
            auto_selected = bladders[0]
        else:
            warning = f"ERRO DE CONFIGURAÇÃO: Encontrados {len(bladders)} bladders ativos para a medida '{size_str or size_obj}'. Corrija no Admin."
            logger.warning(warning)
            auto_selected = None

        return {
            "bladders": bladders,
            "warning": warning,
            "auto_selected": auto_selected,
        }

    @classmethod
    def _build_shift_windows(cls, start_dt, shift_choice, days_ahead=60) -> List[Dict[str, Any]]:
        """
        Gera janelas de turno autorizadas (A, B ou Ambos).
        """
        from datetime import datetime, time, timedelta

        if timezone.is_naive(start_dt):
            tz = timezone.get_current_timezone()
            start_dt = timezone.make_aware(start_dt, tz)
        tz = start_dt.tzinfo

        shifts = list(ProductionShift.objects.filter(ativo=True).order_by("ordem_exibicao"))
        shift_a = next((s for s in shifts if "1" in s.nome or "A" in s.nome.upper()), shifts[0] if shifts else None)
        shift_b = next((s for s in shifts if "2" in s.nome or "B" in s.nome.upper()), shifts[1] if len(shifts) > 1 else shift_a)

        if not shift_a:
            shift_a, _ = ProductionShift.objects.get_or_create(
                nome="Turno A",
                defaults={"horario_inicial": time(6, 0), "horario_final": time(18, 0), "ordem_exibicao": 1, "ativo": True}
            )
        if not shift_b:
            shift_b, _ = ProductionShift.objects.get_or_create(
                nome="Turno B",
                defaults={"horario_inicial": time(18, 0), "horario_final": time(6, 0), "ordem_exibicao": 2, "ativo": True}
            )

        windows = []
        base_date = start_dt.date() - timedelta(days=1)

        for d in range(days_ahead + 5):
            cur_date = base_date + timedelta(days=d)

            # Turno A: 06:00 -> 18:00
            w_a_start = timezone.make_aware(datetime.combine(cur_date, time(6, 0)), tz)
            w_a_end = timezone.make_aware(datetime.combine(cur_date, time(18, 0)), tz)

            # Turno B: 18:00 -> 06:00 do dia seguinte
            w_b_start = timezone.make_aware(datetime.combine(cur_date, time(18, 0)), tz)
            w_b_end = timezone.make_aware(datetime.combine(cur_date + timedelta(days=1), time(6, 0)), tz)

            if shift_choice in ["A", "AMBOS"] and shift_a:
                windows.append({"shift": shift_a, "date": cur_date, "start": w_a_start, "end": w_a_end})
            if shift_choice in ["B", "AMBOS"] and shift_b:
                windows.append({"shift": shift_b, "date": cur_date, "start": w_b_start, "end": w_b_end})

        windows.sort(key=lambda w: w["start"])
        return windows

    @classmethod
    def calculate_plan(
        cls,
        matrix_catalog: ProductionMatrixCatalog,
        start_dt,
        quantity: int,
        shift_choice: str = "AMBOS",
        cavities: int = 1,
        custom_interval: Optional[int] = None,
        custom_lixo_pct: Optional[float] = None,
        custom_ia_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Motor determinístico de cálculo de Programação PCP com aritmética O(1) ultra-rápida.
        """
        import math
        from datetime import datetime, time, timedelta

        if quantity <= 0:
            raise ValueError("A quantidade programada deve ser maior que zero.")

        if cavities <= 0:
            cavities = 1

        settings = cls.get_pcp_settings()
        t_interv = custom_interval if custom_interval is not None else settings["intervalo_operacional_segundos"]
        lixo_pct = custom_lixo_pct if custom_lixo_pct is not None else settings["perda_lixo_percentual"]
        ia_pct = custom_ia_pct if custom_ia_pct is not None else settings["perda_ia_percentual"]

        t_prod = matrix_catalog.tempo_producao_segundos or 760
        m_cycles = math.ceil(quantity / cavities)
        t_cycle = t_prod + t_interv

        if timezone.is_naive(start_dt):
            tz = timezone.get_current_timezone()
            start_dt = timezone.make_aware(start_dt, tz)
        else:
            tz = start_dt.tzinfo

        shift_breakdown_map = {}

        if shift_choice == "AMBOS":
            # Operação contínua 24h sem interrupção de turnos
            total_seconds = m_cycles * t_prod + (m_cycles - 1) * t_interv
            final_dt = start_dt + timedelta(seconds=total_seconds)

            days_needed = math.ceil(total_seconds / 86400.0)
            preview_days = min(days_needed + 5, 180)
            windows = cls._build_shift_windows(start_dt, "AMBOS", days_ahead=preview_days)

            for w in windows:
                if w["end"] <= start_dt:
                    continue
                if w["start"] > final_dt:
                    break

                s_sec = (w["start"] - start_dt).total_seconds()
                e_sec = (w["end"] - start_dt).total_seconds()

                k1 = math.ceil((s_sec - t_prod) / t_cycle)
                if k1 < 0:
                    k1 = 0

                k2 = math.floor((e_sec - t_prod) / t_cycle)
                if k2 >= m_cycles:
                    k2 = m_cycles - 1

                if k1 <= k2:
                    if k1 <= m_cycles - 1 <= k2:
                        tires_in_win = (m_cycles - 1 - k1) * cavities + (quantity - (m_cycles - 1) * cavities)
                    else:
                        tires_in_win = (k2 - k1 + 1) * cavities

                    if tires_in_win > 0:
                        key = (w["date"], w["shift"])
                        shift_breakdown_map[key] = shift_breakdown_map.get(key, 0) + tires_in_win
        else:
            # Operação restrita a um único turno (Turno A ou B: 12 horas úteis por dia)
            window_duration = 43200.0
            c_full = 1 + math.floor((window_duration - t_prod) / t_cycle)
            if c_full <= 0:
                raise ValueError("O tempo de produção é superior à duração da janela de turno.")

            windows_all = cls._build_shift_windows(start_dt, shift_choice, days_ahead=3)
            # Encontrar primeiro início válido
            curr_time = start_dt
            first_win = None
            for w in windows_all:
                if curr_time < w["end"]:
                    first_win = w
                    break

            if first_win and curr_time < first_win["start"]:
                curr_time = first_win["start"]

            avail_first = (first_win["end"] - curr_time).total_seconds() if first_win else 0
            c_first = (1 + math.floor((avail_first - t_prod) / t_cycle)) if avail_first >= t_prod else 0

            if m_cycles <= c_first:
                used_sec = m_cycles * t_prod + (m_cycles - 1) * t_interv
                final_dt = curr_time + timedelta(seconds=used_sec)
            else:
                rem = m_cycles - c_first
                full_days = math.floor(rem / c_full)
                rem_last = rem % c_full
                if rem_last == 0:
                    full_days -= 1
                    rem_last = c_full

                last_used = rem_last * t_prod + (rem_last - 1) * t_interv
                target_date = first_win["date"] + timedelta(days=1 + full_days)

                if shift_choice == "A":
                    start_last = timezone.make_aware(datetime.combine(target_date, time(6, 0)), tz)
                else:
                    start_last = timezone.make_aware(datetime.combine(target_date, time(18, 0)), tz)

                final_dt = start_last + timedelta(seconds=last_used)

            # Construir visualização de turnos (limitada a 180 dias)
            days_needed = math.ceil(m_cycles / c_full) + 5
            preview_days = min(days_needed, 180)
            windows = cls._build_shift_windows(start_dt, shift_choice, days_ahead=preview_days)

            remaining_cycles = m_cycles
            curr_time_p = start_dt

            for w in windows:
                if remaining_cycles <= 0:
                    break
                if curr_time_p >= w["end"]:
                    continue
                if curr_time_p < w["start"]:
                    curr_time_p = w["start"]

                avail_sec = (w["end"] - curr_time_p).total_seconds()
                if avail_sec < t_prod:
                    continue

                cycles_in_win = 1 + math.floor((avail_sec - t_prod) / t_cycle)
                if cycles_in_win > remaining_cycles:
                    cycles_in_win = remaining_cycles

                start_cycle_idx = m_cycles - remaining_cycles
                end_cycle_idx = start_cycle_idx + cycles_in_win - 1

                if start_cycle_idx <= m_cycles - 1 <= end_cycle_idx:
                    tires_in_win = (m_cycles - 1 - start_cycle_idx) * cavities + (quantity - (m_cycles - 1) * cavities)
                else:
                    tires_in_win = cycles_in_win * cavities

                key = (w["date"], w["shift"])
                shift_breakdown_map[key] = shift_breakdown_map.get(key, 0) + tires_in_win

                used_sec = cycles_in_win * t_prod + (cycles_in_win - 1) * t_interv
                curr_time_p = curr_time_p + timedelta(seconds=used_sec + t_interv)
                remaining_cycles -= cycles_in_win

        # Invariante 1: data/hora final deve ser maior que inicio
        if final_dt <= start_dt:
            raise ValueError("Invariante violada: a data final prevista deve ser estritamente maior que a data de início.")

        # Cálculo de perdas estatísticas (sobre a meta total)
        lixo_est = round(quantity * (lixo_pct / 100.0))
        ia_est = round(quantity * (ia_pct / 100.0))
        perda_tot = lixo_est + ia_est
        boa_est = max(0, quantity - perda_tot)

        # Montar lista amigável para exibição e salvamento
        shift_targets = []
        for (d, s_obj), q in sorted(shift_breakdown_map.items(), key=lambda x: (x[0][0], x[0][1].ordem_exibicao)):
            shift_targets.append({
                "date": d,
                "shift": s_obj,
                "meta_prevista": q,
                "inicio_janela": datetime.combine(d, s_obj.horario_inicial) if hasattr(s_obj, "horario_inicial") else start_dt,
                "fim_janela": datetime.combine(d, s_obj.horario_final) if hasattr(s_obj, "horario_final") else start_dt,
            })

        # Invariante 2: soma das metas por turno deve ser igual a quantity
        total_meta_sum = sum(st["meta_prevista"] for st in shift_targets)
        if total_meta_sum != quantity:
            rem = quantity - total_meta_sum
            if rem > 0 and shift_targets:
                shift_targets[-1]["meta_prevista"] += rem
            elif total_meta_sum != quantity:
                raise ValueError(f"Invariante violada: soma das metas por turno ({total_meta_sum}) difere da quantidade programada ({quantity}).")

        bladder_info = cls.get_compatible_bladders(matrix_catalog)

        return {
            "matriz": matrix_catalog,
            "start_dt": start_dt,
            "quantity": quantity,
            "shift_choice": shift_choice,
            "cavities": cavities,
            "tempo_producao": t_prod,
            "intervalo": t_interv,
            "total_cycles": m_cycles,
            "lixo_pct": lixo_pct,
            "ia_pct": ia_pct,
            "lixo_estimado": lixo_est,
            "ia_estimada": ia_est,
            "perda_total_estimada": perda_tot,
            "producao_boa_estimada": boa_est,
            "final_dt": final_dt,
            "shift_targets": shift_targets,
            "bladder_info": bladder_info,
        }

    @classmethod
    @transaction.atomic
    def save_pcp_plan(
        cls,
        matrix_catalog: ProductionMatrixCatalog,
        start_dt,
        quantity: int,
        shift_choice: str = "AMBOS",
        cavities: int = 1,
        bladder: Optional[ProductionBladder] = None,
        user=None,
        custom_interval: Optional[int] = None,
        custom_lixo_pct: Optional[float] = None,
        custom_ia_pct: Optional[float] = None,
        observacao: str = "",
    ) -> ProductionPCPPlan:
        """
        Calcula e persiste a Programação PCP com snapshots e gera os registros de compatibilidade em ProductionTarget.
        """
        calc = cls.calculate_plan(
            matrix_catalog=matrix_catalog,
            start_dt=start_dt,
            quantity=quantity,
            shift_choice=shift_choice,
            cavities=cavities,
            custom_interval=custom_interval,
            custom_lixo_pct=custom_lixo_pct,
            custom_ia_pct=custom_ia_pct,
        )

        if not bladder and calc["bladder_info"]["auto_selected"]:
            bladder = calc["bladder_info"]["auto_selected"]

        plan = ProductionPCPPlan.objects.create(
            matriz=matrix_catalog,
            data_hora_inicio=calc["start_dt"],
            quantidade_programada=quantity,
            turno_opcao=shift_choice,
            cavidades_disponiveis=cavities,
            bladder=bladder,
            tempo_producao_utilizado=calc["tempo_producao"],
            intervalo_utilizado=calc["intervalo"],
            perda_lixo_pct_utilizada=calc["lixo_pct"],
            perda_ia_pct_utilizada=calc["ia_pct"],
            lixo_estimado=calc["lixo_estimado"],
            ia_estimada=calc["ia_estimada"],
            perda_total_estimada=calc["perda_total_estimada"],
            producao_boa_estimada=calc["producao_boa_estimada"],
            data_hora_fim_prevista=calc["final_dt"],
            status="PLANEJADO",
            observacao=observacao,
            created_by=user if user and user.is_authenticated else None,
        )

        # Criar detalhamento por turno e integrar com ProductionTarget
        for st in calc["shift_targets"]:
            d_val = st["date"]
            s_obj = st["shift"]
            meta_val = st["meta_prevista"]

            # Compatibilidade com dashboard legado (ProductionTarget)
            t_obj, _ = ProductionTarget.objects.update_or_create(
                date=d_val,
                shift=s_obj,
                matrix_catalog=matrix_catalog,
                defaults={
                    "matriz_codigo": matrix_catalog.codigo,
                    "produto": matrix_catalog.nome_exibicao,
                    "planned_quantity": meta_val,
                    "status": "PLANEJADA",
                    "observation": f"Gerado automaticamente pelo PCP Plan #{plan.id}",
                    "created_by": user if user and user.is_authenticated else None,
                }
            )

            ProductionPCPPlanShiftTarget.objects.create(
                pcp_plan=plan,
                date=d_val,
                shift=s_obj,
                data_hora_inicio_janela=calc["start_dt"],
                data_hora_fim_janela=calc["final_dt"],
                meta_prevista=meta_val,
                target_legado=t_obj,
            )

        ProductionPCPPlanHistory.objects.create(
            pcp_plan=plan,
            user=user if user and getattr(user, "is_authenticated", False) else None,
            action_type="CRIACAO",
            quantity_before=None,
            quantity_after=quantity,
            shift_choice_before=None,
            shift_choice_after=shift_choice,
            cavities_before=None,
            cavities_after=cavities,
            final_dt_before=None,
            final_dt_after=calc["final_dt"],
            reason="Criação da programação PCP."
        )

        return plan

    @classmethod
    def resolve_pcp_target_for_cavity(cls, cavity, machine_config, mat_catalog, matriz_val, shift_obj, current_dt=None):
        """
        Resolve a meta PCP do turno para uma cavidade específica com distribuição justa entre cavidades participantes.
        """
        if not current_dt:
            current_dt = timezone.now()
        current_date = current_dt.date()

        if not mat_catalog and matriz_val and matriz_val not in ["Não informada", "", "None"]:
            mat_catalog = ProductionMatrixCatalog.objects.filter(
                Q(codigo__iexact=matriz_val) |
                Q(nome_scada__iexact=matriz_val) |
                Q(nome_exibicao__iexact=matriz_val) |
                Q(produto__iexact=matriz_val)
            ).first()

        if not mat_catalog:
            return {"is_pcp": False, "meta_turno": 0}

        plans = ProductionPCPPlan.objects.filter(
            matriz=mat_catalog,
            status__in=["PLANEJADO", "EM_PRODUCAO"]
        ).order_by("-id")

        active_plan = None
        for plan in plans:
            if plan.data_hora_inicio <= current_dt <= plan.data_hora_fim_prevista:
                active_plan = plan
                break
            if shift_obj:
                has_st = ProductionPCPPlanShiftTarget.objects.filter(
                    pcp_plan=plan,
                    date=current_date,
                    shift=shift_obj
                ).exists()
                if has_st:
                    active_plan = plan
                    break

        if not active_plan:
            return {"is_pcp": False, "meta_turno": 0}

        st = None
        if shift_obj:
            st = ProductionPCPPlanShiftTarget.objects.filter(
                pcp_plan=active_plan,
                date=current_date,
                shift=shift_obj
            ).first()

        if not st:
            st = ProductionPCPPlanShiftTarget.objects.filter(
                pcp_plan=active_plan,
                data_hora_inicio_janela__lte=current_dt,
                data_hora_fim_janela__gte=current_dt
            ).first()

        if not st:
            return {"is_pcp": False, "meta_turno": 0}

        meta_turno_total = st.meta_prevista
        cavidades_previstas = active_plan.cavidades_disponiveis

        matching_cavities = []
        if machine_config:
            all_cavs = list(machine_config.cavities.all().order_by("ordem", "id"))
            for c in all_cavs:
                c_mat = getattr(c, "xid_matriz", "") or ""
                if c_mat and (c_mat.strip().lower() == str(mat_catalog.codigo_scada).lower() or
                              c_mat.strip().lower() in mat_catalog.nome_exibicao.lower() or
                              c_mat.strip().lower() == mat_catalog.codigo.lower() or
                              (matriz_val and c_mat.strip().lower() == matriz_val.strip().lower())):
                    matching_cavities.append(c)

        if not matching_cavities:
            matching_cavities = [cavity]

        n_detectadas = len(matching_cavities)
        n_participantes = min(n_detectadas, cavidades_previstas)
        if n_participantes < 1:
            n_participantes = 1

        try:
            cav_index = [c.id for c in matching_cavities].index(cavity.id)
        except ValueError:
            cav_index = 0

        if cav_index < n_participantes:
            base_meta = meta_turno_total // n_participantes
            resto = meta_turno_total % n_participantes
            meta_cavidade = base_meta + (1 if cav_index < resto else 0)
        else:
            meta_cavidade = 0

        pcp_divergencia = None
        if n_detectadas != cavidades_previstas:
            pcp_divergencia = f"PCP prevê {cavidades_previstas} cavidade(s); {n_detectadas} detectada(s)."

        return {
            "is_pcp": True,
            "meta_turno": meta_cavidade,
            "meta_total_turno": meta_turno_total,
            "pcp_plan_id": active_plan.id,
            "pcp_divergencia": pcp_divergencia
        }

    @classmethod
    def get_plan_realized_quantity(cls, plan) -> int:
        """
        Calcula a quantidade acumulada produzida para um plano PCP.
        """
        if not plan or not plan.matriz:
            return 0
        code_scada = plan.matriz.codigo_scada
        sts = plan.shift_targets.all()
        if not sts:
            return 0

        total_realized = 0
        for st in sts:
            accs = ProductionShiftAccumulated.objects.filter(
                date=st.date,
                shift=st.shift
            )
            for acc in accs:
                if acc.matriz and (str(code_scada) in str(acc.matriz) or plan.matriz.nome_exibicao in str(acc.matriz)):
                    total_realized += acc.quantity_accumulated
        return total_realized

    @classmethod
    def edit_unstarted_pcp_plan(cls, plan, matrix_catalog, start_dt, quantity, shift_choice, cavities, user=None, reason=None):
        """
        Edita uma programação PCP não iniciada recalulando integralmente perdas, término e metas de turno.
        """
        from django.db import transaction

        with transaction.atomic(using="default"):
            plan_locked = ProductionPCPPlan.objects.select_for_update().get(pk=plan.pk)

            qty_before = plan_locked.quantidade_programada
            shift_before = plan_locked.turno_opcao
            cavities_before = plan_locked.cavidades_disponiveis
            final_dt_before = plan_locked.data_hora_fim_prevista

            calc = cls.calculate_plan(matrix_catalog, start_dt, quantity, shift_choice, cavities)

            for st in list(plan_locked.shift_targets.all()):
                if st.target_legado:
                    st.target_legado.delete()
                st.delete()

            plan_locked.matriz = matrix_catalog
            plan_locked.data_hora_inicio = start_dt
            plan_locked.quantidade_programada = quantity
            plan_locked.turno_opcao = shift_choice
            plan_locked.cavidades_disponiveis = cavities
            if calc["bladder_info"]["auto_selected"]:
                plan_locked.bladder = calc["bladder_info"]["auto_selected"]
            plan_locked.tempo_producao_utilizado = calc["tempo_producao"]
            plan_locked.lixo_estimado = calc["lixo_estimado"]
            plan_locked.ia_estimada = calc["ia_estimada"]
            plan_locked.perda_total_estimada = calc["perda_total_estimada"]
            plan_locked.producao_boa_estimada = calc["producao_boa_estimada"]
            plan_locked.data_hora_fim_prevista = calc["final_dt"]
            plan_locked.updated_by = user if user and getattr(user, "is_authenticated", False) else None
            plan_locked.save()

            for st in calc["shift_targets"]:
                d_val = st["date"]
                s_obj = st["shift"]
                meta_val = st["meta_prevista"]

                t_obj, _ = ProductionTarget.objects.update_or_create(
                    date=d_val,
                    shift=s_obj,
                    matrix_catalog=matrix_catalog,
                    defaults={
                        "matriz_codigo": matrix_catalog.codigo,
                        "produto": matrix_catalog.nome_exibicao,
                        "planned_quantity": meta_val,
                        "status": "PLANEJADA",
                        "observation": f"Gerado automaticamente pelo PCP Plan #{plan_locked.id}",
                        "created_by": user if user and getattr(user, "is_authenticated", False) else None,
                    }
                )

                ProductionPCPPlanShiftTarget.objects.create(
                    pcp_plan=plan_locked,
                    date=d_val,
                    shift=s_obj,
                    data_hora_inicio_janela=start_dt,
                    data_hora_fim_janela=calc["final_dt"],
                    meta_prevista=meta_val,
                    target_legado=t_obj,
                )

            ProductionPCPPlanHistory.objects.create(
                pcp_plan=plan_locked,
                user=user if user and getattr(user, "is_authenticated", False) else None,
                action_type="EDICAO",
                quantity_before=qty_before,
                quantity_after=quantity,
                shift_choice_before=shift_before,
                shift_choice_after=shift_choice,
                cavities_before=cavities_before,
                cavities_after=cavities,
                final_dt_before=final_dt_before,
                final_dt_after=calc["final_dt"],
                reason=reason or "Edição de programação não iniciada."
            )

            return plan_locked

    @classmethod
    def edit_started_pcp_plan(cls, plan, new_quantity, new_shift_choice, new_cavities, user=None, reason=None):
        """
        Edita uma programação em andamento preservando o histórico de produção já realizada.
        """
        from django.db import transaction

        with transaction.atomic(using="default"):
            plan_locked = ProductionPCPPlan.objects.select_for_update().get(pk=plan.pk)

            qty_before = plan_locked.quantidade_programada
            shift_before = plan_locked.turno_opcao
            cavities_before = plan_locked.cavidades_disponiveis
            final_dt_before = plan_locked.data_hora_fim_prevista

            now = timezone.now()
            realized_qty = cls.get_plan_realized_quantity(plan_locked)
            remaining_qty = max(0, new_quantity - realized_qty)

            future_targets = plan_locked.shift_targets.filter(data_hora_inicio_janela__gte=now)
            for st in list(future_targets):
                if st.target_legado:
                    st.target_legado.delete()
                st.delete()

            if remaining_qty > 0:
                recalc_start = now
                calc = cls.calculate_plan(
                    matrix_catalog=plan_locked.matriz,
                    start_dt=recalc_start,
                    quantity=remaining_qty,
                    shift_choice=new_shift_choice,
                    cavities=new_cavities
                )
                new_final_dt = calc["final_dt"]

                for st in calc["shift_targets"]:
                    d_val = st["date"]
                    s_obj = st["shift"]
                    meta_val = st["meta_prevista"]

                    t_obj, _ = ProductionTarget.objects.update_or_create(
                        date=d_val,
                        shift=s_obj,
                        matrix_catalog=plan_locked.matriz,
                        defaults={
                            "matriz_codigo": plan_locked.matriz.codigo,
                            "produto": plan_locked.matriz.nome_exibicao,
                            "planned_quantity": meta_val,
                            "status": "PLANEJADA",
                            "observation": f"Gerado automaticamente pelo PCP Plan #{plan_locked.id} (recalculado)",
                            "created_by": user if user and getattr(user, "is_authenticated", False) else None,
                        }
                    )

                    ProductionPCPPlanShiftTarget.objects.update_or_create(
                        pcp_plan=plan_locked,
                        date=d_val,
                        shift=s_obj,
                        defaults={
                            "data_hora_inicio_janela": recalc_start,
                            "data_hora_fim_janela": new_final_dt,
                            "meta_prevista": meta_val,
                            "target_legado": t_obj,
                        }
                    )
            else:
                new_final_dt = now

            plan_locked.quantidade_programada = new_quantity
            plan_locked.turno_opcao = new_shift_choice
            plan_locked.cavidades_disponiveis = new_cavities
            plan_locked.data_hora_fim_prevista = new_final_dt
            plan_locked.updated_by = user if user and getattr(user, "is_authenticated", False) else None
            plan_locked.save()

            ProductionPCPPlanHistory.objects.create(
                pcp_plan=plan_locked,
                user=user if user and getattr(user, "is_authenticated", False) else None,
                action_type="EDICAO",
                quantity_before=qty_before,
                quantity_after=new_quantity,
                shift_choice_before=shift_before,
                shift_choice_after=new_shift_choice,
                cavities_before=cavities_before,
                cavities_after=new_cavities,
                final_dt_before=final_dt_before,
                final_dt_after=new_final_dt,
                reason=reason or f"Edição de plano em andamento (Realizado: {realized_qty}, Saldo recalculado: {remaining_qty})."
            )

            return plan_locked

    @classmethod
    def cancel_pcp_plan(cls, plan, user=None, reason=None):
        """
        Cancela um plano PCP em andamento preservando todo o histórico.
        """
        from django.db import transaction

        with transaction.atomic(using="default"):
            plan_locked = ProductionPCPPlan.objects.select_for_update().get(pk=plan.pk)
            plan_locked.status = "CANCELADO"
            plan_locked.updated_by = user if user and getattr(user, "is_authenticated", False) else None
            plan_locked.save()

            for st in plan_locked.shift_targets.all():
                if st.target_legado:
                    st.target_legado.status = "CANCELADO"
                    st.target_legado.save()

            ProductionPCPPlanHistory.objects.create(
                pcp_plan=plan_locked,
                user=user if user and getattr(user, "is_authenticated", False) else None,
                action_type="CANCELAMENTO",
                quantity_before=plan_locked.quantidade_programada,
                quantity_after=plan_locked.quantidade_programada,
                reason=reason or "Programação cancelada."
            )

            return plan_locked

    @classmethod
    def delete_pcp_plan(cls, plan, user=None, reason=None):
        """
        Exclui fisicamente um plano PCP que NUNCA iniciou e não possui produção real associada.
        """
        from django.db import transaction

        with transaction.atomic(using="default"):
            plan_locked = ProductionPCPPlan.objects.select_for_update().get(pk=plan.pk)
            realized = cls.get_plan_realized_quantity(plan_locked)
            now = timezone.now()

            if plan_locked.status != "PLANEJADO" and (plan_locked.data_hora_inicio <= now or realized > 0):
                raise ValueError("Esta programação já iniciou ou possui produção realizada. Use a opção Cancelar.")

            for st in list(plan_locked.shift_targets.all()):
                if st.target_legado:
                    st.target_legado.delete()
                st.delete()

            plan_locked.delete()
            return True


class BladderTrackingService:
    @classmethod
    def get_active_bladders_context(cls, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retorna a lista de todos os bladders atualmente em uso nas cavidades configuradas,
        com cálculo de % de vida útil, tempo em uso, matriz instalada e status de compatibilidade.
        """
        if filters is None:
            filters = {}

        q_search = filters.get("q", "").strip().lower()
        prensa_filter = filters.get("prensa_id", "").strip()
        setup_filter = filters.get("setup_status", "").strip().upper()
        near_limit_only = filters.get("near_limit", "") == "1"

        cavities_qs = (
            ProductionCavityConfig.objects.select_related(
                "machine_config", "machine_config__machine", "machine_config__machine__setor"
            )
            .order_by("machine_config__ordem_exibicao", "machine_config__machine__nome", "ordem", "nome")
        )

        now = timezone.now()

        # Buscar todos os usos ativos
        active_usages = {
            u.cavity_config_id: u
            for u in ProductionBladderUsage.objects.filter(status="EM_USO", ended_at__isnull=True).select_related(
                "cavity_config", "cavity_config__machine_config", "cavity_config__machine_config__machine"
            )
        }

        # Obter últimos valores do SCADA
        all_fetch_xids = []
        for cav in cavities_qs:
            if cav.xid_matriz:
                all_fetch_xids.append(cav.xid_matriz)
            if cav.xid_bla_real:
                all_fetch_xids.append(cav.xid_bla_real)
            if cav.xid_produto:
                all_fetch_xids.append(cav.xid_produto)
            if cav.xid_lote_bladder:
                all_fetch_xids.append(cav.xid_lote_bladder)
            if cav.xid_meta:
                all_fetch_xids.append(cav.xid_meta)

        scada_values = scada_reader.get_last_values_batch(all_fetch_xids)

        bladders_data = []
        total_em_uso = 0
        total_atencao = 0
        total_critico = 0
        total_incorreto = 0

        for cav in cavities_qs:
            usage = active_usages.get(cav.id)

            # Leituras atuais
            mat_entry = scada_values.get(cav.xid_matriz) if cav.xid_matriz else None
            raw_mat = str(mat_entry.get("str_value", mat_entry.get("value", ""))).strip() if mat_entry else ""
            mat_info = resolve_matrix_product_display(raw_mat)

            bla_entry = scada_values.get(cav.xid_bla_real) if cav.xid_bla_real else None
            raw_bla = str(bla_entry.get("str_value", bla_entry.get("value", ""))).strip() if bla_entry else ""
            norm_bla = normalize_bladder_code(raw_bla) or (usage.codigo_bla_real if usage else "")

            prod_entry = scada_values.get(cav.xid_produto) if cav.xid_produto else None
            prod_val = str(prod_entry.get("str_value", prod_entry.get("value", ""))).strip() if prod_entry else (usage.lote_prefixo if usage else "")

            lote_entry = scada_values.get(cav.xid_lote_bladder) if cav.xid_lote_bladder else None
            lote_val = str(lote_entry.get("str_value", lote_entry.get("value", ""))).strip() if lote_entry else (usage.lote_numero if usage else "")

            lot_info = compose_bladder_lot(prod_val, lote_val)
            lot_display = lot_info["display"] if lot_info["status"] != "AUSENTE" else (usage.lote_completo_snapshot if usage else "Não informado")

            passadas = usage.passadas_acumuladas if usage else 0
            limite = usage.limite_vida_snapshot if usage and usage.limite_vida_snapshot else None
            if limite is None and cav.xid_meta:
                meta_entry = scada_values.get(cav.xid_meta)
                if meta_entry and isinstance(meta_entry.get("value"), (int, float)) and meta_entry["value"] > 0:
                    limite = int(meta_entry["value"])

            pct_vida = round((passadas / limite * 100), 1) if limite and limite > 0 else None

            # Faixas visuais de vida útil
            if pct_vida is None:
                vida_badge = "secondary"
                vida_status = "INDETERMINADO"
                vida_label = "Limite não informado"
            elif pct_vida < 80.0:
                vida_badge = "success"
                vida_status = "NORMAL"
                vida_label = f"{pct_vida}%"
            elif pct_vida < 95.0:
                vida_badge = "warning"
                vida_status = "ATENCAO"
                vida_label = f"{pct_vida}%"
                total_atencao += 1
            else:
                vida_badge = "danger"
                vida_status = "CRITICO"
                vida_label = f"{pct_vida}%"
                total_critico += 1

            # Validação de setup
            expected_bladders = get_expected_bladders_for_matrix(raw_mat)
            if not norm_bla or not mat_info["matrix_identified"]:
                setup_status = "NAO_VERIFICAVEL"
                setup_label = "Não Verificado"
                setup_badge = "secondary"
                setup_icon = "bi-question-circle"
            elif not expected_bladders:
                setup_status = "NAO_VERIFICAVEL"
                setup_label = "Sem BLA Cadastrado"
                setup_badge = "secondary"
                setup_icon = "bi-exclamation-circle"
            elif norm_bla in expected_bladders:
                setup_status = "CORRETO"
                setup_label = "✓ Setup Correto"
                setup_badge = "success"
                setup_icon = "bi-check-circle-fill"
            else:
                setup_status = "INCORRETO"
                setup_label = "Setup Incorreto"
                setup_badge = "danger"
                setup_icon = "bi-x-circle-fill"
                total_incorreto += 1

            if usage:
                total_em_uso += 1
                tempo_segundos = max(0, int((now - usage.started_at).total_seconds()))
                tempo_str = ProductionStateService.format_elapsed_seconds(tempo_segundos)
                inicio_str = usage.started_at.strftime("%d/%m/%Y %H:%M")
            else:
                tempo_str = "—"
                inicio_str = "Sem registro"

            p_id = cav.machine_config.machine.id if cav.machine_config and cav.machine_config.machine else 0
            p_nome = cav.machine_config.machine.nome if cav.machine_config and cav.machine_config.machine else "Prensa"

            item = {
                "usage_id": usage.id if usage else None,
                "cavity_id": cav.id,
                "prensa_id": p_id,
                "prensa_nome": p_nome,
                "cavidade_nome": cav.nome,
                "codigo_bla": norm_bla or "Não informado",
                "raw_bla": raw_bla,
                "lote_completo": lot_display,
                "matriz_nome": mat_info["display"],
                "matriz_raw": raw_mat,
                "passadas": passadas,
                "limite": limite,
                "limite_str": str(limite) if limite else "Não informado",
                "pct_vida": pct_vida,
                "pct_bar": min(100, max(0, round(pct_vida))) if pct_vida is not None else 0,
                "vida_badge": vida_badge,
                "vida_label": vida_label,
                "vida_status": vida_status,
                "setup_status": setup_status,
                "setup_label": setup_label,
                "setup_badge": setup_badge,
                "setup_icon": setup_icon,
                "expected_bladders": ", ".join(expected_bladders) if expected_bladders else "N/A",
                "inicio_str": inicio_str,
                "tempo_uso_str": tempo_str,
                "has_usage": bool(usage),
            }

            # Filtros em memória
            if q_search:
                match_bla = q_search in (norm_bla or "").lower()
                match_lote = q_search in (lot_display or "").lower()
                match_prensa = q_search in p_nome.lower()
                if not (match_bla or match_lote or match_prensa):
                    continue

            if prensa_filter and prensa_filter.isdigit():
                if p_id != int(prensa_filter):
                    continue

            if setup_filter:
                if setup_status != setup_filter:
                    continue

            if near_limit_only:
                if pct_vida is None or pct_vida < 80.0:
                    continue

            bladders_data.append(item)

        machines = Machine.objects.filter(production_config__isnull=False).order_by("nome")

        return {
            "bladders": bladders_data,
            "total_em_uso": total_em_uso,
            "total_atencao": total_atencao,
            "total_critico": total_critico,
            "total_incorreto": total_incorreto,
            "machines": machines,
            "filters": {
                "q": filters.get("q", ""),
                "prensa_id": prensa_filter,
                "setup_status": setup_filter,
                "near_limit": filters.get("near_limit", ""),
            },
            "last_updated_str": now.strftime("%d/%m/%Y %H:%M:%S"),
        }

    @classmethod
    def get_bladder_history_context(cls, filters: Optional[Dict[str, Any]] = None, page: Any = 1) -> Dict[str, Any]:
        """
        Retorna o histórico de utilizações de bladders com sobreposição temporal de período,
        filtros por prensa, cavidade, BLA, lote, motivo de troca, paginação backend e KPIs consolidados.
        """
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

        if filters is None:
            filters = {}

        now = timezone.now()

        # Resolução de intervalo de datas (default: últimos 30 dias)
        data_ini_str = filters.get("data_inicio", "").strip()
        data_fim_str = filters.get("data_fim", "").strip()

        def parse_dt(dt_str, is_end=False):
            if not dt_str:
                return None
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    if timezone.is_naive(dt):
                        if is_end and fmt == "%Y-%m-%d":
                            dt = dt.replace(hour=23, minute=59, second=59)
                        dt = timezone.make_aware(dt)
                    return dt
                except ValueError:
                    pass
            return None

        start_dt = parse_dt(data_ini_str, is_end=False)
        end_dt = parse_dt(data_fim_str, is_end=True)

        if not start_dt:
            start_dt = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        if not end_dt:
            end_dt = now

        # Regra de sobreposição temporal
        qs = ProductionBladderUsage.objects.select_related(
            "cavity_config", "cavity_config__machine_config", "cavity_config__machine_config__machine"
        ).filter(
            Q(started_at__lte=end_dt) & (Q(ended_at__isnull=True) | Q(ended_at__gte=start_dt))
        )

        bla_filter = filters.get("bla", "").strip().upper()
        if bla_filter:
            norm_filter = normalize_bladder_code(bla_filter) or bla_filter
            qs = qs.filter(codigo_bla_real__icontains=norm_filter)

        lote_filter = filters.get("lote", "").strip()
        if lote_filter:
            qs = qs.filter(lote_completo_snapshot__icontains=lote_filter)

        prensa_filter = filters.get("prensa_id", "").strip()
        if prensa_filter and prensa_filter.isdigit():
            qs = qs.filter(cavity_config__machine_config__machine_id=int(prensa_filter))

        cavidade_filter = filters.get("cavidade_id", "").strip()
        if cavidade_filter and cavidade_filter.isdigit():
            qs = qs.filter(cavity_config_id=int(cavidade_filter))

        motivo_filter = filters.get("motivo_troca", "").strip()
        if motivo_filter and motivo_filter.isdigit():
            qs = qs.filter(motivo_troca=int(motivo_filter))

        status_filter = filters.get("status", "").strip().upper()
        if status_filter in ["EM_USO", "FINALIZADO"]:
            qs = qs.filter(status=status_filter)

        qs = qs.order_by("-started_at")

        # KPIs do Período Filtrado
        all_records = list(qs)
        total_utilizacoes = len(all_records)
        total_passadas = sum(r.passadas_acumuladas for r in all_records)
        bladders_em_uso = sum(1 for r in all_records if r.status == "EM_USO")
        total_trocas = sum(1 for r in all_records if r.status == "FINALIZADO")
        media_passadas = round(total_passadas / total_utilizacoes) if total_utilizacoes > 0 else 0

        # Breakdown de motivos de troca
        reason_counts = {}
        for r in all_records:
            if r.status == "FINALIZADO" and r.motivo_troca > 0:
                label = r.get_motivo_troca_display()
                reason_counts[label] = reason_counts.get(label, 0) + 1

        principal_motivo = max(reason_counts, key=reason_counts.get) if reason_counts else "Nenhum no período"
        motivos_breakdown = [
            {"motivo": k, "qtd": v, "pct": round(v / total_trocas * 100, 1) if total_trocas > 0 else 0}
            for k, v in sorted(reason_counts.items(), key=lambda x: -x[1])
        ]

        # Paginação no Backend (15 por página)
        paginator = Paginator(qs, 15)
        try:
            page_obj = paginator.page(page)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # Montagem dos itens da página
        items_data = []
        for u in page_obj:
            dur_end = u.ended_at or now
            dur_secs = max(0, int((dur_end - u.started_at).total_seconds()))
            dur_str = ProductionStateService.format_elapsed_seconds(dur_secs)

            pct_vida = round((u.passadas_acumuladas / u.limite_vida_snapshot * 100), 1) if u.limite_vida_snapshot and u.limite_vida_snapshot > 0 else None
            if pct_vida is None:
                vida_badge = "secondary"
            elif pct_vida < 80.0:
                vida_badge = "success"
            elif pct_vida < 95.0:
                vida_badge = "warning"
            else:
                vida_badge = "danger"

            items_data.append({
                "id": u.id,
                "codigo_bla": u.codigo_bla_real,
                "lote_completo": u.lote_completo_snapshot,
                "prensa_nome": u.machine_name_snapshot or (u.cavity_config.machine_config.machine.nome if u.cavity_config and u.cavity_config.machine_config else "Prensa"),
                "cavidade_nome": u.cavity_name_snapshot or (u.cavity_config.nome if u.cavity_config else "Cavidade"),
                "passadas": u.passadas_acumuladas,
                "limite": u.limite_vida_snapshot or "—",
                "pct_vida": pct_vida,
                "vida_badge": vida_badge,
                "started_at_str": u.started_at.strftime("%d/%m/%Y %H:%M"),
                "ended_at_str": u.ended_at.strftime("%d/%m/%Y %H:%M") if u.ended_at else "Em uso",
                "duracao_str": dur_str,
                "motivo_troca_display": u.get_motivo_troca_display(),
                "motivo_troca_code": u.motivo_troca,
                "status_display": u.get_status_display(),
                "is_active": (u.status == "EM_USO"),
            })

        # Preservação de querystring
        query_params = []
        if data_ini_str:
            query_params.append(f"data_inicio={data_ini_str}")
        if data_fim_str:
            query_params.append(f"data_fim={data_fim_str}")
        if bla_filter:
            query_params.append(f"bla={bla_filter}")
        if lote_filter:
            query_params.append(f"lote={lote_filter}")
        if prensa_filter:
            query_params.append(f"prensa_id={prensa_filter}")
        if cavidade_filter:
            query_params.append(f"cavidade_id={cavidade_filter}")
        if motivo_filter:
            query_params.append(f"motivo_troca={motivo_filter}")
        if status_filter:
            query_params.append(f"status={status_filter}")

        querystring = "&".join(query_params)
        machines = Machine.objects.filter(production_config__isnull=False).order_by("nome")
        reasons_list = [
            {"code": c.value, "label": c.label} for c in ProductionBladderChangeReason
        ]

        return {
            "page_obj": page_obj,
            "items": items_data,
            "total_utilizacoes": total_utilizacoes,
            "total_passadas": total_passadas,
            "bladders_em_uso": bladders_em_uso,
            "total_trocas": total_trocas,
            "media_passadas": media_passadas,
            "principal_motivo": principal_motivo,
            "motivos_breakdown": motivos_breakdown,
            "machines": machines,
            "reasons": reasons_list,
            "filters": {
                "data_inicio": start_dt.strftime("%Y-%m-%d"),
                "data_fim": end_dt.strftime("%Y-%m-%d"),
                "bla": filters.get("bla", ""),
                "lote": filters.get("lote", ""),
                "prensa_id": prensa_filter,
                "cavidade_id": cavidade_filter,
                "motivo_troca": motivo_filter,
                "status": status_filter,
            },
            "querystring": querystring,
        }

    @classmethod
    def get_bladder_consolidated_detail(
        cls,
        bla_code: Optional[str] = None,
        lot_str: Optional[str] = None,
        usage_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retorna a ficha consolidada detalhada de uma identidade de bladder (BLA + Lote),
        somando todas as passadas de múltiplos segmentos sem duplicação.
        """
        target_usage = None
        if usage_id:
            target_usage = ProductionBladderUsage.objects.filter(pk=usage_id).first()
            if target_usage:
                bla_code = target_usage.codigo_bla_real
                lot_str = target_usage.lote_completo_snapshot

        if not bla_code or not lot_str:
            return None

        norm_bla = normalize_bladder_code(bla_code) or bla_code

        segments_qs = ProductionBladderUsage.objects.select_related(
            "cavity_config", "cavity_config__machine_config", "cavity_config__machine_config__machine"
        ).filter(
            codigo_bla_real=norm_bla,
            lote_completo_snapshot=lot_str
        ).order_by("started_at")

        segments = list(segments_qs)
        if not segments:
            return None

        total_passadas = sum(s.passadas_acumuladas for s in segments)
        primeira_observacao = min(s.started_at for s in segments)
        ultima_observacao = max(s.ended_at or timezone.now() for s in segments)

        active_segment = next((s for s in segments if s.status == "EM_USO"), None)
        is_em_uso = active_segment is not None

        if is_em_uso:
            p_nome = active_segment.machine_name_snapshot or active_segment.cavity_config.machine_config.machine.nome
            c_nome = active_segment.cavity_name_snapshot or active_segment.cavity_config.nome
            situacao_str = f"Em uso na {p_nome} — {c_nome}"
            situacao_badge = "success"
        else:
            situacao_str = "Finalizado / Fora de uso"
            situacao_badge = "secondary"

        limite = next((s.limite_vida_snapshot for s in reversed(segments) if s.limite_vida_snapshot), None)
        pct_total = round((total_passadas / limite * 100), 1) if limite and limite > 0 else None

        if pct_total is None:
            pct_badge = "secondary"
        elif pct_total < 80.0:
            pct_badge = "success"
        elif pct_total < 95.0:
            pct_badge = "warning"
        else:
            pct_badge = "danger"

        now = timezone.now()
        segments_data = []
        for s in segments:
            dur_end = s.ended_at or now
            dur_secs = max(0, int((dur_end - s.started_at).total_seconds()))
            dur_str = ProductionStateService.format_elapsed_seconds(dur_secs)

            segments_data.append({
                "id": s.id,
                "prensa_nome": s.machine_name_snapshot or s.cavity_config.machine_config.machine.nome,
                "cavidade_nome": s.cavity_name_snapshot or s.cavity_config.nome,
                "started_at_str": s.started_at.strftime("%d/%m/%Y %H:%M"),
                "ended_at_str": s.ended_at.strftime("%d/%m/%Y %H:%M") if s.ended_at else "Em andamento",
                "duracao_str": dur_str,
                "passadas": s.passadas_acumuladas,
                "motivo_troca_display": s.get_motivo_troca_display(),
                "status_display": s.get_status_display(),
                "is_active": (s.status == "EM_USO"),
            })

        return {
            "codigo_bla": norm_bla,
            "lote_completo": lot_str,
            "primeira_observacao_str": primeira_observacao.strftime("%d/%m/%Y %H:%M"),
            "ultima_observacao_str": ultima_observacao.strftime("%d/%m/%Y %H:%M"),
            "is_em_uso": is_em_uso,
            "situacao_str": situacao_str,
            "situacao_badge": situacao_badge,
            "total_passadas": total_passadas,
            "limite": limite or "Não informado",
            "pct_total": pct_total,
            "pct_badge": pct_badge,
            "total_instalacoes": len(segments),
            "segments": segments_data,
        }

