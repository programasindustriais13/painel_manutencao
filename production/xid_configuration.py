import logging
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from maintenance.models import Machine
from production.models import (
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    ProductionParameterConfig,
    ProductionMatrixCatalog,
)
from production.services import (
    scada_reader,
    CAVITY_REASON_MAP,
)

logger = logging.getLogger(__name__)


class XIDRegistry:
    """
    Componente central de introspecção, agrupamento funcional e metadados de XIDs.
    Fornece a especificação canônica de todos os campos que representam telemetria
    no Scada-LTS e garante consistência entre formulários, diagnósticos e testes.
    """

    MACHINE_XID_FIELDS = [
        {
            "field_name": "xid_status_prensa",
            "label": "XID Status da Prensa (Produzindo/Parada)",
            "short_label": "Status da Prensa",
            "group": "Configuração Geral da Prensa",
            "help_text": "Ponto que indica se a máquina está em ciclo produtivo ou parada.",
            "target": "machine",
            "required": False,
        },
        {
            "field_name": "xid_abertura",
            "label": "XID Sinal de Abertura",
            "short_label": "Sinal de Abertura",
            "group": "Configuração Geral da Prensa",
            "help_text": "Ponto de transição/abertura de molde para ciclos de vulcanização.",
            "target": "machine",
            "required": False,
        },
        {
            "field_name": "xid_motivo_parada_geral",
            "label": "XID Motivo de Parada Geral",
            "short_label": "Motivo Geral de Parada",
            "group": "Configuração Geral da Prensa",
            "help_text": "Código numérico do motivo de parada geral do equipamento.",
            "target": "machine",
            "required": False,
        },
    ]

    CAVITY_XID_FIELDS = [
        # Grupo: Produção e Parada
        {
            "field_name": "xid_producao",
            "label": "XID Produção Atual",
            "short_label": "Contador de Produção",
            "group": "Parada e Produção",
            "help_text": "Contador acumulativo de pneus/passadas vulcanizadas na cavidade.",
            "target": "cavity",
            "required": False,
        },
        {
            "field_name": "xid_motivo_parada",
            "label": "XID Motivo de Parada da Cavidade",
            "short_label": "Motivo de Parada da Cavidade",
            "group": "Parada e Produção",
            "help_text": "Código numérico do motivo de parada individual da cavidade.",
            "target": "cavity",
            "required": False,
        },
        # Grupo: Matriz e Lote
        {
            "field_name": "xid_matriz",
            "label": "XID Matriz",
            "short_label": "Matriz / Modelo",
            "group": "Matriz e Lote",
            "help_text": "Código da matriz em produção (traduzido pelo catálogo canônico).",
            "target": "cavity",
            "required": False,
        },
        {
            "field_name": "xid_produto",
            "label": "XID Prefixo do Lote do Bladder (1ª parte)",
            "short_label": "Prefixo Lote Bladder",
            "group": "Matriz e Lote",
            "help_text": "Primeira parte do identificador de lote do bladder (ex: 6154).",
            "target": "cavity",
            "required": False,
        },
        {
            "field_name": "xid_lote_bladder",
            "label": "XID Número do Lote do Bladder (2ª parte)",
            "short_label": "Número Lote Bladder",
            "group": "Matriz e Lote",
            "help_text": "Segunda parte do identificador de lote do bladder (ex: 161046).",
            "target": "cavity",
            "required": False,
        },
        # Grupo: Rastreabilidade do Bladder
        {
            "field_name": "xid_bla_real",
            "label": "XID BLA Real Instalado",
            "short_label": "Código BLA Real",
            "group": "Rastreabilidade do Bladder",
            "help_text": "Código do bladder instalado lido do CLP (ex: BLA003).",
            "target": "cavity",
            "required": False,
        },
        {
            "field_name": "xid_meta",
            "label": "XID Limite de Vida do Bladder (Scada)",
            "short_label": "Limite de Vida Bladder",
            "group": "Rastreabilidade do Bladder",
            "help_text": "Limite de vida útil produtiva do ciclo do bladder parametrizado no Scada.",
            "target": "cavity",
            "required": False,
        },
        {
            "field_name": "xid_motivo_troca_bladder",
            "label": "XID Motivo da Troca do Bladder",
            "short_label": "Motivo Troca Bladder",
            "group": "Rastreabilidade do Bladder",
            "help_text": "Código numérico (0 a 8) do motivo de substituição do bladder.",
            "target": "cavity",
            "required": False,
        },
    ]

    GLOBAL_PARAM_XID_FIELDS = [
        {
            "field_name": "xid",
            "label": "XID no Scada-LTS",
            "short_label": "XID Scada",
            "group": "Parâmetros Globais",
            "help_text": "Identificador único do ponto de telemetria no Scada-LTS.",
            "target": "global_parameter",
            "required": False,
        }
    ]

    GLOBAL_ALARM_XID_FIELDS = [
        {
            "field_name": "xid",
            "label": "XID no Scada-LTS",
            "short_label": "XID Scada",
            "group": "Alarmes Globais",
            "help_text": "Identificador único do ponto de alarme no Scada-LTS.",
            "target": "global_alarm",
            "required": False,
        }
    ]

    PARAMETER_CONFIG_XID_FIELDS = [
        {
            "field_name": "xid",
            "label": "XID Scada",
            "short_label": "XID Scada",
            "group": "Parâmetros de Processo",
            "help_text": "Identificador do ponto com faixa de limite operacional.",
            "target": "parameter_config",
            "required": False,
        }
    ]

    @classmethod
    def get_machine_fields(cls) -> List[Dict[str, Any]]:
        return cls.MACHINE_XID_FIELDS

    @classmethod
    def get_cavity_fields(cls) -> List[Dict[str, Any]]:
        return cls.CAVITY_XID_FIELDS

    @classmethod
    def get_registered_fields_by_model(cls) -> Dict[str, List[str]]:
        return {
            "ProductionMachineConfig": [f["field_name"] for f in cls.MACHINE_XID_FIELDS],
            "ProductionCavityConfig": [f["field_name"] for f in cls.CAVITY_XID_FIELDS],
            "ProductionGlobalParameter": [f["field_name"] for f in cls.GLOBAL_PARAM_XID_FIELDS],
            "ProductionGlobalAlarm": [f["field_name"] for f in cls.GLOBAL_ALARM_XID_FIELDS],
            "ProductionParameterConfig": [f["field_name"] for f in cls.PARAMETER_CONFIG_XID_FIELDS],
        }


