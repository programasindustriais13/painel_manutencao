from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import requests

from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError

from production.models import ProductionGlobalAlarm, WhatsAppAlertRecipient
from maintenance.models import WhatsAppGroup
from production.maintenance_alerts import MaintenanceAlertService
from production.routers import ScadaRouter


class MaintenanceAlertsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.recipient_1 = WhatsAppAlertRecipient.objects.create(
            nome="Técnico João",
            telefone="31988887777",
            ativo=True,
        )
        cls.recipient_2 = WhatsAppAlertRecipient.objects.create(
            nome="Técnico Maria",
            telefone="31977776666",
            ativo=True,
        )
        cls.recipient_inativo = WhatsAppAlertRecipient.objects.create(
            nome="Técnico Inativo",
            telefone="31955554444",
            ativo=False,
        )
        cls.grupo_manutencao = WhatsAppGroup.objects.create(
            nome="Manutenção Industrial",
            jid="120363029999999999@g.us",
            is_active=True,
        )
        cls.grupo_inativo = WhatsAppGroup.objects.create(
            nome="Grupo Desativado",
            jid="120363028888888888@g.us",
            is_active=False,
        )

    def setUp(self):
        self.alarm_pressao = ProductionGlobalAlarm.objects.create(
            nome="Pressão Linha 1",
            chave="pressao_linha_1",
            xid="DP_PRESSAO_01",
            unidade="bar",
            valor_minimo=5.0,
            valor_maximo=7.0,
            delay_segundos=60,
            intervalo_repeticao_minutos=10,
            habilitado=True,
            notificar_normalizacao=True,
        )
        self.alarm_pressao.destinatarios.add(self.recipient_1)
        self.alarm_pressao.grupos.add(self.grupo_manutencao)

    # 1. Dentro da faixa -> nenhuma mensagem
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_01_dentro_da_faixa_nenhuma_mensagem(self, mock_send):
        scada_values = {"DP_PRESSAO_01": {"value": 6.0, "is_null": False}}
        res = MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values)
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        mock_send.assert_not_called()

    # 2. Abaixo do mínimo -> entra PENDENTE
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_02_abaixo_do_minimo_entra_pendente(self, mock_send):
        scada_values = {"DP_PRESSAO_01": {"value": 4.5, "is_null": False}}
        t0 = timezone.now()
        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values, now=t0)
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "PENDENTE")
        self.assertIsNotNone(self.alarm_pressao.inicio_fora_faixa)
        mock_send.assert_not_called()

    # 3. Acima do máximo -> entra PENDENTE
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_03_acima_do_maximo_entra_pendente(self, mock_send):
        scada_values = {"DP_PRESSAO_01": {"value": 7.5, "is_null": False}}
        t0 = timezone.now()
        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values, now=t0)
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "PENDENTE")
        mock_send.assert_not_called()

    # 4. Normaliza antes do delay -> nenhuma mensagem
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_04_normaliza_antes_do_delay_nenhuma_mensagem(self, mock_send):
        t0 = timezone.now()
        # Ciclo 1: Sai da faixa (4.8 bar)
        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 4.8, "is_null": False}},
            now=t0,
        )
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "PENDENTE")

        # Ciclo 2: 30 segundos depois (delay é 60s), volta ao normal (5.5 bar)
        t1 = t0 + timedelta(seconds=30)
        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 5.5, "is_null": False}},
            now=t1,
        )
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        self.assertIsNone(self.alarm_pressao.inicio_fora_faixa)
        mock_send.assert_not_called()

    # 5. Permanece fora pelo delay -> primeiro alerta
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_05_permanece_fora_pelo_delay_primeiro_alerta(self, mock_send):
        t0 = timezone.now()
        # Sai da faixa
        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 4.8, "is_null": False}},
            now=t0,
        )
        # 65 segundos depois (delay é 60s)
        t1 = t0 + timedelta(seconds=65)
        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 4.8, "is_null": False}},
            now=t1,
        )
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "ALARME_ATIVO")
        self.assertTrue(self.alarm_pressao.alerta_inicial_enviado)
        self.assertEqual(mock_send.call_count, 2)  # 1 individual + 1 grupo

        # Verifica conteúdo da mensagem
        args, _ = mock_send.call_args
        mensagem = args[1]
        self.assertIn("ALERTA DE MANUTENÇÃO", mensagem)
        self.assertIn("Pressão Linha 1", mensagem)
        self.assertIn("4.8 bar", mensagem)
        self.assertIn("5.0 a 7.0 bar", mensagem)

    # 6. Continua fora antes do intervalo de repetição -> nenhuma mensagem
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_06_continua_fora_antes_da_repeticao_sem_mensagem(self, mock_send):
        t0 = timezone.now()
        # Entra em alarme no t0
        self.alarm_pressao.estado_atual = "ALARME_ATIVO"
        self.alarm_pressao.inicio_fora_faixa = t0 - timedelta(minutes=2)
        self.alarm_pressao.ultimo_alerta_enviado_em = t0
        self.alarm_pressao.alerta_inicial_enviado = True
        self.alarm_pressao.save()

        # 5 minutos depois (intervalo de repetição é 10 minutos)
        t1 = t0 + timedelta(minutes=5)
        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 4.8, "is_null": False}},
            now=t1,
        )
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "ALARME_ATIVO")
        mock_send.assert_not_called()

    # 7. Alcança repetição -> nova mensagem
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_07_alcanca_repeticao_nova_mensagem(self, mock_send):
        t0 = timezone.now()
        self.alarm_pressao.estado_atual = "ALARME_ATIVO"
        self.alarm_pressao.inicio_fora_faixa = t0 - timedelta(minutes=15)
        self.alarm_pressao.ultimo_alerta_enviado_em = t0
        self.alarm_pressao.alerta_inicial_enviado = True
        self.alarm_pressao.save()

        # 10 minutos e 1 segundo depois (intervalo é 10m)
        t1 = t0 + timedelta(minutes=10, seconds=1)
        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 4.6, "is_null": False}},
            now=t1,
        )
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(mock_send.call_count, 2)
        self.assertEqual(self.alarm_pressao.ultimo_alerta_enviado_em, t1)

    # 8. Normaliza -> uma mensagem de recuperação
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_08_normaliza_uma_mensagem_recuperacao(self, mock_send):
        t0 = timezone.now()
        self.alarm_pressao.estado_atual = "ALARME_ATIVO"
        self.alarm_pressao.inicio_fora_faixa = t0 - timedelta(minutes=15)
        self.alarm_pressao.ultimo_alerta_enviado_em = t0 - timedelta(minutes=10)
        self.alarm_pressao.alerta_inicial_enviado = True
        self.alarm_pressao.save()

        # Volta a 5.8 bar (faixa normal)
        t1 = t0 + timedelta(minutes=2)
        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 5.8, "is_null": False}},
            now=t1,
        )
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        self.assertEqual(mock_send.call_count, 2)

        args, _ = mock_send.call_args
        mensagem = args[1]
        self.assertIn("NORMALIZADO", mensagem)
        self.assertIn("Pressão Linha 1", mensagem)
        self.assertIn("5.8 bar", mensagem)

    # 9. Ciclos seguintes normal -> não repete recuperação
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_09_ciclos_seguintes_normal_nao_repete_recuperacao(self, mock_send):
        t0 = timezone.now()
        # Já está normal
        self.alarm_pressao.estado_atual = "NORMAL"
        self.alarm_pressao.save()

        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 6.2, "is_null": False}},
            now=t0,
        )
        mock_send.assert_not_called()

    # 10. Alarme desabilitado -> não envia
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_10_alarme_desabilitado_nao_envia(self, mock_send):
        self.alarm_pressao.habilitado = False
        self.alarm_pressao.save()

        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 3.0, "is_null": False}},
            now=timezone.now(),
        )
        mock_send.assert_not_called()

    # 11. Reabilitação começa nova avaliação do zero
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_11_reabilitacao_comeca_nova_avaliacao(self, mock_send):
        self.alarm_pressao.habilitado = False
        self.alarm_pressao.estado_atual = "DESABILITADO"
        self.alarm_pressao.inicio_fora_faixa = timezone.now() - timedelta(hours=2)
        self.alarm_pressao.save()

        # Reabilita
        self.alarm_pressao.habilitado = True
        self.alarm_pressao.full_clean()
        self.alarm_pressao.save()

        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        self.assertIsNone(self.alarm_pressao.inicio_fora_faixa)

    # 12. Apenas mínimo configurado
    def test_12_apenas_minimo_configurado(self):
        alarm = ProductionGlobalAlarm(
            nome="Vácuo Mínimo",
            chave="vacuo_min",
            xid="DP_VACUO",
            valor_minimo=0.5,
            valor_maximo=None,
        )
        alarm.full_clean()
        self.assertEqual(alarm.faixa_formatada, "mínimo 0.5")

    # 13. Apenas máximo configurado
    def test_13_apenas_maximo_configurado(self):
        alarm = ProductionGlobalAlarm(
            nome="Temperatura Máxima",
            chave="temp_max",
            xid="DP_TEMP",
            unidade="°C",
            valor_minimo=None,
            valor_maximo=180.0,
        )
        alarm.full_clean()
        self.assertEqual(alarm.faixa_formatada, "máximo 180.0 °C")

    # 14. Mínimo + Máximo
    def test_14_minimo_e_maximo_configurados(self):
        alarm = ProductionGlobalAlarm(
            nome="Pressão Linha",
            chave="pressao_ambos",
            xid="DP_P_AMBOS",
            valor_minimo=4.0,
            valor_maximo=8.0,
        )
        alarm.full_clean()
        self.assertEqual(alarm.faixa_formatada, "4.0 a 8.0")

    # 15. Mínimo >= Máximo rejeitado
    def test_15_minimo_maior_ou_igual_maximo_rejeitado(self):
        # Mínimo > Máximo
        a1 = ProductionGlobalAlarm(
            nome="Inválido 1",
            chave="inv_1",
            valor_minimo=10.0,
            valor_maximo=5.0,
        )
        with self.assertRaises(ValidationError):
            a1.full_clean()

        # Mínimo == Máximo
        a2 = ProductionGlobalAlarm(
            nome="Inválido 2",
            chave="inv_2",
            valor_minimo=5.0,
            valor_maximo=5.0,
        )
        with self.assertRaises(ValidationError):
            a2.full_clean()

        # Nenhum dos dois configurado rejeitado no AdminForm
        from production.admin import ProductionGlobalAlarmAdminForm
        form = ProductionGlobalAlarmAdminForm(data={
            "nome": "Inválido 3",
            "chave": "inv_3",
            "valor_minimo": "",
            "valor_maximo": "",
            "delay_segundos": 60,
            "intervalo_repeticao_minutos": 10,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("Pelo menos um limite", str(form.errors))

    # 16. Leitura None -> não gera alarme de valor 0
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_16_leitura_none_nao_gera_falso_alarme(self, mock_send):
        scada_values = {"DP_PRESSAO_01": None}
        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values)
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        mock_send.assert_not_called()

    # 17. Leitura inválida (não numérica) -> não gera alarme
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_17_leitura_invalida_nao_gera_alarme(self, mock_send):
        scada_values = {"DP_PRESSAO_01": {"value": "TEXTO_INVALIDO", "is_null": False}}
        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values)
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        mock_send.assert_not_called()

    # 18. SCADA offline (dicionário vazio) -> sem alarme
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_18_scada_offline_sem_alarme(self, mock_send):
        MaintenanceAlertService.evaluate_due_alerts(scada_values={})
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        mock_send.assert_not_called()

    # 19. Stale (is_null=True) -> sem alarme
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_19_stale_sem_alarme(self, mock_send):
        scada_values = {"DP_PRESSAO_01": {"value": 0.0, "is_null": True}}
        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values)
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "NORMAL")
        mock_send.assert_not_called()

    # 20. Destinatário individual
    def test_20_destinatario_individual_normalizacao_telefone(self):
        rec = WhatsAppAlertRecipient(nome="Teste", telefone="(31) 98888-1122")
        self.assertEqual(rec.telefone_normalizado, "5531988881122")

    # 21. Grupo WhatsApp
    def test_21_grupo_whatsapp_reutilizado(self):
        self.assertIn(self.grupo_manutencao, self.alarm_pressao.grupos.all())

    # 22. Múltiplos destinos
    def test_22_multiplos_destinos_configurados(self):
        self.alarm_pressao.destinatarios.add(self.recipient_2)
        self.assertEqual(self.alarm_pressao.destinatarios.count(), 2)
        self.assertEqual(self.alarm_pressao.grupos.count(), 1)

    # 23. Destinos inativos ignorados
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_23_destinos_inativos_ignorados(self, mock_send):
        self.alarm_pressao.destinatarios.clear()
        self.alarm_pressao.grupos.clear()
        self.alarm_pressao.destinatarios.add(self.recipient_inativo)
        self.alarm_pressao.grupos.add(self.grupo_inativo)

        t0 = timezone.now()
        # Entra em alarme ativo
        self.alarm_pressao.estado_atual = "PENDENTE"
        self.alarm_pressao.inicio_fora_faixa = t0 - timedelta(seconds=120)
        self.alarm_pressao.save()

        MaintenanceAlertService.evaluate_due_alerts(
            scada_values={"DP_PRESSAO_01": {"value": 3.0, "is_null": False}},
            now=t0,
        )
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.estado_atual, "ALARME_ATIVO")
        # Nenhuma mensagem enviada porque nenhum destino ativo está presente
        mock_send.assert_not_called()

    # 24. Múltiplos alarmes simultâneos consolidados por destino (anti-spam)
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_24_multiplos_alarmes_consolidados_por_destino(self, mock_send):
        alarm_nivel = ProductionGlobalAlarm.objects.create(
            nome="Nível Tanque",
            chave="nivel_tanque",
            xid="DP_NIVEL_01",
            unidade="%",
            valor_minimo=25.0,
            delay_segundos=60,
            habilitado=True,
        )
        # Ambos os alarmes vão para o mesmo grupo
        alarm_nivel.grupos.add(self.grupo_manutencao)

        t0 = timezone.now()
        # Coloca ambos em PENDENTE com delay estourado
        self.alarm_pressao.estado_atual = "PENDENTE"
        self.alarm_pressao.inicio_fora_faixa = t0 - timedelta(seconds=100)
        self.alarm_pressao.save()

        alarm_nivel.estado_atual = "PENDENTE"
        alarm_nivel.inicio_fora_faixa = t0 - timedelta(seconds=100)
        alarm_nivel.save()

        scada_values = {
            "DP_PRESSAO_01": {"value": 4.2, "is_null": False},
            "DP_NIVEL_01": {"value": 15.0, "is_null": False},
        }

        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values, now=t0)

        # Para o grupo, deve haver APENAS UMA ÚNICA chamada consolidada!
        chamadas_grupo = [call for call in mock_send.call_args_list if call[0][0] == self.grupo_manutencao.jid]
        self.assertEqual(len(chamadas_grupo), 1)

        msg_consolidada = chamadas_grupo[0][0][1]
        self.assertIn("Pressão Linha 1", msg_consolidada)
        self.assertIn("Nível Tanque", msg_consolidada)
        self.assertIn("4.2 bar", msg_consolidada)
        self.assertIn("15.0 %", msg_consolidada)

    # 25. Node retorna 202
    @patch("requests.post")
    def test_25_node_retorna_202(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_post.return_value = mock_resp

        sucesso = MaintenanceAlertService.send_whatsapp_message("5531999999999", "Teste 202")
        self.assertTrue(sucesso)

    # 26. Node retorna 429
    @patch("requests.post")
    def test_26_node_retorna_429(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_post.return_value = mock_resp

        sucesso = MaintenanceAlertService.send_whatsapp_message("5531999999999", "Teste 429")
        self.assertFalse(sucesso)

    # 27. Node retorna 503
    @patch("requests.post")
    def test_27_node_retorna_503(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_post.return_value = mock_resp

        sucesso = MaintenanceAlertService.send_whatsapp_message("5531999999999", "Teste 503")
        self.assertFalse(sucesso)

    # 28. Node offline (RequestException)
    @patch("requests.post")
    def test_28_node_offline_nao_lanca_excecao(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

        sucesso = MaintenanceAlertService.send_whatsapp_message("5531999999999", "Teste Offline")
        self.assertFalse(sucesso)

    # 29. Restart/segunda avaliação não duplica envio
    @patch.object(MaintenanceAlertService, "send_whatsapp_message")
    def test_29_segunda_avaliacao_imediata_nao_duplica_envio(self, mock_send):
        t0 = timezone.now()
        # Dispara primeiro alerta
        self.alarm_pressao.estado_atual = "PENDENTE"
        self.alarm_pressao.inicio_fora_faixa = t0 - timedelta(seconds=70)
        self.alarm_pressao.save()

        scada_values = {"DP_PRESSAO_01": {"value": 4.5, "is_null": False}}
        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values, now=t0)
        self.assertEqual(mock_send.call_count, 2)

        # Imediatamente após (novo ciclo do coletor 5 segundos depois)
        mock_send.reset_mock()
        t1 = t0 + timedelta(seconds=5)
        MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values, now=t1)
        # Não deve enviar nada
        mock_send.assert_not_called()

    # 30. Router mantém models novos no banco default
    def test_30_router_mantem_models_no_default(self):
        router = ScadaRouter()
        self.assertEqual(router.db_for_read(WhatsAppAlertRecipient), "default")
        self.assertEqual(router.db_for_write(WhatsAppAlertRecipient), "default")
        self.assertEqual(router.db_for_read(ProductionGlobalAlarm), "default")
        self.assertEqual(router.db_for_write(ProductionGlobalAlarm), "default")

    # 31. Nenhuma escrita no scada
    def test_31_nenhuma_escrita_no_scada(self):
        self.assertEqual(self.alarm_pressao._state.db, "default")
        self.assertEqual(self.recipient_1._state.db, "default")

    # 32. Busca automática de XIDs ausentes no scada_values (ex: ciclo do coletor)
    @patch("production.services.scada_reader.get_last_values_batch")
    def test_32_busca_xids_de_alarmes_faltantes_no_scada_values(self, mock_get_batch):
        mock_get_batch.return_value = {
            "DP_PRESSAO_01": {"value": 11.17, "is_null": False, "ts_ms": 1000}
        }
        # Passa um scada_values que NÃO contém DP_PRESSAO_01 (como o retornado por process_scada_cycle)
        scada_values_parcial = {"DP_PRENSA_01_STATUS": {"value": 1, "is_null": False}}
        res = MaintenanceAlertService.evaluate_due_alerts(scada_values=scada_values_parcial)

        # Deve ter consultado o XID faltante no SCADA
        mock_get_batch.assert_called_once_with(["DP_PRESSAO_01"])
        self.alarm_pressao.refresh_from_db()
        self.assertEqual(self.alarm_pressao.ultima_leitura_valor, 11.17)
        self.assertIsNotNone(self.alarm_pressao.ultima_leitura_timestamp)
        # Como 11.17 < 12.0 (ou fora da faixa 5.0 a 7.0 no mock do test case), entra em PENDENTE
        self.assertEqual(self.alarm_pressao.estado_atual, "PENDENTE")
