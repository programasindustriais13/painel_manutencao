import logging
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from production.models import ProductionGlobalAlarm, WhatsAppAlertRecipient
from maintenance.models import WhatsAppGroup

logger = logging.getLogger("production.alerts")


class MaintenanceAlertService:
    """
    Serviço central de monitoramento de XIDs no Scada-LTS e emissão de alertas
    via WhatsApp para a Manutenção Industrial.
    
    Implementa:
    - Máquina de estados idempotente (NORMAL, PENDENTE, ALARME_ATIVO, DESABILITADO);
    - Anti-oscilação com delay configurável;
    - Intervalo de repetição (1, 5, 10, 30 min) com comparação >= agora;
    - Mensagem única de normalização;
    - Desativação individual para paradas de manutenção sem retenção de estado anterior;
    - Consolidação de múltiplos alarmes simultâneos por destinatário (escudo anti-spam);
    - Tratamento resiliente de HTTP 202, 429, 503 e falha de conectividade.
    """

    @classmethod
    def send_whatsapp_message(cls, destination: str, text: str) -> bool:
        """
        Envia mensagem ao microserviço Baileys Node.js respeitando rate limits e circuit breaker.
        Retorna True em caso de sucesso (200/202) e False em falhas ou rate limits (429/503/offline).
        """
        if not destination or not text:
            return False

        url = getattr(settings, "WHATSAPP_SERVICE_URL", "http://localhost:3000/send")
        payload = {
            "numero": destination,
            "mensagem": text,
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code in (200, 202):
                logger.info(f"Mensagem enviada com sucesso ao WhatsApp ({destination}).")
                return True
            elif response.status_code == 429:
                logger.warning(f"Rate limit (429) do WhatsApp atingido para destino '{destination}'. Envio contido defensivamente.")
                return False
            elif response.status_code == 503:
                logger.warning(f"Microserviço WhatsApp temporariamente indisponível (503 / Circuit Breaker). Destino: '{destination}'.")
                return False
            else:
                logger.warning(f"Resposta inesperada do microserviço WhatsApp ({response.status_code}): {response.text[:100]}")
                return False
        except requests.exceptions.RequestException as e:
            logger.warning(f"Microserviço WhatsApp offline ou inacessível ({type(e).__name__}): {e}")
            return False

    @classmethod
    def evaluate_due_alerts(
        cls,
        scada_values: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Avalia todos os alarmes habilitados contra as leituras atuais do Scada-LTS.
        Executa a máquina de estados, consolida eventos por destino e despacha mensagens.
        """
        now = now or timezone.now()

        # Busca todos os alarmes configurados e habilitados
        alarms_qs = (
            ProductionGlobalAlarm.objects.filter(habilitado=True)
            .exclude(Q(xid__isnull=True) | Q(xid=""))
            .prefetch_related("destinatarios", "grupos")
            .order_by("ordem", "nome")
        )
        alarms = list(alarms_qs)
        if not alarms:
            return {"status": "no_alarms", "evaluated": 0}

        # Busca valores do Scada em lote se não foram fornecidos
        if scada_values is None:
            from production.services import scada_reader
            xids = [a.xid.strip() for a in alarms if a.xid and a.xid.strip()]
            scada_values = scada_reader.get_last_values_batch(xids)

        alert_events_by_dest: Dict[str, List[Dict[str, Any]]] = {}
        norm_events_by_dest: Dict[str, List[Dict[str, Any]]] = {}

        for alarm in alarms:
            xid_clean = alarm.xid.strip() if alarm.xid else ""
            entry = scada_values.get(xid_clean)

            # Validação estrita: telemetria indisponível, XID inexistente ou leitura não-numérica NÃO é valor 0!
            if entry is None or entry.get("is_null") or entry.get("value") is None:
                logger.debug(f"Telemetria indisponível ou XID sem leitura para '{alarm.nome}' (XID {xid_clean}). Avaliação pulada.")
                continue

            try:
                val = float(entry["value"])
            except (ValueError, TypeError):
                logger.warning(f"Leitura não numérica recebida para alarme '{alarm.nome}' (XID {xid_clean}): {entry.get('value')}")
                continue

            with transaction.atomic(using="default"):
                # Atualiza última leitura observada
                alarm.ultima_leitura_valor = val
                alarm.ultima_leitura_timestamp = now

                # Verifica limites configurados
                fora_da_faixa = False
                if alarm.valor_minimo is not None and val < alarm.valor_minimo:
                    fora_da_faixa = True
                if alarm.valor_maximo is not None and val > alarm.valor_maximo:
                    fora_da_faixa = True

                disparar_alerta = False
                disparar_normalizacao = False
                tempo_fora_minutos = 0
                tempo_total_minutos = 0

                if fora_da_faixa:
                    if alarm.estado_atual == "NORMAL":
                        # Início de condição fora da faixa: entra em PENDENTE
                        alarm.estado_atual = "PENDENTE"
                        alarm.inicio_fora_faixa = now
                        alarm.alerta_inicial_enviado = False
                    elif alarm.estado_atual == "PENDENTE":
                        if not alarm.inicio_fora_faixa:
                            alarm.inicio_fora_faixa = now
                        segundos_fora = (now - alarm.inicio_fora_faixa).total_seconds()
                        if segundos_fora >= alarm.delay_segundos:
                            # Ultrapassou delay contínuo: ativa alarme
                            alarm.estado_atual = "ALARME_ATIVO"
                            alarm.alerta_inicial_enviado = True
                            alarm.ultimo_alerta_enviado_em = now
                            disparar_alerta = True
                            tempo_fora_minutos = max(1, int(round(segundos_fora / 60)))
                    elif alarm.estado_atual == "ALARME_ATIVO":
                        # Permanece fora da faixa: verificar intervalo de repetição
                        segundos_fora = (now - alarm.inicio_fora_faixa).total_seconds() if alarm.inicio_fora_faixa else 0
                        tempo_fora_minutos = max(1, int(round(segundos_fora / 60)))
                        intervalo_seg = alarm.intervalo_repeticao_minutos * 60
                        if alarm.ultimo_alerta_enviado_em:
                            desde_ultimo = (now - alarm.ultimo_alerta_enviado_em).total_seconds()
                            if desde_ultimo >= intervalo_seg:
                                alarm.ultimo_alerta_enviado_em = now
                                disparar_alerta = True
                        else:
                            alarm.ultimo_alerta_enviado_em = now
                            disparar_alerta = True
                    elif alarm.estado_atual == "DESABILITADO":
                        # Alarme desabilitado não avalia
                        pass

                else:
                    # Valor dentro da faixa normal
                    if alarm.estado_atual == "PENDENTE":
                        # Normalizou antes do delay: cancela condição pendente sem notificação
                        alarm.estado_atual = "NORMAL"
                        alarm.inicio_fora_faixa = None
                        alarm.alerta_inicial_enviado = False
                    elif alarm.estado_atual == "ALARME_ATIVO":
                        # Retornou da condição de alarme ativo para normal
                        alarm.estado_atual = "NORMAL"
                        alarm.ultima_normalizacao_em = now
                        if alarm.inicio_fora_faixa:
                            tempo_total_seg = (now - alarm.inicio_fora_faixa).total_seconds()
                            tempo_total_minutos = max(1, int(round(tempo_total_seg / 60)))
                        else:
                            tempo_total_minutos = 1

                        if alarm.notificar_normalizacao:
                            disparar_normalizacao = True

                        alarm.inicio_fora_faixa = None
                        alarm.alerta_inicial_enviado = False

                alarm.save(update_fields=[
                    "estado_atual",
                    "inicio_fora_faixa",
                    "ultima_leitura_valor",
                    "ultima_leitura_timestamp",
                    "ultimo_alerta_enviado_em",
                    "alerta_inicial_enviado",
                    "ultima_normalizacao_em",
                ])

                # Coleta destinatários para este alarme se houver evento a disparar
                if disparar_alerta or disparar_normalizacao:
                    dest_individuais = [d.telefone_normalizado for d in alarm.destinatarios.filter(ativo=True)]
                    dest_grupos = [g.jid for g in alarm.grupos.filter(is_active=True)]
                    todos_destinos = set(dest_individuais + dest_grupos)

                    if not todos_destinos:
                        logger.warning(f"Alarme '{alarm.nome}' gerou evento, mas não possui nenhum destinatário ativo configurado.")

                    if disparar_alerta:
                        evento = {
                            "alarm": alarm,
                            "valor": val,
                            "tempo_fora_minutos": tempo_fora_minutos,
                            "inicio_fora_faixa": alarm.inicio_fora_faixa,
                        }
                        for d in todos_destinos:
                            alert_events_by_dest.setdefault(d, []).append(evento)

                    if disparar_normalizacao:
                        evento_norm = {
                            "alarm": alarm,
                            "valor": val,
                            "tempo_total_minutos": tempo_total_minutos,
                            "normalizado_em": now,
                        }
                        for d in todos_destinos:
                            norm_events_by_dest.setdefault(d, []).append(evento_norm)

        # ------------------------------------------------------------------
        # DESPACHO CONSOLIDADO (ESCUDO ANTI-SPAM / COORDENAÇÃO DE SAÍDA)
        # ------------------------------------------------------------------
        # 1. Envio consolidado de Alertas
        for dest, events in alert_events_by_dest.items():
            texto = cls._formatar_mensagem_alerta(events, now)
            cls.send_whatsapp_message(dest, texto)

        # 2. Envio consolidado de Normalizações
        for dest, events in norm_events_by_dest.items():
            texto = cls._formatar_mensagem_normalizacao(events, now)
            cls.send_whatsapp_message(dest, texto)

        return {
            "status": "success",
            "evaluated": len(alarms),
            "alert_destinations": len(alert_events_by_dest),
            "norm_destinations": len(norm_events_by_dest),
        }

    @classmethod
    def _formatar_mensagem_alerta(cls, events: List[Dict[str, Any]], now: datetime) -> str:
        """
        Formata uma mensagem de alerta consolidada (um ou múltiplos alarmes simultâneos).
        """
        linhas = ["⚠️ *ALERTA DE MANUTENÇÃO*", ""]
        tz_now = timezone.localtime(now) if timezone.is_aware(now) else now

        for ev in events:
            alarm = ev["alarm"]
            val = ev["valor"]
            u = f" {alarm.unidade}" if alarm.unidade else ""
            tempo_min = ev["tempo_fora_minutos"]

            dt_inicio = ev.get("inicio_fora_faixa")
            dt_inicio_str = ""
            if dt_inicio:
                dt_loc = timezone.localtime(dt_inicio) if timezone.is_aware(dt_inicio) else dt_inicio
                dt_inicio_str = f"Fora da faixa desde: {dt_loc.strftime('%H:%M')}\n"

            linhas.append(f"• *{alarm.nome}*")
            linhas.append(f"Valor atual: {val:.1f}{u}")
            linhas.append(f"Faixa permitida: {alarm.faixa_formatada}")
            if dt_inicio_str:
                linhas.append(dt_inicio_str.strip())
            linhas.append(f"Tempo fora do limite: {tempo_min} min")
            linhas.append("")

        linhas.append(tz_now.strftime("%d/%m/%Y %H:%M"))
        return "\n".join(linhas)

    @classmethod
    def _formatar_mensagem_normalizacao(cls, events: List[Dict[str, Any]], now: datetime) -> str:
        """
        Formata uma mensagem de normalização consolidada.
        """
        linhas = ["✅ *NORMALIZADO*", ""]
        tz_now = timezone.localtime(now) if timezone.is_aware(now) else now

        for ev in events:
            alarm = ev["alarm"]
            val = ev["valor"]
            u = f" {alarm.unidade}" if alarm.unidade else ""
            tempo_total = ev["tempo_total_minutos"]

            linhas.append(f"• *{alarm.nome}*")
            linhas.append(f"Valor atual: {val:.1f}{u}")
            linhas.append(f"Faixa permitida: {alarm.faixa_formatada}")
            linhas.append(f"Tempo total fora da faixa: {tempo_total} min")
            linhas.append("")

        linhas.append(f"Normalizado em: {tz_now.strftime('%d/%m/%Y %H:%M')}")
        return "\n".join(linhas)