class XIDDiagnosticsService:
    """
    Serviço de análise em lote e diagnóstico de cobertura de XIDs da fábrica.
    Calcula percentuais de preenchimento, lista pendências detalhadas por prensa
    e identifica possíveis duplicidades.
    """

    @classmethod
    def get_diagnostics_overview(
        cls,
        search_query: Optional[str] = None,
        status_filter: Optional[str] = None,
        sector_filter: Optional[str] = "vulcanizacao"
    ) -> Dict[str, Any]:
        """
        Executa diagnóstico global consolidando máquinas, cavidades e variáveis globais.
        """
        base_qs = (
            Machine.objects.all()
            .select_related("setor", "production_config")
            .prefetch_related("production_config__cavities")
            .order_by("production_config__ordem_exibicao", "nome")
        )

        vulcanizacao_filter = (
            Q(production_config__isnull=False) |
            Q(setor__nome__icontains="vulc") |
            Q(setor__nome__icontains="prens") |
            Q(nome__icontains="prensa")
        )
        vulcanizacao_count = base_qs.filter(vulcanizacao_filter).count()
        total_factory_machines = base_qs.count()

        if sector_filter == "vulcanizacao":
            machines_qs = base_qs.filter(vulcanizacao_filter)
        elif sector_filter and sector_filter != "all":
            machines_qs = base_qs.filter(setor__nome__iexact=sector_filter)
        else:
            machines_qs = base_qs

        global_params = list(
            ProductionGlobalParameter.objects.exclude(
                Q(chave__startswith="calandra_") | Q(nome__istartswith="calandra")
            ).order_by("ordem", "nome")
        )
        global_alarms = list(ProductionGlobalAlarm.objects.all().order_by("ordem", "nome"))
        process_params = list(ProductionParameterConfig.objects.filter(ativo=True).order_by("ordem", "nome"))


        # Mapa global de ocorrência de XIDs para detecção de duplicidades
        xid_usage_map: Dict[str, List[Dict[str, Any]]] = {}

        def _register_xid(xid_val: Optional[str], location: str, field_label: str, model_name: str, obj_id: Any):
            if xid_val and str(xid_val).strip():
                clean_xid = str(xid_val).strip()
                if clean_xid not in xid_usage_map:
                    xid_usage_map[clean_xid] = []
                xid_usage_map[clean_xid].append({
                    "location": location,
                    "field_label": field_label,
                    "model_name": model_name,
                    "id": obj_id,
                })

        machine_fields_defs = XIDRegistry.get_machine_fields()
        cavity_fields_defs = XIDRegistry.get_cavity_fields()

        total_expected_xids = 0
        total_filled_xids = 0

        # Processar variáveis globais
        for gp in global_params:
            total_expected_xids += 1
            if gp.xid and str(gp.xid).strip():
                total_filled_xids += 1
                _register_xid(gp.xid, f"Parâmetro Global '{gp.nome}'", "XID", "ProductionGlobalParameter", gp.pk)

        for ga in global_alarms:
            total_expected_xids += 1
            if ga.xid and str(ga.xid).strip():
                total_filled_xids += 1
                _register_xid(ga.xid, f"Alarme Global '{ga.nome}'", "XID", "ProductionGlobalAlarm", ga.pk)

        for pp in process_params:
            total_expected_xids += 1
            if pp.xid and str(pp.xid).strip():
                total_filled_xids += 1
                _register_xid(pp.xid, f"Parâmetro de Processo '{pp.nome}'", "XID", "ProductionParameterConfig", pp.pk)

        machines_data: List[Dict[str, Any]] = []

        for m in machines_qs:
            cfg = getattr(m, "production_config", None)
            m_expected = len(machine_fields_defs)
            m_filled = 0
            missing_items: List[str] = []
            machine_name = m.nome
            sector_name = m.setor.nome if m.setor else "Geral"


            if cfg:
                for f_def in machine_fields_defs:
                    f_name = f_def["field_name"]
                    val = getattr(cfg, f_name, None)
                    if val and str(val).strip():
                        m_filled += 1
                        _register_xid(val, f"{machine_name} (Geral)", f_def["short_label"], "ProductionMachineConfig", cfg.pk)
                    else:
                        missing_items.append(f"Geral: {f_def['short_label']}")

                cavities = list(cfg.cavities.all().order_by("ordem", "id"))
                cavities_count = len(cavities)

                if cavities_count == 0:
                    m_expected += 2 * len(cavity_fields_defs)
                    missing_items.append("Nenhuma cavidade cadastrada (Configuração pendente)")
                else:
                    for cav in cavities:
                        m_expected += len(cavity_fields_defs)
                        for c_def in cavity_fields_defs:
                            c_f_name = c_def["field_name"]
                            c_val = getattr(cav, c_f_name, None)
                            if c_val and str(c_val).strip():
                                m_filled += 1
                                _register_xid(c_val, f"{machine_name} - {cav.nome}", c_def["short_label"], "ProductionCavityConfig", cav.pk)
                            else:
                                missing_items.append(f"{cav.nome}: {c_def['short_label']}")
            else:
                cavities_count = 0
                m_expected += 2 * len(cavity_fields_defs)
                missing_items.append("Configuração SCADA ainda não criada")
                for f_def in machine_fields_defs:
                    missing_items.append(f"Geral: {f_def['short_label']}")

            total_expected_xids += m_expected
            total_filled_xids += m_filled

            pct = round((m_filled / m_expected * 100.0), 1) if m_expected > 0 else 0.0
            is_complete = (m_filled == m_expected and m_expected > 0)
            is_unconfigured = (cfg is None)

            machines_data.append({
                "machine_id": m.id,
                "config_id": cfg.id if cfg else None,
                "machine_name": machine_name,
                "sector_name": sector_name,
                "cavities_count": cavities_count,
                "expected_count": m_expected,
                "filled_count": m_filled,
                "missing_count": m_expected - m_filled,
                "percent": pct,
                "is_complete": is_complete,
                "is_unconfigured": is_unconfigured,
                "missing_items": missing_items,
                "stale_limit_seconds": cfg.stale_limit_seconds if cfg else 120,
                "produzindo_value": cfg.produzindo_value if cfg else "1",
            })

        # Mapeamento de duplicidades (XIDs com > 1 registro)
        duplicates_map = {xid: locs for xid, locs in xid_usage_map.items() if len(locs) > 1}
        duplicates_count = len(duplicates_map)

        for m_item in machines_data:
            m_name = m_item["machine_name"]
            m_dups = []
            for d_xid, loc_list in duplicates_map.items():
                if any(m_name in loc["location"] for loc in loc_list):
                    other_locs = [l["location"] for l in loc_list]
                    m_dups.append({"xid": d_xid, "locations": other_locs, "count": len(loc_list)})
            m_item["duplicates"] = m_dups
            m_item["has_duplicates"] = len(m_dups) > 0

        filtered_machines = machines_data

        if search_query:
            sq = search_query.strip().lower()
            filtered_machines = [
                m for m in filtered_machines
                if sq in m["machine_name"].lower()
                or sq in m["sector_name"].lower()
                or any(sq in item.lower() for item in m["missing_items"])
                or any(sq in d["xid"].lower() for d in m.get("duplicates", []))
            ]

        if status_filter == "complete":
            filtered_machines = [m for m in filtered_machines if m["is_complete"]]
        elif status_filter == "incomplete":
            filtered_machines = [m for m in filtered_machines if not m["is_complete"]]
        elif status_filter == "issues":
            filtered_machines = [m for m in filtered_machines if m.get("has_duplicates") or m["is_unconfigured"] or not m["is_complete"]]

        total_missing = max(0, total_expected_xids - total_filled_xids)
        overall_pct = round((total_filled_xids / total_expected_xids * 100.0), 1) if total_expected_xids > 0 else 0.0

        return {
            "total_machines": len(machines_data),
            "total_expected_xids": total_expected_xids,
            "total_filled_xids": total_filled_xids,
            "total_missing_xids": total_missing,
            "overall_percent": overall_pct,
            "duplicates_count": duplicates_count,
            "duplicates_map": duplicates_map,
            "machines": filtered_machines,
            "all_machines_count": len(machines_data),
            "complete_count": sum(1 for m in machines_data if m["is_complete"]),
            "incomplete_count": sum(1 for m in machines_data if not m["is_complete"]),
            "issues_count": sum(1 for m in machines_data if m.get("has_duplicates") or m["is_unconfigured"] or not m["is_complete"]),
            "global_params_count": len(global_params),
            "global_params_filled": sum(1 for gp in global_params if gp.xid and str(gp.xid).strip()),
            "global_alarms_count": len(global_alarms),
            "global_alarms_filled": sum(1 for ga in global_alarms if ga.xid and str(ga.xid).strip()),
            "process_params_count": len(process_params),
            "process_params_filled": sum(1 for pp in process_params if pp.xid and str(pp.xid).strip()),
            "current_search": search_query or "",
            "current_status": status_filter or "all",
            "current_sector": sector_filter or "vulcanizacao",
            "vulcanizacao_count": vulcanizacao_count,
            "total_factory_machines": total_factory_machines,
        }



