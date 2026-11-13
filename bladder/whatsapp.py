"""Envio conservador: fila compartilhada, limite de testes e nenhuma repetição incerta."""
import datetime
import uuid
from urllib.parse import urlsplit, urlunsplit

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import ConfiguracaoWhatsAppBladder, EnvioWhatsAppBladder


def _url_status(envio):
    partes = urlsplit(settings.WHATSAPP_SERVICE_URL)
    base = partes.path.rstrip('/').rsplit('/', 1)[0]
    return urlunsplit((partes.scheme, partes.netloc, f'{base}/messages/bladder-{envio.pk}', '', ''))


def _registrar(envio, status, detalhe, pode_repetir=False):
    envio.status, envio.detalhe, envio.pode_repetir = status, detalhe, pode_repetir
    envio.save(update_fields=['status', 'detalhe', 'pode_repetir', 'atualizado_em'])
    # A reconciliação de um envio antigo não deve sobrescrever o mais recente.
    mais_recente = envio.configuracao.envios.first()
    if mais_recente and mais_recente.pk == envio.pk:
        ConfiguracaoWhatsAppBladder.objects.filter(pk=envio.configuracao_id).update(
            ultimo_status=status, ultimo_log=detalhe,
            ultimo_envio=envio.criado_em, updated_at=timezone.now(),
        )
    return {'status': status.lower(), 'mensagem': detalhe, 'envio_id': str(envio.pk)}


def consultar_envios(config_id=None):
    """Só consulta; nunca reenvia mensagens já aceitas ou com resultado incerto."""
    envios = EnvioWhatsAppBladder.objects.filter(status__in=['PREPARANDO', 'EM_FILA', 'INCERTO'])
    if config_id is not None:
        envios = envios.filter(configuracao_id=config_id)
    agora = timezone.now()
    envios = envios.exclude(status='INCERTO', criado_em__lt=agora - datetime.timedelta(hours=48))
    for envio in envios.select_related('configuracao').order_by('criado_em')[:100]:
        inicio_tentativa = envio.ultima_tentativa_em or envio.criado_em
        # INCERTO permanece auditável, mas deixa de consultar após 48h.
        if agora - envio.criado_em > datetime.timedelta(hours=48):
            if envio.status != 'INCERTO':
                _registrar(envio, 'INCERTO', 'Sem confirmação após 48 horas. Confira o WhatsApp; não haverá reenvio automático.')
            continue
        try:
            resposta = requests.get(_url_status(envio), timeout=3)
            if resposta.status_code == 200:
                dados = resposta.json()
                if not isinstance(dados, dict):
                    raise ValueError('Resposta de acompanhamento inválida')
                if dados.get('status') == 'sent':
                    _registrar(envio, 'ENVIADO', 'O serviço confirmou o envio ao WhatsApp. Isso não confirma leitura ou entrega ao destinatário.')
                elif dados.get('status') == 'failed':
                    _registrar(envio, 'FALHA', 'A transmissão falhou. Confira o WhatsApp antes de realizar outro teste.')
                elif dados.get('status') == 'queued':
                    if agora - inicio_tentativa > datetime.timedelta(minutes=15):
                        if envio.status != 'INCERTO':
                            _registrar(envio, 'INCERTO', 'Mensagem sem confirmação há mais de 15 minutos. Não será reenviada automaticamente.')
                    elif envio.status != 'EM_FILA':
                        _registrar(envio, 'EM_FILA', 'Mensagem na fila compartilhada do WhatsApp.')
                else:
                    _registrar(envio, 'INCERTO', 'Resposta de acompanhamento desconhecida. Reenvio automático bloqueado.')
            elif resposta.status_code == 404 and envio.status != 'INCERTO' and agora - inicio_tentativa > datetime.timedelta(minutes=2):
                _registrar(envio, 'INCERTO', 'O serviço não reconhece esta mensagem (possível reinício). Confira o WhatsApp; reenvio automático bloqueado.')
            elif resposta.status_code != 200 and envio.status != 'INCERTO' and agora - inicio_tentativa > datetime.timedelta(minutes=15):
                _registrar(envio, 'INCERTO', 'O serviço não confirmou o resultado. Reenvio automático bloqueado.')
        except (requests.RequestException, ValueError):
            if agora - inicio_tentativa > datetime.timedelta(minutes=15) and envio.status != 'INCERTO':
                _registrar(envio, 'INCERTO', 'Não foi possível confirmar o resultado. Reenvio automático bloqueado.')


