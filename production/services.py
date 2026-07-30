import logging
import time
from typing import Dict, List, Any, Optional
from django.db import models, transaction
from django.db.models import Max, Q
from django.utils import timezone
from .models import (
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    ProductionMachineState,
    ProductionDowntimeEvent,
    ScadaDataPoint,
    ScadaPointValue,
    ScadaPointValueAnnotation,
)

logger = logging.getLogger(__name__)


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


class ProductionStateService:
    """
    Serviço agregador e de persistência da máquina de estados do módulo de produção:
    - Carrega configurações de máquinas, cavidades, parâmetros e alarmes.
    - Consulta o Scada-LTS em lote de forma otimizada.
    - Mantém a máquina de estados (Produzindo, Parada, Sem comunicação, Dado desatualizado).
    - Persiste transições de estado de forma idempotente em ProductionMachineState e ProductionDowntimeEvent.
    """

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
    def build_cavities_data(
        cls, config: ProductionMachineConfig, scada_values: Dict[str, Any]
    ) -> tuple[List[Dict[str, Any]], int, int, int, int]:
        cavities_list = []
        total_prod = 0
        total_meta = 0

        for cav in config.cavities.all():
            # Produção atual
            c_prod_entry = scada_values.get(cav.xid_producao) if cav.xid_producao else None
            c_prod = int(c_prod_entry["value"]) if c_prod_entry and isinstance(c_prod_entry.get("value"), (int, float)) else 0

            # Meta manual de produção (fonte do dashboard)
            c_meta = cav.meta_producao_manual or 0

            total_prod += c_prod
            total_meta += c_meta

            percent = round((c_prod / c_meta) * 100) if c_meta > 0 else 0
            percent_bar = min(100, percent) if c_meta > 0 else 0

            # Matriz
            matriz_entry = scada_values.get(cav.xid_matriz) if cav.xid_matriz else None
            matriz_val = str(matriz_entry.get("str_value", "")).strip() if matriz_entry else ""

            # Produto e Lote do Bladder
            prod_entry = scada_values.get(cav.xid_produto) if cav.xid_produto else None
            prod_val = str(prod_entry.get("str_value", "")).strip() if prod_entry else ""

            lote_entry = scada_values.get(cav.xid_lote_bladder) if cav.xid_lote_bladder else None
            lote_val = str(lote_entry.get("str_value", "")).strip() if lote_entry else ""

            # Regras de fallback para produto e lote:
            if prod_val and lote_val:
                produto_lote_str = f"{prod_val} - {lote_val}"
            elif prod_val:
                produto_lote_str = prod_val
            elif lote_val:
                produto_lote_str = f"Lote: {lote_val}"
            else:
                produto_lote_str = "Não informado"

            # Status independente da cavidade
            if cav.xid_status_cavidade and str(cav.xid_status_cavidade).strip():
                status_entry = scada_values.get(cav.xid_status_cavidade)
                if status_entry and status_entry.get("ts") is not None:
                    c_raw_val = str(status_entry.get("str_value", status_entry.get("value", ""))).strip().lower()
                    c_target_val = str(cav.valor_cavidade_produzindo).strip().lower()
                    if c_raw_val == c_target_val:
                        c_status_code = "PRODUZINDO"
                        c_status_label = "Produzindo"
                        c_badge_class = "success"
                    else:
                        c_status_code = "PARADA"
                        c_status_label = "Parada"
                        c_badge_class = "danger"
                else:
                    c_status_code = "STATUS_NAO_CONFIGURADO"
                    c_status_label = "Status não configurado"
                    c_badge_class = "secondary"
            else:
                c_status_code = "STATUS_NAO_CONFIGURADO"
                c_status_label = "Status não configurado"
                c_badge_class = "secondary"

            # Motivo de parada da cavidade quando parada
            if c_status_code == "PARADA":
                motivo_entry = scada_values.get(cav.xid_motivo_parada) if cav.xid_motivo_parada else None
                c_motivo_str = str(motivo_entry.get("str_value", "")).strip() if motivo_entry else ""
                c_motivo_exibido = c_motivo_str if c_motivo_str else "Motivo não informado"
            else:
                c_motivo_exibido = ""

            cavities_list.append({
                "id": cav.id,
                "nome": cav.nome,
                "ordem": cav.ordem,
                "status_code": c_status_code,
                "status_label": c_status_label,
                "badge_class": c_badge_class,
                "matriz": matriz_val if matriz_val else "Não informada",
                "produto_val": prod_val,
                "lote_val": lote_val,
                "produto_lote_str": produto_lote_str,
                "producao": c_prod,
                "meta": c_meta,
                "percentual": percent,
                "percentual_bar": percent_bar,
                "motivo_parada": c_motivo_exibido,
            })

        total_percent = round((total_prod / total_meta) * 100) if total_meta > 0 else 0
        total_percent_bar = min(100, total_percent) if total_meta > 0 else 0

        return cavities_list, total_prod, total_meta, total_percent, total_percent_bar

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
                    if cav.xid_status_cavidade:
                        all_xids.add(cav.xid_status_cavidade)
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
                continue

            ts_ms = status_entry["ts"]
            age_seconds = (now_ms - ts_ms) / 1000.0
            is_stale = (age_seconds > cfg.stale_limit_seconds)
            scada_dt = timezone.datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            raw_val = str(status_entry.get("str_value", status_entry.get("value", ""))).strip().lower()
            target_val = str(cfg.produzindo_value).strip().lower()
            is_producing = (raw_val == target_val)

            # Caso 2: Dado Desatualizado (Stale) -> Preservar estado industrial sem abrir/fechar eventos
            if is_stale:
                state_obj.sem_comunicacao = False
                state_obj.dado_desatualizado = True
                state_obj.ultima_leitura_scada = scada_dt
                state_obj.ultimo_timestamp_scada = ts_ms
                state_obj.ultimo_valor_status = raw_val
                state_obj.save()
                continue

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
                    # Continua Parada -> Manter o evento aberto, atualizar motivo se necessário
                    if motivo_str and open_event.motivo_geral != motivo_str:
                        open_event.motivo_geral = motivo_str
                        open_event.save(update_fields=["motivo_geral", "updated_at"])
                    if state_obj.estado_atual != "PARADA":
                        state_obj.estado_atual = "PARADA"
                        state_obj.inicio_estado_atual = open_event.inicio
                else:
                    # Transição: Produzindo -> Parada
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
                    # Transição: Parada -> Produzindo -> Fechar evento aberto
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
                    # Continua Produzindo
                    if state_obj.estado_atual != "PRODUZINDO" or not state_obj.inicio_estado_atual:
                        state_obj.estado_atual = "PRODUZINDO"
                        state_obj.inicio_estado_atual = scada_dt
                        state_obj.motivo_atual = ""

            state_obj.save()

        return scada_values

    @classmethod
    def get_dashboard_state(cls) -> dict:
        configs = list(
            ProductionMachineConfig.objects.select_related("machine", "machine__setor")
            .prefetch_related("cavities")
            .order_by("ordem_exibicao", "machine__nome")
        )
        global_params = list(ProductionGlobalParameter.objects.all().order_by("ordem", "nome"))
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
                if cav.xid_status_cavidade:
                    all_xids.add(cav.xid_status_cavidade)
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

        for p in global_params:
            if p.xid:
                all_xids.add(p.xid)
        for a in global_alarms:
            if a.xid:
                all_xids.add(a.xid)

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

            # Recuperar evento aberto ou início do estado para cálculo do cronômetro
            open_event = ProductionDowntimeEvent.objects.filter(
                machine_config=cfg, fim__isnull=True
            ).order_by("-inicio").first()

            motivo_entry = scada_values.get(cfg.xid_motivo_parada_geral) if cfg.xid_motivo_parada_geral else None
            motivo_geral_val = (
                (open_event.motivo_geral if open_event and open_event.motivo_geral else None)
                or (motivo_entry.get("str_value", "") if motivo_entry else "")
                or (state_obj.motivo_atual if state_obj else "")
            )

            if open_event:
                timer_secs = max(0, int((now - open_event.inicio).total_seconds()))
            elif state_obj and state_obj.inicio_estado_atual:
                timer_secs = max(0, int((now - state_obj.inicio_estado_atual).total_seconds()))
            else:
                timer_secs = 0

            tempo_decorrido_str = cls.format_elapsed_seconds_human(timer_secs, state)

            # Alerta de prensa parada há mais de 5 minutos (300 segundos):
            alerta_parada_5min = (state == "PARADA" and not sem_comunicacao and not is_stale and timer_secs >= 300)
            motivo_prensa_pendente = not (motivo_geral_val and str(motivo_geral_val).strip())

            abertura_entry = scada_values.get(cfg.xid_abertura) if cfg.xid_abertura else None
            abertura_val = abertura_entry.get("str_value", "") if abertura_entry else None

            cavities_list, total_prod, total_meta, total_percent, total_percent_bar = cls.build_cavities_data(cfg, scada_values)

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

        return {
            "machines": machines_data,
            "total_count": len(configs),
            "produzindo_count": produzindo_count,
            "paradas_count": paradas_count,
            "sem_comunicacao_count": sem_comunicacao_count,
            "global_parameters": params_data,
            "global_alarms": alarms_data,
            "scada_offline": (len(scada_values) == 0 and len(all_xids) > 0),
            "last_updated_str": timezone.now().strftime("%d/%m/%Y %H:%M:%S"),
        }

    @classmethod
    def get_machine_detail(
        cls,
        config_id: int,
        data_inicio_str: Optional[str] = None,
        data_final_str: Optional[str] = None,
        periodo: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retorna o contexto detalhado de uma máquina específica para a view /producao/maquinas/<id>/,
        incluindo estado atual, cavidades, histórico de paradas filtrado e KPIs do período.
        """
        cfg = (
            ProductionMachineConfig.objects.select_related("machine", "machine__setor")
            .prefetch_related("cavities")
            .get(pk=config_id)
        )

        now = timezone.now()

        # Resolução de intervalo de datas para os filtros
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
                start_dt = timezone.make_aware(timezone.datetime.combine(d_start, timezone.datetime.min.time()))
                end_dt = timezone.make_aware(timezone.datetime.combine(d_end, timezone.datetime.max.time()))
                periodo_ativo = "custom"
            except ValueError:
                end_dt = now
                start_dt = (end_dt - timezone.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                periodo_ativo = "7d"
        else:
            # Padrão: últimos 7 dias
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
            if cav.xid_status_cavidade:
                all_xids.add(cav.xid_status_cavidade)
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

        # Cronômetro persistido
        open_event = ProductionDowntimeEvent.objects.filter(
            machine_config=cfg, fim__isnull=True
        ).order_by("-inicio").first()

        if open_event and open_event.motivo_geral:
            motivo_geral_val = open_event.motivo_geral

        if open_event:
            timer_secs = max(0, int((now - open_event.inicio).total_seconds()))
        elif state_obj and state_obj.inicio_estado_atual:
            timer_secs = max(0, int((now - state_obj.inicio_estado_atual).total_seconds()))
        else:
            timer_secs = 0

        tempo_decorrido_str = cls.format_elapsed_seconds_human(timer_secs, state)

        alerta_parada_5min = (state == "PARADA" and not sem_comunicacao and not is_stale and timer_secs >= 300)
        motivo_prensa_pendente = not (motivo_geral_val and str(motivo_geral_val).strip())

        cavities_list, total_prod, total_meta, total_percent, total_percent_bar = cls.build_cavities_data(cfg, scada_values)

        # Filtro de eventos de parada parcialmente ou totalmente sobrepostos ao período
        events_qs = ProductionDowntimeEvent.objects.filter(
            machine_config=cfg
        ).filter(
            Q(inicio__lte=end_dt) & (Q(fim__isnull=True) | Q(fim__gte=start_dt))
        ).order_by("-inicio")

        events_data = []
        total_downtime_seconds = 0
        maior_parada_seconds = 0
        qtd_paradas = 0

        for ev in events_qs:
            eff_start = max(ev.inicio, start_dt)
            eff_end = min(ev.fim or now, end_dt)
            eff_dur = max(0, int((eff_end - eff_start).total_seconds()))

            total_downtime_seconds += eff_dur
            qtd_paradas += 1
            if eff_dur > maior_parada_seconds:
                maior_parada_seconds = eff_dur

            is_open = (ev.fim is None)
            events_data.append({
                "id": ev.id,
                "inicio": ev.inicio,
                "fim": ev.fim,
                "duracao_segundos": eff_dur,
                "duracao_str": cls.format_elapsed_seconds(eff_dur),
                "motivo_geral": ev.motivo_geral or "Não informado",
                "is_open": is_open,
                "status_label": "Em andamento" if is_open else "Fechado",
            })

        duracao_media_seconds = round(total_downtime_seconds / qtd_paradas) if qtd_paradas > 0 else 0

        return {
            "config": cfg,
            "machine": cfg.machine,
            "setor_nome": cfg.machine.setor.nome if cfg.machine.setor else "Geral",
            "state": state,
            "state_label": state_label,
            "badge_class": badge_class,
            "is_stale": is_stale,
            "sem_comunicacao": sem_comunicacao,
            "tempo_decorrido_str": tempo_decorrido_str,
            "timer_secs": timer_secs,
            "alerta_parada_5min": alerta_parada_5min,
            "motivo_prensa_pendente": motivo_prensa_pendente,
            "motivo_geral": motivo_geral_val or "Sem motivo registrado",
            "ultima_leitura_str": state_obj.ultima_leitura_scada.strftime("%d/%m/%Y %H:%M:%S") if (state_obj and state_obj.ultima_leitura_scada) else "N/A",
            "cavidades": cavities_list,
            "producao_total": total_prod,
            "meta_total": total_meta,
            "percentual_total": total_percent,
            "percentual_total_bar": total_percent_bar,
            "events": events_data,
            "kpi": {
                "tempo_total_parado_str": cls.format_elapsed_seconds(total_downtime_seconds),
                "total_downtime_seconds": total_downtime_seconds,
                "qtd_paradas": qtd_paradas,
                "maior_parada_str": cls.format_elapsed_seconds(maior_parada_seconds),
                "duracao_media_str": cls.format_elapsed_seconds(duracao_media_seconds),
            },
            "filters": {
                "data_inicio_str": start_dt.strftime("%Y-%m-%d"),
                "data_final_str": end_dt.strftime("%Y-%m-%d"),
                "periodo_ativo": periodo_ativo,
            },
        }
