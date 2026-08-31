import io
from datetime import datetime, timedelta, time as dt_time
from unittest.mock import patch, MagicMock
import openpyxl

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.db import connections

from production.models import (
    ProductionGlobalParameter,
    ScadaDataPoint,
    ScadaPointValue,
    ScadaPointValueAnnotation,
)
from production.services_caldeira import (
    CaldeiraHistoricalService,
    CALDEIRA_VARIABLES_CONFIG,
)
from production.services_calandra import (
    CalandraHistoricalService,
    CALANDRA_VARIABLES_CONFIG,
)
from production.tests import init_scada_test_tables


class CaldeiraReportTestCase(TestCase):
    """
    Suíte completa de testes automatizados para a Central de Relatórios de Máquinas,
    Relatório Histórico da Caldeira 2, Cálculos de Pressão, Totalizador de Condensado,
    Cadastro de XIDs e Exportação Excel Multi-Abas.
    """

    databases = {"default", "scada"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        init_scada_test_tables()

    def setUp(self):
        self.client = Client()

        # Grupos padrão
        self.grp_lp, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.grp_op, _ = Group.objects.get_or_create(name="Operadores")
        self.grp_pcp, _ = Group.objects.get_or_create(name="PCP")
        self.grp_tec, _ = Group.objects.get_or_create(name="Tecnicos")
        self.grp_tv, _ = Group.objects.get_or_create(name="Visualizador")

        # Usuários para matriz de permissões
        self.user_lp = User.objects.create_user("caldeira_user_lp", "lp_cald@test.com", "pass123")
        self.user_lp.groups.add(self.grp_lp)

        self.user_op = User.objects.create_user("caldeira_user_op", "op_cald@test.com", "pass123")
        self.user_op.groups.add(self.grp_op)

        self.user_pcp = User.objects.create_user("caldeira_user_pcp", "pcp_cald@test.com", "pass123")
        self.user_pcp.groups.add(self.grp_pcp)

        self.user_admin = User.objects.create_superuser("caldeira_user_admin", "admin_cald@test.com", "pass123")

        self.user_tec = User.objects.create_user("caldeira_user_tec", "tec_cald@test.com", "pass123")
        self.user_tec.groups.add(self.grp_tec)

        self.user_tv = User.objects.create_user("caldeira_user_tv", "tv_cald@test.com", "pass123")
        self.user_tv.groups.add(self.grp_tv)

        # Popular DataPoints da Caldeira e Calandra no banco de teste 'scada'
        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalues WHERE dataPointId >= 100 AND dataPointId <= 300;")
            cursor.execute("DELETE FROM datapoints WHERE id >= 100 AND id <= 300;")

            self.dp_map = {}
            for idx, var in enumerate(CALDEIRA_VARIABLES_CONFIG, start=200):
                cursor.execute(
                    "INSERT INTO datapoints (id, xid, dataSourceId, pointName, plcAlarmLevel) VALUES (%s, %s, %s, %s, %s);",
                    (idx, var["tag_name"], 1, var["tag_name"], 0)
                )
                self.dp_map[var["key"]] = idx

            # Calandra DPs para testes de não-regressão
            for idx, var in enumerate(CALANDRA_VARIABLES_CONFIG, start=100):
                cursor.execute(
                    "INSERT INTO datapoints (id, xid, dataSourceId, pointName, plcAlarmLevel) VALUES (%s, %s, %s, %s, %s);",
                    (idx, var["tag_name"], 1, var["tag_name"], 0)
                )

    # ─────────────────────────────────────────────────────────────────────────
    # 1. TESTES DE PERMISSÕES E ACESSO
    # ─────────────────────────────────────────────────────────────────────────

    def test_hub_access_contains_caldeira_and_calandra(self):
        """Central de Relatórios de Máquinas exibe cards de Calandra e Caldeira 2 para autorizados."""
        self.client.force_login(self.user_lp)
        resp = self.client.get(reverse("production:machine_reports_hub"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Calandra")
        self.assertContains(resp, "Caldeira 2")

    def test_caldeira_report_access_permissions(self):
        """Acesso à tela de relatório da Caldeira é restrito a perfis autorizados."""
        self.client.force_login(self.user_lp)
        resp = self.client.get(reverse("production:caldeira_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Caldeira 2")
        self.assertContains(resp, "Distribuição de Vapor e Utilidades")

        # Técnico não autorizado
        self.client.force_login(self.user_tec)
        resp_blocked = self.client.get(reverse("production:caldeira_report"))
        self.assertEqual(resp_blocked.status_code, 302)

    def test_caldeira_excel_export_permissions(self):
        """Exportação Excel da Caldeira é restrita a perfis autorizados."""
        self.client.force_login(self.user_op)
        resp = self.client.get(reverse("production:caldeira_export_excel"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        self.client.force_login(self.user_tv)
        resp_blocked = self.client.get(reverse("production:caldeira_export_excel"))
        self.assertEqual(resp_blocked.status_code, 302)

    def test_xid_caldeira_config_permissions(self):
        """Tela de configuração de XIDs da Caldeira exige estritamente superusuário."""
        self.client.force_login(self.user_admin)
        resp = self.client.get(reverse("production:xid_caldeira_config"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Configuração de XIDs da Caldeira 2")

        # Usuários não superuser são bloqueados
        for user in [self.user_lp, self.user_op, self.user_tec, self.user_pcp]:
            self.client.force_login(user)
            resp_blocked = self.client.get(reverse("production:xid_caldeira_config"))
            self.assertEqual(resp_blocked.status_code, 302)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. TESTES DE CONFIGURAÇÃO DE XIDS
    # ────────────────────────────────────────────────────────────────---------

    def test_xid_caldeira_config_save_and_restore(self):
        """Salvar e restaurar configurações de XIDs da Caldeira."""
        self.client.force_login(self.user_admin)

        post_data = {
            "action": "save_caldeira_xids",
            "xid_pressao_caldeira": "CUSTOM_CALDEIRA_PRESS",
            "xid_setpoint_pressao_alta": "CUSTOM_SETPOINT",
            "xid_volume_condensado": "DP_153208",
        }
        resp = self.client.post(reverse("production:xid_caldeira_config"), data=post_data)
        self.assertEqual(resp.status_code, 302)

        param = ProductionGlobalParameter.objects.get(chave="caldeira_pressao_caldeira")
        self.assertEqual(param.xid, "CUSTOM_CALDEIRA_PRESS")

        # Testar restauração de padrões
        resp_restore = self.client.post(reverse("production:xid_caldeira_config"), data={"action": "restore_defaults"})
        self.assertEqual(resp_restore.status_code, 302)
        self.assertFalse(ProductionGlobalParameter.objects.filter(chave__startswith="caldeira_").exists())

    def test_xid_test_api_mock(self):
        """Teste de leitura via API AJAX retorna dados amigáveis sem expor o banco."""
        self.client.force_login(self.user_admin)

        with patch("production.xid_configuration.scada_reader") as mock_reader:
            mock_reader.get_data_point_ids.return_value = {"DP_153208": 205}
            mock_reader.get_last_values_batch.return_value = {
                "DP_153208": {"value": 12500.5, "data_type": 3, "ts": 1700000000000, "str_value": "12500.5"}
            }

            resp = self.client.post(
                reverse("production:xid_test_api"),
                data={"xid": "DP_153208"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["status"], "OK")
            self.assertEqual(data["value"], 12500.5)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. TESTES DE FILTRO TEMPORAL E RESILIÊNCIA
    # ─────────────────────────────────────────────────────────────────────────

    def test_period_filters_and_empty_state(self):
        """Validação de períodos válidos, inválidos e estado vazio sem erro 500."""
        self.client.force_login(self.user_lp)

        # Período válido sem dados
        resp = self.client.get(reverse("production:caldeira_report") + "?periodo=ontem")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Não existem leituras da Caldeira para o período selecionado.")

        # Data inicial maior que data final
        resp_inv = self.client.get(
            reverse("production:caldeira_report") + "?periodo=personalizado&data_inicio=2026-12-31&data_final=2026-01-01"
        )
        self.assertEqual(resp_inv.status_code, 200)

        # Exportação Excel em período sem dados não dá erro 500
        resp_excel = self.client.get(reverse("production:caldeira_export_excel") + "?periodo=ontem")
        self.assertEqual(resp_excel.status_code, 200)

    # ─────────────────────────────────────────────────────────────────────────
    # 4. TESTES DE CÁLCULOS ESTATÍSTICOS DE PRESSÃO E DESVIOS
    # ─────────────────────────────────────────────────────────────────────────

    def test_pressure_and_setpoint_deviation_calculations(self):
        """Testa média, min, max, amplitude, desvios do setpoint amostra a amostra e diferenças entre linhas."""
        now = timezone.now()
        t1 = int(now.timestamp() * 1000)
        t2 = t1 + 60000
        t3 = t1 + 120000

        with connections["scada"].cursor() as cursor:
            # Amostra 1: Caldeira=13.0, SP=10.0, P1=9.8, P2=9.5, PBX1=3.0, PBX2=2.8
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_caldeira"], 13.0, t1))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["setpoint_pressao_alta"], 10.0, t1))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_alta_prensas_1_7"], 9.8, t1))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_alta_prensas_8_12"], 9.5, t1))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_baixa_prensas_1_7"], 3.0, t1))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_baixa_prensas_8_12"], 2.8, t1))

            # Amostra 2: Caldeira=13.2, SP=10.0, P1=10.2, P2=9.6, PBX1=3.1, PBX2=2.9
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_caldeira"], 13.2, t2))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["setpoint_pressao_alta"], 10.0, t2))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_alta_prensas_1_7"], 10.2, t2))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_alta_prensas_8_12"], 9.6, t2))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_baixa_prensas_1_7"], 3.1, t2))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_baixa_prensas_8_12"], 2.9, t2))

            # Amostra 3: Caldeira=13.4, SP=10.5 (setpoint variou!), P1=10.4, P2=9.7
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_caldeira"], 13.4, t3))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["setpoint_pressao_alta"], 10.5, t3))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_alta_prensas_1_7"], 10.4, t3))
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 3, %s, %s);", (self.dp_map["pressao_alta_prensas_8_12"], 9.7, t3))

        start_dt = now - timedelta(minutes=10)
        end_dt = now + timedelta(minutes=10)

        history = CaldeiraHistoricalService.get_synchronized_history(start_dt, end_dt)
        stats = history["stats"]
        var_stats = stats["variables"]
        deviations = stats["deviations"]
        comparisons = stats["comparisons"]

        # Pressão da Caldeira: (13.0 + 13.2 + 13.4) / 3 = 13.2
        self.assertEqual(var_stats["pressao_caldeira"]["avg"], 13.2)
        self.assertEqual(var_stats["pressao_caldeira"]["min"], 13.0)
        self.assertEqual(var_stats["pressao_caldeira"]["max"], 13.4)
        self.assertEqual(var_stats["pressao_caldeira"]["amplitude"], 0.4)

        # Desvios de Linha 1-7 em relação ao Setpoint amostra a amostra:
        # t1: 9.8 - 10.0 = -0.2 (abs: 0.2)
        # t2: 10.2 - 10.0 = +0.2 (abs: 0.2)
        # t3: 10.4 - 10.5 = -0.1 (abs: 0.1)
        # Média Absoluta: (0.2 + 0.2 + 0.1) / 3 = 0.5 / 3 = 0.17
        self.assertEqual(deviations["linha_1_7"]["avg_abs"], 0.17)

        # Desvios de Linha 8-12:
        # t1: 9.5 - 10.0 = -0.5 (abs: 0.5)
        # t2: 9.6 - 10.0 = -0.4 (abs: 0.4)
        # t3: 9.7 - 10.5 = -0.8 (abs: 0.8)
        # Média Absoluta: (0.5 + 0.4 + 0.8) / 3 = 1.7 / 3 = 0.57
        self.assertEqual(deviations["linha_8_12"]["avg_abs"], 0.57)

        # Diferença entre Linhas de Alta (P1 - P2):
        # t1: 9.8 - 9.5 = 0.3
        # t2: 10.2 - 9.6 = 0.6
        # t3: 10.4 - 9.7 = 0.7
        # Média: (0.3 + 0.6 + 0.7) / 3 = 1.6 / 3 = 0.53
        self.assertEqual(comparisons["alta"]["avg_signed"], 0.53)

        # Diferença Caldeira × Linha 1 (PRESSCAL - P1):
        # t1: 13.0 - 9.8 = 3.2
        # t2: 13.2 - 10.2 = 3.0
        # t3: 13.4 - 10.4 = 3.0
        # Média: (3.2 + 3.0 + 3.0) / 3 = 9.2 / 3 = 3.07
        self.assertEqual(comparisons["caldeira_linha_1"]["avg_signed"], 3.07)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. TESTES DO TOTALIZADOR DE CONDENSADO (VOLUME_CAL)
    # ─────────────────────────────────────────────────────────────────────────

    def test_condensate_totalizer_simple_case(self):
        """Caso simples: 1000L, 1050L, 1100L -> Consumo de 100L."""
        now_ms = int(timezone.now().timestamp() * 1000)
        events = [
            {"ts": now_ms, "val": 1000.0},
            {"ts": now_ms + 3600000, "val": 1050.0},
            {"ts": now_ms + 7200000, "val": 1100.0},
        ]
        result = CaldeiraHistoricalService.compute_condensate_volume(events, now_ms, now_ms + 7200000)
        self.assertTrue(result["has_data"])
        self.assertEqual(result["total_liters"], 100.0)
        self.assertEqual(result["resets_count"], 0)
        self.assertEqual(result["first_cumulative"], 1000.0)
        self.assertEqual(result["last_cumulative"], 1100.0)
        # 2 horas cobertas: 100L / 2h = 50 L/h
        self.assertEqual(result["avg_liters_per_hour"], 50.0)

    def test_condensate_totalizer_with_reset_in_middle(self):
        """Reset no meio do período: 1000L -> 1050L -> 10L -> 40L -> 50L + 30L = 80L com 1 reset."""
        now_ms = int(timezone.now().timestamp() * 1000)
        events = [
            {"ts": now_ms, "val": 1000.0},
            {"ts": now_ms + 3600000, "val": 1050.0},
            {"ts": now_ms + 7200000, "val": 10.0},  # Reset / Rollover
            {"ts": now_ms + 10800000, "val": 40.0},
        ]
        result = CaldeiraHistoricalService.compute_condensate_volume(events, now_ms, now_ms + 10800000)
        self.assertTrue(result["has_data"])
        self.assertEqual(result["total_liters"], 80.0)
        self.assertEqual(result["resets_count"], 1)

    def test_condensate_totalizer_edge_cases(self):
        """Testa casos de borda: apenas 1 leitura, nenhuma leitura, leituras iguais, seed anterior e duplicatas."""
        now_ms = int(timezone.now().timestamp() * 1000)

        # 1. Nenhuma leitura
        r_empty = CaldeiraHistoricalService.compute_condensate_volume([], now_ms, now_ms + 1000)
        self.assertFalse(r_empty["has_data"])

        # 2. Apenas 1 leitura sem seed
        r_single = CaldeiraHistoricalService.compute_condensate_volume([{"ts": now_ms, "val": 500.0}], now_ms, now_ms + 1000)
        self.assertEqual(r_single["formatted_liters"], "Dados insuficientes")

        # 3. Leitura com seed anterior
        r_seed = CaldeiraHistoricalService.compute_condensate_volume([{"ts": now_ms + 3600000, "val": 550.0}], now_ms, now_ms + 3600000, seed_reading=500.0)
        self.assertEqual(r_seed["total_liters"], 50.0)

        # 4. Leituras iguais (sem consumo)
        r_same = CaldeiraHistoricalService.compute_condensate_volume([
            {"ts": now_ms, "val": 500.0},
            {"ts": now_ms + 1000, "val": 500.0}
        ], now_ms, now_ms + 1000)
        self.assertEqual(r_same["total_liters"], 0.0)

        # 5. Entrada desordenada e com valores inválidos
        r_unordered = CaldeiraHistoricalService.compute_condensate_volume([
            {"ts": now_ms + 2000, "val": 520.0},
            {"ts": now_ms + 1000, "val": "inválido"},
            {"ts": now_ms, "val": 500.0},
        ], now_ms, now_ms + 2000)
        self.assertEqual(r_unordered["total_liters"], 20.0)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. TESTES DA EXPORTAÇÃO EXCEL
    # ─────────────────────────────────────────────────────────────────────────

    def test_excel_export_structure_and_print_setup(self):
        """Valida que o arquivo Excel possui 3 abas, abre no openpyxl, contém formatação e impressão A4 paisagem."""
        start_dt = timezone.now() - timedelta(hours=2)
        end_dt = timezone.now()

        excel_bytes = CaldeiraHistoricalService.generate_excel_report(start_dt, end_dt, generated_by="Auditor Teste")
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))

        # Abas esperadas
        sheet_names = wb.sheetnames
        self.assertIn("Resumo Gerencial", sheet_names)
        self.assertIn("Gráficos", sheet_names)
        self.assertIn("Dados Históricos", sheet_names)

        # Aba ativa padrão é a primeira
        self.assertEqual(wb.active.title, "Resumo Gerencial")

        # Aba 1: Resumo Gerencial
        ws1 = wb["Resumo Gerencial"]
        self.assertEqual(ws1.page_setup.orientation, ws1.ORIENTATION_LANDSCAPE)
        self.assertEqual(ws1.page_setup.fitToWidth, 1)

        # Aba 3: Dados Históricos
        ws3 = wb["Dados Históricos"]
        self.assertEqual(ws3.freeze_panes, "A2")
        self.assertEqual(ws3.page_setup.orientation, ws3.ORIENTATION_LANDSCAPE)

    # ─────────────────────────────────────────────────────────────────────────
    # 7. TESTES DE NÃO-REGRESSÃO DA CALANDRA
    # ─────────────────────────────────────────────────────────────────────────

    def test_calandra_report_no_regression(self):
        """Garante que a implementação da Caldeira não causou nenhuma regressão no relatório da Calandra."""
        self.client.force_login(self.user_lp)
        resp = self.client.get(reverse("production:calandra_report"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Calandra")

        resp_excel = self.client.get(reverse("production:calandra_export_excel"))
        self.assertEqual(resp_excel.status_code, 200)