def enviar_resumo(config_id=None, teste=False, usuario=None, dry_run=False):
    from .services import gerar_texto_resumo_estoque_whatsapp

    config = (ConfiguracaoWhatsAppBladder.objects.filter(pk=config_id).first()
              if config_id is not None else ConfiguracaoWhatsAppBladder.objects.order_by('pk').first())
    if config is None:
        return {'status': 'sem_configuracao', 'mensagem': 'Cadastre a configuração no administrador.'}
    agora = timezone.localtime()
    hoje = agora.date()
    if not teste:
        if not config.habilitado:
            return {'status': 'desabilitado', 'mensagem': 'Envio automático desabilitado.'}
        if str(agora.weekday()) not in [d.strip() for d in config.dias_semana.split(',')]:
            return {'status': 'fora_do_calendario', 'mensagem': 'Hoje não é um dia configurado para envio.'}
        horario = datetime.datetime.combine(hoje, config.horario_envio)
        atraso = agora.replace(tzinfo=None) - horario
        if atraso < datetime.timedelta(0) or atraso >= datetime.timedelta(hours=4):
            return {'status': 'fora_do_horario', 'mensagem': 'Aguardando horário configurado ou janela de quatro horas encerrada.'}
        # Compatibilidade com o último envio anterior à instalação da melhoria.
        if config.ultimo_status == 'SUCESSO' and config.ultimo_envio and timezone.localtime(config.ultimo_envio).date() == hoje:
            return {'status': 'ja_enviado', 'mensagem': 'Resumo já registrado como enviado hoje.'}

    destino = (config.numero_destino or '').strip()
    if not teste and config.grupo_destino and config.grupo_destino.is_active:
        destino = config.grupo_destino.jid
    if not destino:
        return {'status': 'sem_destinatario', 'mensagem': 'Cadastre o número individual para testes ou um destino para o automático.'}
    if teste and (not destino.isascii() or not destino.isdigit() or not destino.startswith('55') or len(destino) not in (12, 13)):
        return {'status': 'destino_invalido', 'mensagem': 'O número de teste deve conter 55 + DDD + número, somente dígitos.'}
    texto = gerar_texto_resumo_estoque_whatsapp()
    if teste:
        texto = '*TESTE SOLICITADO NO ADMINISTRADOR — BLADDER*\n\n' + texto
    # Simulação não cria histórico, não consome limites e não executa HTTP.
    if dry_run or getattr(settings, 'WHATSAPP_DRY_RUN', False):
        return {'status': 'simulado', 'mensagem': 'Simulação; nenhuma mensagem enviada.', 'destino': destino, 'texto': texto}
    # Rotinas locais automáticas nunca enviam; teste exige clique explícito no admin.
    if settings.DEBUG and not teste:
        return {'status': 'desenvolvimento', 'mensagem': 'Envio automático bloqueado com DEBUG=True.'}

    chave = f'auto:{config.pk}:{hoje}'
    with transaction.atomic():
        # Compare-and-set: cliques e processos concorrentes não atravessam o intervalo.
        reservado = ConfiguracaoWhatsAppBladder.objects.filter(pk=config.pk).filter(
            Q(ultimo_disparo__isnull=True) | Q(ultimo_disparo__lte=agora - datetime.timedelta(minutes=10))
        ).update(ultimo_disparo=agora)
        if not reservado:
            return {'status': 'intervalo', 'mensagem': 'Aguarde ao menos dez minutos entre disparos do Bladder.'}
        if teste:
            if config.envios.filter(tipo='TESTE', data_referencia=hoje).count() >= 3:
                transaction.set_rollback(True)
                return {'status': 'limite_testes', 'mensagem': 'Limite de três testes por dia atingido.'}
            envio = EnvioWhatsAppBladder.objects.create(
                configuracao=config, chave=f'teste:{uuid.uuid4()}', tipo='TESTE',
                data_referencia=hoje, destino=destino, solicitado_por=usuario,
            )
        else:
            envio, novo = EnvioWhatsAppBladder.objects.get_or_create(
                chave=chave, defaults=dict(configuracao=config, tipo='AUTOMATICO', data_referencia=hoje, destino=destino),
            )
            if not novo and (not envio.pode_repetir or envio.tentativas >= 3 or
                             agora - envio.atualizado_em < datetime.timedelta(minutes=15)):
                transaction.set_rollback(True)
                return {'status': 'ja_processado', 'mensagem': 'Resumo de hoje já processado ou aguardando intervalo de nova tentativa.'}
            # Um destino alterado não muda a identidade de uma tentativa diária.
            destino = envio.destino
        envio.status, envio.pode_repetir = 'PREPARANDO', False
        envio.ultima_tentativa_em = agora
        envio.save(update_fields=['status', 'pode_repetir', 'ultima_tentativa_em', 'atualizado_em'])

    # Exigir o protocolo de acompanhamento antes de tentar enviar: Node antigo não recebe disparo.
    try:
        partes = urlsplit(_url_status(envio))
        status_url = urlunsplit((partes.scheme, partes.netloc, partes.path.rsplit('/messages/', 1)[0] + '/status', '', ''))
        saude = requests.get(status_url, timeout=3)
        dados = saude.json() if saude.status_code == 200 else {}
        if not isinstance(dados, dict):
            raise ValueError('Resposta de conexão inválida')
        if dados.get('tracking_version') != 1:
            return _registrar(envio, 'FALHA', 'Atualize e reinicie manualmente o serviço WhatsApp para habilitar o acompanhamento do Bladder.', pode_repetir=True)
        if not dados.get('connected') or dados.get('circuitTripped'):
            return _registrar(envio, 'FALHA', 'WhatsApp desconectado ou temporariamente bloqueado; nenhum envio solicitado.', pode_repetir=True)
    except (requests.RequestException, ValueError):
        return _registrar(envio, 'FALHA', 'Serviço WhatsApp indisponível; nenhum envio solicitado.', pode_repetir=True)

    envio.tentativas += 1
    envio.save(update_fields=['tentativas', 'atualizado_em'])
    try:
        resposta = requests.post(settings.WHATSAPP_SERVICE_URL, json={
            'numero': destino, 'mensagem': texto, 'origem': 'bladder', 'message_id': f'bladder-{envio.pk}',
        }, timeout=10)
        if resposta.status_code in (200, 202):
            return _registrar(envio, 'EM_FILA', 'Mensagem aceita na fila. Atualize o status para conferir a transmissão.')
        if resposta.status_code in (429, 503):
            return _registrar(envio, 'FALHA', f'Serviço recusou o envio antes de enfileirar (HTTP {resposta.status_code}).', pode_repetir=True)
        if resposta.status_code == 400:
            return _registrar(envio, 'FALHA', 'Serviço recusou os dados. Confira a configuração e os registros do serviço.')
        return _registrar(envio, 'INCERTO', f'Resposta inesperada (HTTP {resposta.status_code}). Confira o WhatsApp; reenvio automático bloqueado.')
    except requests.RequestException:
        return _registrar(envio, 'INCERTO', 'Conexão interrompida durante a solicitação. Confira o WhatsApp; reenvio automático bloqueado.')