class XIDTestService:
    """
    Serviço seguro e estritamente somente-leitura para teste de DataPoints e XIDs no Scada-LTS.
    Reutiliza ScadaReaderService sem acionar coletor, sem abrir eventos e sem escrita no banco.
    """

    DATA_TYPE_NAMES = {
        1: "Binário / Boolean (1)",
        2: "Multistate / Inteiro (2)",
        3: "Numérico / Float (3)",
        4: "Alfanumérico / String (4)",
    }

    @classmethod
    def test_single_xid(cls, xid_raw: Any) -> Dict[str, Any]:
        """
        Consulta um XID no Scada-LTS e retorna seu estado de conectividade, tipo, valor e timestamp.
        """
        if not xid_raw or not str(xid_raw).strip():
            return {
                "success": False,
                "status": "EMPTY",
                "xid": "",
                "message": "Nenhum XID fornecido para consulta.",
            }

        clean_xid = str(xid_raw).strip()

        try:
            # 1. Resolução do DataPoint ID
            dp_map = scada_reader.get_data_point_ids([clean_xid])
            if not dp_map or clean_xid not in dp_map:
                return {
                    "success": False,
                    "status": "NOT_FOUND",
                    "xid": clean_xid,
                    "message": f"O XID '{clean_xid}' não foi localizado no Scada-LTS.",
                }

            dp_id = dp_map[clean_xid]

            # 2. Busca do último valor
            values_map = scada_reader.get_last_values_batch([clean_xid])
            val_entry = values_map.get(clean_xid)

            if not val_entry:
                return {
                    "success": True,
                    "status": "NO_READINGS",
                    "xid": clean_xid,
                    "data_point_id": dp_id,
                    "message": f"DataPoint localizado (ID #{dp_id}), porém não há leituras recentes registradas no Scada-LTS.",
                }

            data_type = val_entry.get("data_type", 0)
            data_type_label = cls.DATA_TYPE_NAMES.get(data_type, f"Tipo {data_type}")
            val = val_entry.get("value")
            str_val = val_entry.get("str_value", str(val))
            ts = val_entry.get("ts")

            # Formatação do timestamp
            formatted_dt_str = "Não registrado"
            is_stale = False
            if ts:
                try:
                    dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.get_current_timezone())
                    formatted_dt_str = dt.strftime("%d/%m/%Y %H:%M:%S")
                    diff_seconds = (timezone.now() - dt).total_seconds()
                    if diff_seconds > 300:
                        is_stale = True
                except Exception:
                    formatted_dt_str = str(ts)

            # Interpretação semântica amigável adicional
            semantic_hint = ""
            if data_type in (1, 2, 3):
                try:
                    int_val = int(val) if val is not None else None
                    if int_val in CAVITY_REASON_MAP:
                        semantic_hint = f"Motivo Parada: {CAVITY_REASON_MAP[int_val]}"
                except (ValueError, TypeError):
                    pass

                if not semantic_hint and val is not None:
                    try:
                        mat_obj = ProductionMatrixCatalog.objects.filter(
                            Q(codigo_scada=int(val)) | Q(codigo=str(val))
                        ).first()
                        if mat_obj:
                            semantic_hint = f"Matriz: {mat_obj.nome_exibicao or mat_obj.produto}"
                    except Exception:
                        pass

            return {
                "success": True,
                "status": "OK",
                "xid": clean_xid,
                "data_point_id": dp_id,
                "data_type": data_type,
                "data_type_label": data_type_label,
                "value": val,
                "str_value": str_val,
                "ts": ts,
                "formatted_time": formatted_dt_str,
                "is_stale": is_stale,
                "semantic_hint": semantic_hint,
                "message": f"✓ XID localizado no Scada-LTS (DataPoint #{dp_id})",
            }

        except Exception as e:
            logger.warning(f"Erro ao testar leitura do XID '{clean_xid}' no Scada: {type(e).__name__}: {str(e)}")
            return {
                "success": False,
                "status": "SCADA_OFFLINE",
                "xid": clean_xid,
                "message": "Não foi possível consultar o Scada-LTS neste momento. As alterações podem ser salvas localmente no banco padrão e testadas quando a conexão for restabelecida.",
            }
