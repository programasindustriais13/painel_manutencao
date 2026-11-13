import datetime
import io
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from maintenance.models import WhatsAppGroup
from .models import ConfiguracaoWhatsAppBladder, EnvioWhatsAppBladder, ProdutoBladder
from .services import gerar_texto_resumo_estoque_whatsapp
from .whatsapp import enviar_resumo, consultar_envios


@override_settings(DEBUG=False, WHATSAPP_DRY_RUN=False, SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'])
class WhatsAppBladderTests(TestCase):
    def setUp(self):
        self.agora = datetime.datetime(2026, 11, 13, 7, 30, tzinfo=ZoneInfo('America/Sao_Paulo'))
        self.clock = patch('django.utils.timezone.now', side_effect=lambda: self.agora)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.get = patch('bladder.whatsapp.requests.get').start()
        self.post = patch('bladder.whatsapp.requests.post').start()
        self.addCleanup(patch.stopall)
        self.get.return_value = Mock(status_code=200)
        self.get.return_value.json.return_value = {'connected': True, 'tracking_version': 2, 'circuitTripped': False}
        self.post.return_value = Mock(status_code=202)
        self.config = ConfiguracaoWhatsAppBladder.objects.create(numero_destino='5585999999999')
        self.user = User.objects.create_superuser('admin_whatsapp', password='test-pass', email='admin@example.test')

    def avancar(self, minutos):
        self.agora += datetime.timedelta(minutes=minutos)

    def test_horario_dias_e_janela_sao_respeitados(self):
        self.agora = self.agora.replace(hour=7, minute=29)
        self.assertEqual(enviar_resumo()['status'], 'fora_do_horario')
        self.agora = self.agora.replace(hour=11, minute=30)
        self.assertEqual(enviar_resumo()['status'], 'fora_do_horario')
        self.agora += datetime.timedelta(days=1)
        self.assertEqual(enviar_resumo()['status'], 'fora_do_calendario')
        self.post.assert_not_called()

    def test_alterar_horario_no_admin_tem_efeito(self):
        self.config.horario_envio = datetime.time(8, 0)
        self.config.save()
        self.assertEqual(enviar_resumo()['status'], 'fora_do_horario')
        self.agora = self.agora.replace(hour=8, minute=0)
        self.assertEqual(enviar_resumo()['status'], 'em_fila')

    def test_desabilitado_e_sem_destino_nao_enviam(self):
        self.config.habilitado = False
        self.config.save()
        self.assertEqual(enviar_resumo()['status'], 'desabilitado')
        self.config.habilitado, self.config.numero_destino = True, ''
        self.config.save()
        self.assertEqual(enviar_resumo()['status'], 'sem_destinatario')
        self.post.assert_not_called()

    def test_sem_configuracao_nao_cria_registro(self):
        self.config.delete()
        self.assertEqual(enviar_resumo()['status'], 'sem_configuracao')
        self.assertFalse(ConfiguracaoWhatsAppBladder.objects.exists())

    def test_automatico_nao_repete_mesmo_apos_intervalo(self):
        self.assertEqual(enviar_resumo()['status'], 'em_fila')
        self.avancar(16)
        self.assertEqual(enviar_resumo()['status'], 'ja_processado')
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(EnvioWhatsAppBladder.objects.count(), 1)

    def test_sucesso_legado_e_convertido_para_data_local(self):
        self.config.ultimo_envio = self.agora.astimezone(datetime.timezone.utc)
        self.config.ultimo_status = 'SUCESSO'
        self.config.save()
        self.assertEqual(enviar_resumo()['status'], 'ja_enviado')
        self.post.assert_not_called()

    def test_novo_dia_permite_novo_resumo(self):
        enviar_resumo()
        self.avancar(3 * 24 * 60)  # Segunda-feira
        self.assertEqual(enviar_resumo()['status'], 'em_fila')
        self.assertEqual(self.post.call_count, 2)

    def test_grupo_tem_prioridade_no_automatico_e_teste_usa_numero(self):
        self.config.grupo_destino = WhatsAppGroup.objects.create(nome='Grupo teste', jid='123456@g.us')
        self.config.save()
        enviar_resumo()
        self.assertEqual(self.post.call_args.kwargs['json']['numero'], '123456@g.us')
        self.avancar(10)
        enviar_resumo(config_id=self.config.pk, teste=True, usuario=self.user)
        payload = self.post.call_args.kwargs['json']
        self.assertEqual(payload['numero'], self.config.numero_destino)
        self.assertIn('TESTE SOLICITADO', payload['mensagem'])
        self.assertEqual(payload['origem'], 'bladder')
        self.assertTrue(payload['message_id'].startswith('bladder-'))
        self.assertEqual(EnvioWhatsAppBladder.objects.first().solicitado_por, self.user)

    def test_grupo_inativo_usa_numero_no_automatico(self):
        self.config.grupo_destino = WhatsAppGroup.objects.create(nome='Inativo', jid='123@g.us', is_active=False)
        self.config.save()
        enviar_resumo()
        self.assertEqual(self.post.call_args.kwargs['json']['numero'], self.config.numero_destino)

    def test_teste_explicito_ignora_calendario_e_habilitado(self):
        self.agora += datetime.timedelta(days=1)
        self.config.habilitado = False
        self.config.save()
        with override_settings(DEBUG=True):
            self.assertEqual(enviar_resumo(teste=True)['status'], 'em_fila')

    def test_teste_sem_numero_nao_envia_ao_grupo(self):
        self.config.numero_destino = ''
        self.config.grupo_destino = WhatsAppGroup.objects.create(nome='Grupo', jid='123@g.us')
        self.config.save()
        self.assertEqual(enviar_resumo(teste=True)['status'], 'sem_destinatario')
        self.post.assert_not_called()

    def test_intervalo_e_limite_de_tres_testes(self):
        self.assertEqual(enviar_resumo(teste=True)['status'], 'em_fila')
        self.assertEqual(enviar_resumo(teste=True)['status'], 'intervalo')
        for _ in range(2):
            self.avancar(10)
            self.assertEqual(enviar_resumo(teste=True)['status'], 'em_fila')
        self.avancar(10)
        self.assertEqual(enviar_resumo(teste=True)['status'], 'limite_testes')
        self.assertEqual(self.post.call_count, 3)

    def test_simulacao_nao_faz_http_nem_muda_banco(self):
        for opcoes in ({'dry_run': True}, {'teste': True, 'dry_run': True}):
            self.assertEqual(enviar_resumo(**opcoes)['status'], 'simulado')
        self.get.assert_not_called()
        self.post.assert_not_called()
        self.config.refresh_from_db()
        self.assertIsNone(self.config.ultimo_disparo)
        self.assertFalse(self.config.envios.exists())

    @override_settings(WHATSAPP_DRY_RUN=True)
    def test_chave_global_de_simulacao_impede_teste_real(self):
        self.assertEqual(enviar_resumo(teste=True)['status'], 'simulado')
        self.post.assert_not_called()

    @override_settings(DEBUG=True)
    def test_automatico_local_e_bloqueado(self):
        self.assertEqual(enviar_resumo()['status'], 'desenvolvimento')
        self.get.assert_not_called()
        self.post.assert_not_called()

    def test_servico_antigo_nao_recebe_mensagem(self):
        self.get.return_value.json.return_value = {'connected': True}
        self.assertEqual(enviar_resumo()['status'], 'falha')
        self.post.assert_not_called()

    def test_offline_aguarda_sem_consumir_tentativas_de_transmissao(self):
        self.get.return_value.json.return_value['connected'] = False
        for _ in range(4):
            self.assertEqual(enviar_resumo()['status'], 'falha')
            self.avancar(15)
        self.assertEqual(self.config.envios.get().tentativas, 0)
        self.get.return_value.json.return_value['connected'] = True
        self.assertEqual(enviar_resumo()['status'], 'em_fila')
        self.assertEqual(self.post.call_count, 1)

    def test_fila_apos_esperar_servico_usa_instante_da_tentativa_atual(self):
        self.get.return_value.json.return_value['connected'] = False
        enviar_resumo()
        self.avancar(60)
        self.get.return_value.json.return_value['connected'] = True
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'queued'}
        consultar_envios()
        self.assertEqual(self.config.envios.get().status, 'EM_FILA')

    def test_preserva_sucesso_legado_na_migracao(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        self.config.ultimo_status, self.config.ultimo_envio = 'SUCESSO', self.agora
        self.config.save()
        migration = import_module('bladder.migrations.0009_whatsapp_agendamento_historico')
        migration.preservar_sucessos_anteriores(apps, Mock(connection=connection))
        self.avancar(1)
        enviar_resumo(teste=True)
        self.avancar(15)
        self.assertEqual(enviar_resumo()['status'], 'ja_processado')
        self.assertEqual(self.post.call_count, 1)

    def test_status_antigos_incertos_nao_bloqueiam_acompanhamento_recente(self):
        antigo = self.agora - datetime.timedelta(days=3)
        for n in range(101):
            envio = EnvioWhatsAppBladder.objects.create(
                configuracao=self.config, chave=f'antigo-{n}', tipo='TESTE',
                data_referencia=antigo.date(), destino=self.config.numero_destino, status='INCERTO',
            )
            EnvioWhatsAppBladder.objects.filter(pk=envio.pk).update(criado_em=antigo, atualizado_em=antigo)
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'server_ack'}
        consultar_envios()
        self.assertEqual(self.config.envios.first().status, 'ENVIADO')

    def test_rejeicao_temporaria_limita_tres_tentativas(self):
        self.post.return_value.status_code = 429
        for _ in range(3):
            self.assertEqual(enviar_resumo()['status'], 'falha')
            self.avancar(15)
        self.assertEqual(enviar_resumo()['status'], 'ja_processado')
        self.assertEqual(self.post.call_count, 3)
        self.assertEqual(self.config.envios.get().tentativas, 3)

    def test_timeout_nao_dispara_repeticao_automatica(self):
        self.post.side_effect = requests.Timeout()
        self.assertEqual(enviar_resumo()['status'], 'incerto')
        self.avancar(16)
        self.assertEqual(enviar_resumo()['status'], 'ja_processado')
        self.assertEqual(self.post.call_count, 1)

    def test_http_inesperado_tambem_bloqueia_reenvio(self):
        self.post.return_value.status_code = 500
        self.assertEqual(enviar_resumo()['status'], 'incerto')
        self.assertFalse(self.config.envios.get().pode_repetir)

    def test_http400_nao_e_repetido(self):
        self.post.return_value.status_code = 400
        self.assertEqual(enviar_resumo()['status'], 'falha')
        self.assertFalse(self.config.envios.get().pode_repetir)

    def test_aceito_na_fila_nao_e_sucesso_de_transmissao(self):
        enviar_resumo()
        self.config.refresh_from_db()
        self.assertEqual(self.config.ultimo_status, 'EM_FILA')
        self.get.return_value.json.return_value = {'status': 'server_ack'}
        consultar_envios()
        self.config.refresh_from_db()
        self.assertEqual(self.config.ultimo_status, 'ENVIADO')
        self.assertEqual(self.config.envios.get().status, 'ENVIADO')

    def test_falha_na_fila_nao_e_repetida(self):
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'failed'}
        consultar_envios()
        self.avancar(16)
        self.assertEqual(enviar_resumo()['status'], 'ja_processado')
        self.assertEqual(self.post.call_count, 1)

    def test_reinicio_do_node_deixa_resultado_incerto(self):
        enviar_resumo()
        self.get.return_value.status_code = 404
        self.avancar(3)
        consultar_envios()
        self.assertEqual(self.config.envios.get().status, 'INCERTO')
        self.assertFalse(self.config.envios.get().pode_repetir)

    def test_confirmacao_tardia_recupera_resultado_incerto(self):
        self.post.side_effect = requests.Timeout()
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'server_ack'}
        consultar_envios()
        self.assertEqual(self.config.envios.get().status, 'ENVIADO')

    def test_retorno_sem_ack_nao_confirma_envio(self):
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'submitted', 'whatsapp_message_id': 'WA-TESTE', 'resolved_jid': '5585999999999@s.whatsapp.net'}
        consultar_envios()
        envio = self.config.envios.get()
        self.assertEqual(envio.status, 'AGUARDANDO')
        self.assertEqual(envio.whatsapp_message_id, 'WA-TESTE')
        self.assertEqual(envio.destino_resolvido, '5585999999999@s.whatsapp.net')

    def test_status_v1_nao_e_mais_considerado_confirmacao(self):
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'sent'}
        consultar_envios()
        self.assertEqual(self.config.envios.get().status, 'INCERTO')
        self.avancar(15)
        self.assertEqual(enviar_resumo()['status'], 'ja_processado')
        self.assertEqual(self.post.call_count, 1)

    def test_entrega_e_leitura_exigem_confirmacoes_distintas(self):
        enviar_resumo()
        for estado, esperado in [('server_ack', 'ENVIADO'), ('delivered', 'ENTREGUE'), ('read', 'LIDO')]:
            self.get.return_value.json.return_value = {'status': estado}
            consultar_envios()
            self.assertEqual(self.config.envios.get().status, esperado)

    def test_entrega_nao_regride_quando_evento_antigo_ou_404_chega(self):
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'delivered'}
        consultar_envios()
        self.get.return_value.json.return_value = {'status': 'submitted'}
        consultar_envios()
        self.get.return_value.status_code = 404
        self.avancar(20)
        consultar_envios()
        self.assertEqual(self.config.envios.get().status, 'ENTREGUE')

    def test_numero_nao_confirmado_exibe_motivo_sem_reenvio(self):
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'failed', 'error_code': 'DESTINO_NAO_CONFIRMADO'}
        consultar_envios()
        envio = self.config.envios.get()
        self.assertEqual(envio.status, 'FALHA')
        self.assertIn('Nenhuma mensagem foi transmitida', envio.detalhe)
        self.assertFalse(envio.pode_repetir)

    def test_retorno_antigo_nao_apaga_confirmacao(self):
        from .whatsapp import _registrar
        enviar_resumo()
        envio = self.config.envios.get()
        _registrar(envio, 'ENTREGUE', 'Entrega confirmada')
        _registrar(envio, 'EM_FILA', 'Resposta antiga')
        envio.refresh_from_db()
        self.assertEqual(envio.status, 'ENTREGUE')

    def test_grupo_nao_afirma_entrega_a_todos_os_participantes(self):
        self.config.grupo_destino = WhatsAppGroup.objects.create(nome='Grupo', jid='123@g.us')
        self.config.save()
        enviar_resumo()
        self.get.return_value.json.return_value = {'status': 'delivered', 'delivery_scope': 'participant'}
        consultar_envios()
        self.assertIn('pelo menos um participante', self.config.envios.get().detalhe)

    def test_migracao_nao_preserva_falsa_confirmacao_v1(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        enviar_resumo()
        EnvioWhatsAppBladder.objects.update(status='ENVIADO')
        ConfiguracaoWhatsAppBladder.objects.update(ultimo_status='ENVIADO')
        migration = import_module('bladder.migrations.0010_whatsapp_confirmacoes_reais')
        migration.preservar_confirmacoes_antigas(apps, Mock(connection=connection))
        self.config.refresh_from_db()
        self.assertEqual(self.config.ultimo_status, 'LEGADO')
        self.assertEqual(self.config.envios.get().status, 'LEGADO')

    def test_validacao_de_numero_e_dias(self):
        for numero in ('abc', '85999999999', '55 85 999999999', '５５８５９９９９９９９９９'):
            self.config.numero_destino = numero
            with self.assertRaises(ValidationError):
                self.config.full_clean()
        self.config.numero_destino = '5585999999999'
        for dias in ('', '0,7', 'segunda', '0,,1'):
            self.config.dias_semana = dias
            with self.assertRaises(ValidationError):
                self.config.full_clean()

    def test_resumo_inclui_estoque_real_e_classificacao(self):
        ProdutoBladder.objects.create(codigo='BLA-CRITICO', descricao='100', estoque_minimo=10, estoque_atual=5)
        ProdutoBladder.objects.create(codigo='BLA-ATENCAO', descricao='200', estoque_minimo=10, estoque_atual=15)
        ProdutoBladder.objects.create(codigo='BLA-NORMAL', descricao='300', estoque_minimo=10, estoque_atual=20)
        texto = gerar_texto_resumo_estoque_whatsapp()
        self.assertIn('BLA-CRITICO', texto)
        self.assertIn('BLA-ATENCAO', texto)
        self.assertIn('*40 un*', texto)
        self.assertIn('*1* / 3', texto)

    def test_admin_exibe_botao_e_historico_e_nao_envia_em_get(self):
        self.client.force_login(self.user)
        url = reverse('admin:bladder_configuracaowhatsappbladder_change', args=[self.config.pk])
        response = self.client.get(url)
        self.assertContains(response, 'Salvar e enviar teste ao número individual')
        self.assertContains(response, 'Últimos envios')
        self.post.assert_not_called()

    def dados_admin(self):
        return {'habilitado': 'on', 'numero_destino': self.config.numero_destino,
                'horario_envio': '07:30:00', 'dias_semana': '0,1,2,3,4', '_enviar_teste': '1'}

    def test_admin_salva_e_envia_com_autoria(self):
        self.client.force_login(self.user)
        url = reverse('admin:bladder_configuracaowhatsappbladder_change', args=[self.config.pk])
        dados = self.dados_admin()
        dados['numero_destino'] = '5585999998888'
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, dados)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.post.call_args.kwargs['json']['numero'], '5585999998888')
        self.assertEqual(self.config.envios.get().solicitado_por, self.user)

    def test_admin_formulario_invalido_nao_envia(self):
        self.client.force_login(self.user)
        dados = self.dados_admin()
        dados['numero_destino'] = 'incorreto'
        response = self.client.post(reverse('admin:bladder_configuracaowhatsappbladder_change', args=[self.config.pk]), dados)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Informe somente dígitos')
        self.post.assert_not_called()

    def test_admin_somente_leitura_nao_pode_enviar(self):
        viewer = User.objects.create_user('viewer_whatsapp', password='test', is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename='view_configuracaowhatsappbladder'))
        self.client.force_login(viewer)
        url = reverse('admin:bladder_configuracaowhatsappbladder_change', args=[self.config.pk])
        self.assertNotContains(self.client.get(url), 'name="_enviar_teste"')
        self.assertEqual(self.client.post(url, self.dados_admin()).status_code, 403)
        self.post.assert_not_called()

    def test_admin_exige_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = reverse('admin:bladder_configuracaowhatsappbladder_change', args=[self.config.pk])
        self.assertEqual(client.post(url, self.dados_admin()).status_code, 403)
        self.post.assert_not_called()

    def test_comando_preview_e_dry_run_nao_fazem_http(self):
        for argumento in ('--preview', '--dry-run'):
            call_command('enviar_resumo_estoque_bladder', argumento, stdout=io.StringIO())
        self.post.assert_not_called()
        self.get.assert_not_called()
        self.assertFalse(self.config.envios.exists())

    @override_settings(DEBUG=True)
    def test_verificacao_instalacao_rejeita_desenvolvimento(self):
        with self.assertRaises(CommandError):
            call_command('enviar_resumo_estoque_bladder', '--verificar-instalacao', stdout=io.StringIO())
        self.post.assert_not_called()
