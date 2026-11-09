import io
import uuid
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, time as dt_time
from unittest.mock import patch, MagicMock
import openpyxl

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.db import connections
from django.core.management import call_command

from production.models import (
    CaldeiraAnalysisSettings,
    ProductionGlobalParameter,
    ScadaDataPoint,
    ScadaPointValue,
    ScadaPointValueAnnotation,
)
from production.services_caldeira import (
    CaldeiraHistoricalService,
    CALDEIRA_VARIABLES_CONFIG,
)
from production.services_caldeira_fast import CaldeiraFastReader, report_cache
from production.services_caldeira_insights import CaldeiraInsightsService
from production.caldeira_insights_excel import build_insights_excel
from production import caldeira_export_jobs
from production import caldeira_insights_jobs
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
        report_cache.clear()

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

    def test_long_excel_export_runs_outside_request_and_is_private(self):
        """Período longo inicia tarefa; somente o solicitante acompanha o estado."""
        job_id = uuid.uuid4()
        self.client.force_login(self.user_lp)
        with patch("production.views.start_caldeira_export_job", return_value=str(job_id)) as start:
            response = self.client.get(reverse("production:caldeira_export_excel") + "?periodo=7d")
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(job_id), response.url)
        start.assert_called_once()
        status_url = reverse("production:caldeira_export_status", args=[job_id])
        job = {"user_id": self.user_lp.pk, "status": "running",
               "created_at": timezone.now().isoformat()}
        with patch("production.views.read_caldeira_export_job", return_value=job):
            response = self.client.get(status_url)
        self.assertContains(response, "está sendo preparado")
        self.client.force_login(self.user_op)
        with patch("production.views.read_caldeira_export_job", return_value=job):
            response = self.client.get(status_url)
        self.assertEqual(response.status_code, 404)

    def test_background_excel_job_writes_file_and_marks_ready(self):
        """O processo auxiliar publica apenas o arquivo Excel completo."""
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(caldeira_export_jobs, "JOB_DIR", Path(directory)):
                start_dt = timezone.now() - timedelta(days=7)
                end_dt = timezone.now()
                with patch.object(caldeira_export_jobs.subprocess, "Popen") as process:
                    job_id = caldeira_export_jobs.start_job(self.user_lp, start_dt, end_dt)
                process.assert_called_once()
                self.assertEqual(caldeira_export_jobs.read_job(job_id)["status"], "queued")
                with patch.object(CaldeiraFastReader, "excel_file", return_value=io.BytesIO(b"xlsx-test")):
                    call_command("build_caldeira_export", job=uuid.UUID(job_id))
                self.assertEqual(caldeira_export_jobs.read_job(job_id)["status"], "ready")
                self.assertEqual(caldeira_export_jobs.output_path(job_id).read_bytes(), b"xlsx-test")
                self.client.force_login(self.user_lp)
                download_url = reverse("production:caldeira_export_status", args=[uuid.UUID(job_id)]) + "?download=1"
                response = self.client.get(download_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"xlsx-test")

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

    def test_fast_report_paginates_and_preserves_aggregates_and_excel_rows(self):
        """A página lê 50 registros e o resumo mantém os cálculos do histórico integral."""
        start_dt = timezone.now() - timedelta(minutes=2)
        start_ms = int((start_dt + timedelta(seconds=1)).timestamp() * 1000)
        rows = []
        for index in range(51):
            ts = start_ms + index * 1000
            rows.append((self.dp_map["pressao_caldeira"], 3, 13.0 + index / 100, ts))
        for index, value in ((0, 1000), (1, 1050), (2, 10), (3, 40)):
            rows.append((self.dp_map["volume_condensado"], 3, value, start_ms + index * 1000))
        for key, value in (("setpoint_pressao_alta", 10),
                           ("pressao_alta_prensas_1_7", 9.5),
                           ("pressao_alta_prensas_8_12", 9.0)):
            rows.append((self.dp_map[key], 3, value, start_ms))
        with connections["scada"].cursor() as cursor:
            cursor.executemany(
                "INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, %s, %s, %s)", rows
            )
        end_dt = start_dt + timedelta(minutes=3)
        fast = CaldeiraFastReader.summary(start_dt, end_dt)
        original = CaldeiraHistoricalService.get_synchronized_history(start_dt, end_dt)
        self.assertEqual(fast["total_records"], 51)
        self.assertEqual(fast["raw_points_count"], len(rows))
        self.assertEqual(fast["stats"]["variables"], original["stats"]["variables"])
        self.assertEqual(fast["stats"]["deviations"], original["stats"]["deviations"])
        self.assertEqual(fast["condensate_stats"]["total_liters"], 80)
        self.assertEqual(len(CaldeiraFastReader.page(start_dt, end_dt, 1, 51)), 50)
        self.assertEqual(len(CaldeiraFastReader.page(start_dt, end_dt, 2, 51)), 1)
        with CaldeiraFastReader.excel_file(start_dt, end_dt) as output:
            workbook = openpyxl.load_workbook(output, read_only=True)
            self.assertEqual(sum(1 for _ in workbook["Dados Históricos"].iter_rows()), 52)
            self.assertEqual(workbook["Dados Históricos"]["O3"].value, 50)
            self.assertEqual(workbook["Dados Históricos"]["O4"].value, 0)
            self.assertEqual(workbook["Dados Históricos"]["O5"].value, 30)
            workbook.close()
        with patch.object(CaldeiraFastReader, "EXCEL_MAX_DATA_ROWS", 20):
            with CaldeiraFastReader.excel_file(start_dt, end_dt) as output:
                workbook = openpyxl.load_workbook(output, read_only=True)
                self.assertEqual(
                    [name for name in workbook.sheetnames if name.startswith("Dados Históricos")],
                    ["Dados Históricos", "Dados Históricos 2", "Dados Históricos 3"],
                )
                self.assertEqual(sum(1 for _ in workbook["Dados Históricos 3"].iter_rows()), 12)
                workbook.close()

    def test_fast_full_day_segments_preserve_forward_fill_and_condensate(self):
        """Mesclar dias em cache mantém os resultados de uma consulta contínua."""
        first_date = timezone.localtime().date() - timedelta(days=3)
        start_dt = timezone.make_aware(datetime.combine(first_date, dt_time.min))
        end_dt = start_dt + timedelta(days=2) - timedelta(milliseconds=1)
        first_ts = int((start_dt + timedelta(hours=12)).timestamp() * 1000)
        second_ts = int((start_dt + timedelta(days=1, hours=12)).timestamp() * 1000)
        readings = [
            (self.dp_map["setpoint_pressao_alta"], 3, 10.0, first_ts),
            (self.dp_map["pressao_alta_prensas_1_7"], 3, 9.0, first_ts),
            (self.dp_map["volume_condensado"], 3, 100.0, first_ts),
            (self.dp_map["pressao_alta_prensas_1_7"], 3, 11.0, second_ts),
            (self.dp_map["volume_condensado"], 3, 150.0, second_ts),
        ]
        with connections["scada"].cursor() as cursor:
            cursor.executemany(
                "INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, %s, %s, %s)", readings
            )
        fast = CaldeiraFastReader.summary(start_dt, end_dt)
        original = CaldeiraHistoricalService.get_synchronized_history(start_dt, end_dt)
        self.assertEqual(fast["total_records"], len(original["timeline"]))
        self.assertEqual(fast["stats"]["variables"], original["stats"]["variables"])
        self.assertEqual(fast["stats"]["deviations"], original["stats"]["deviations"])
        self.assertEqual(fast["condensate_stats"]["total_liters"], 50.0)
        with patch.object(CaldeiraFastReader, "_segment_summary",
                          wraps=CaldeiraFastReader._segment_summary) as segment_query:
            CaldeiraFastReader.summary(start_dt, end_dt + timedelta(minutes=1))
        self.assertEqual(segment_query.call_count, 1)

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

    def test_vacuum_chart_keeps_weakest_reading_in_interval(self):
        start_dt = timezone.localtime().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        vacuum_id = self.dp_map["pressao_vacuo"]
        with connections["scada"].cursor() as cursor:
            cursor.executemany(
                "INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, %s, %s, %s)",
                [(vacuum_id, 3, value, int((start_dt + timedelta(minutes=minute)).timestamp() * 1000))
                 for minute, value in ((1, -0.55), (2, -0.20), (3, -0.54))],
            )
        chart = CaldeiraFastReader.summary(start_dt, start_dt + timedelta(minutes=5))["chart_datasets"]["chart_6_vacuo"]
        self.assertEqual(chart["vacuum_max"], [-0.2])
        self.assertEqual(chart["vacuum_avg"], [-0.43])

    def test_insights_counts_door_opening_pressure_drop_and_press_activity(self):
        start_dt = timezone.make_aware(datetime(2026, 11, 9, 6, 0))
        end_dt = start_dt + timedelta(hours=1)
        def reading(minute, point_id, value):
            return (point_id, 3, value, int((start_dt + timedelta(minutes=minute)).timestamp() * 1000), minute)
        records = sorted([
            reading(1, 3, 1), reading(5, 1, 15), reading(7, 4, 1),
            reading(8, 4, 0), reading(10, 1, 13.8), reading(13, 1, 13.7),
            reading(15, 1, 15), reading(30, 2, 1050), reading(31, 3, 0),
        ], key=lambda row: row[3])
        with patch.object(CaldeiraInsightsService, "_resolve", return_value=(
            {1: "pressure", 2: "condensate", 3: "press_01", 4: "door"}, [], True,
        )), patch.object(CaldeiraInsightsService, "_seeds", return_value={
            "pressure": None, "condensate": 1000, "press_01": False, "door": False,
        }), patch.object(CaldeiraFastReader, "_records", return_value=iter(records)):
            result = CaldeiraInsightsService.analyze(start_dt, end_dt)
        self.assertEqual(result["door_openings"], 1)
        self.assertEqual(result["drop_total"], 1)
        self.assertEqual(result["hours"][0]["cond_liters"], 50)
        self.assertEqual(result["hours"][0]["active_presses"], 0.5)
        self.assertEqual(result["shifts"][0]["drop_count"], 1)
        self.assertEqual(result["shifts"][0]["door_near_drops"], 1)
        self.assertEqual(result["shifts"][0]["pressure_samples"], 4)
        self.assertEqual(result["shifts"][0]["drop_pressure_min"], 13.7)
        self.assertEqual(result["drops"][0]["peak_pressure"], 15)
        self.assertEqual(result["drops"][0]["minimum_pressure"], 13.7)
        self.assertEqual(result["door_events"][0]["duration_seconds"], 60)
        self.assertEqual(result["shifts"][0]["door_long_average_minutes"], 1)
        workbook = openpyxl.load_workbook(build_insights_excel(result), read_only=True)
        self.assertEqual(workbook.sheetnames, ["Resumo", "Turnos", "Recuos", "Aberturas da Porta", "Horas"])
        self.assertEqual(list(workbook["Recuos"].values)[1][3], 13.7)
        self.assertEqual(list(workbook["Aberturas da Porta"].values)[1][2], 60)
        workbook.close()

    def test_performance_page_and_settings_permissions(self):
        self.client.force_login(self.user_lp)
        with patch("production.views.read_caldeira_insights_result", return_value=None), \
             patch("production.views.ensure_caldeira_insights_job") as start_job:
            response = self.client.get(reverse("production:caldeira_performance"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Organizando as leituras")
        self.assertContains(response, "Filtrar período")
        start_job.assert_called_once()
        self.assertNotContains(response, "O que aconteceu com a pressão?")
        save_url = reverse("production:caldeira_performance_settings")
        response = self.client.post(save_url, {"last_maintenance_date": "2026-11-01"})
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(CaldeiraAnalysisSettings.objects.exists())

        self.client.force_login(self.user_admin)
        response = self.client.post(save_url, {
            "last_maintenance_date": "2026-11-01",
            "last_inspection_date": "2026-01-01",
            "next_inspection_due": "2027-01-01",
            "operating_pressure_floor_bar": "14.5",
        })
        self.assertEqual(response.status_code, 302)
        settings = CaldeiraAnalysisSettings.objects.get(pk=1)
        self.assertEqual(str(settings.operating_pressure_floor_bar), "14.50")
        self.client.post(save_url, {"operating_pressure_floor_bar": "17.7"})
        self.assertEqual(CaldeiraAnalysisSettings.objects.get(pk=1).last_maintenance_date.isoformat(), "2026-11-01")

    def test_door_open_time_is_split_at_shift_change(self):
        start_dt = timezone.make_aware(datetime(2026, 11, 9, 17, 50))
        end_dt = start_dt + timedelta(minutes=20)
        def reading(minute, value):
            return (4, 3, value, int((start_dt + timedelta(minutes=minute)).timestamp() * 1000), minute)
        records = [reading(9, 1), reading(12, 0), reading(13, 1), reading(13.5, 0)]
        with patch.object(CaldeiraInsightsService, "_resolve", return_value=({4: "door"}, [], True)), \
             patch.object(CaldeiraInsightsService, "_seeds", return_value={"door": False}), \
             patch.object(CaldeiraFastReader, "_records", return_value=iter(records)):
            result = CaldeiraInsightsService.analyze(start_dt, end_dt)
        self.assertEqual(result["door_openings"], 2)
        self.assertEqual(result["door_open_minutes"], 3.5)
        self.assertEqual(result["shifts"][0]["door_open_minutes"], 1)
        self.assertEqual(result["shifts"][1]["door_open_minutes"], 2.5)
        self.assertEqual(result["shifts"][0]["door_long_average_minutes"], 3)
        self.assertEqual(result["shifts"][1]["door_quick_count"], 1)

    def test_ready_performance_page_and_excel_share_result(self):
        self.client.force_login(self.user_lp)
        start_dt = timezone.make_aware(datetime(2026, 11, 9, 6, 0))
        with patch.object(CaldeiraInsightsService, "_resolve", return_value=({}, [], False)), \
             patch.object(CaldeiraInsightsService, "_seeds", return_value={}), \
             patch.object(CaldeiraFastReader, "_records", return_value=iter(())):
            analysis = CaldeiraInsightsService.analyze(start_dt, start_dt + timedelta(hours=24))
        with patch("production.views.read_caldeira_insights_result", return_value=analysis), \
             patch("production.views.ensure_caldeira_insights_job") as start_job:
            response = self.client.get(reverse("production:caldeira_performance"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Comparação por turno horário")
            self.assertContains(response, "Exportar Excel")
            self.assertNotContains(response, "O que aconteceu com a pressão?")
            self.assertNotContains(response, "O que os dados sugerem sobre o condensado?")
            export = self.client.get(reverse("production:caldeira_performance_excel"))
            self.assertEqual(export.status_code, 200)
            self.assertIn(".xlsx", export["Content-Disposition"])
            book = openpyxl.load_workbook(io.BytesIO(b"".join(export.streaming_content)), read_only=True)
            self.assertEqual(book.sheetnames, ["Resumo", "Turnos", "Recuos", "Aberturas da Porta", "Horas"])
            book.close()
            start_job.assert_not_called()

    def test_custom_performance_period_survives_loading_and_export(self):
        self.client.force_login(self.user_lp)
        end_dt = timezone.localtime().replace(second=0, microsecond=0) - timedelta(hours=12)
        start_dt = end_dt - timedelta(hours=8)
        filters = {"janela": "personalizado", "inicio": start_dt.strftime("%Y-%m-%dT%H:%M"),
                   "fim": end_dt.strftime("%Y-%m-%dT%H:%M"), "queda_bar": "1.5", "duracao_min": "3"}
        with patch("production.views.read_caldeira_insights_result", return_value=None), \
             patch("production.views.ensure_caldeira_insights_job") as start_job:
            response = self.client.get(reverse("production:caldeira_performance"), filters)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Organizando as leituras")
            self.assertContains(response, 'id="loading-inicio"')
            self.assertContains(response, 'id="loading-fim"')
            self.assertContains(response, "janela=personalizado")
            self.assertContains(response, "inicio=")
            self.assertEqual(start_job.call_args.args[1:3], (start_dt, end_dt))
            export = self.client.get(reverse("production:caldeira_performance_excel"), filters)
            self.assertEqual(export.status_code, 302)
            self.assertIn("janela=personalizado", export["Location"])
            self.assertIn("inicio=", export["Location"])

        with patch.object(CaldeiraInsightsService, "_resolve", return_value=({}, [], False)), \
             patch.object(CaldeiraInsightsService, "_seeds", return_value={}), \
             patch.object(CaldeiraFastReader, "_records", return_value=iter(())):
            analysis = CaldeiraInsightsService.analyze(start_dt, end_dt, 1.5, 3)
        with patch("production.views.read_caldeira_insights_result", return_value=analysis):
            response = self.client.get(reverse("production:caldeira_performance"), filters)
            self.assertContains(response, 'name="inicio"')
            self.assertContains(response, 'name="fim"')
            self.assertContains(response, "Filtrar período")
            self.assertContains(response, "janela=personalizado")
            self.assertContains(response, "exportar-excel/")
            export = self.client.get(reverse("production:caldeira_performance_excel"), filters)
            self.assertEqual(export.status_code, 200)
            book = openpyxl.load_workbook(io.BytesIO(b"".join(export.streaming_content)), read_only=True)
            summary = list(book["Resumo"].values)
            self.assertEqual(summary[1][1], start_dt.strftime("%d/%m/%Y %H:%M"))
            self.assertEqual(summary[2][1], end_dt.strftime("%d/%m/%Y %H:%M"))
            book.close()

    def test_custom_performance_period_rejects_invalid_dates_and_long_ranges(self):
        self.client.force_login(self.user_lp)
        url = reverse("production:caldeira_performance")
        end_dt = timezone.localtime().replace(second=0, microsecond=0) - timedelta(hours=1)
        with patch("production.views.ensure_caldeira_insights_job") as start_job:
            for start, end in ((end_dt, end_dt - timedelta(hours=1)),
                               (end_dt - timedelta(days=32), end_dt),
                               (end_dt - timedelta(hours=1), end_dt + timedelta(days=1))):
                response = self.client.get(url, {"janela": "personalizado",
                    "inicio": start.strftime("%Y-%m-%dT%H:%M"),
                    "fim": end.strftime("%Y-%m-%dT%H:%M")})
                self.assertRedirects(response, url, fetch_redirect_response=False)
            start_job.assert_not_called()

    def test_insights_worker_persists_result(self):
        key = "a" * 64
        start_dt = timezone.make_aware(datetime(2026, 11, 9, 6, 0))
        with tempfile.TemporaryDirectory() as directory, patch.object(caldeira_insights_jobs, "JOB_DIR", Path(directory)):
            caldeira_insights_jobs.write_state(key, {
                "status": "queued", "start": start_dt.isoformat(),
                "end": (start_dt + timedelta(hours=1)).isoformat(),
                "drop_bar": 1.0, "min_minutes": 2, "floor": None,
            })
            with patch.object(CaldeiraInsightsService, "analyze", return_value={
                "start": start_dt, "end": start_dt + timedelta(hours=1), "drop_total": 2,
            }):
                call_command("build_caldeira_insights", job=key)
            self.assertEqual(caldeira_insights_jobs.read_state(key)["status"], "ready")
            self.assertEqual(caldeira_insights_jobs.read_result(key)["drop_total"], 2)

    def test_report_removes_setpoint_difference_chart(self):
        self.client.force_login(self.user_lp)
        response = self.client.get(reverse("production:caldeira_report"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Diferença das Linhas de Alta em Relação ao Setpoint")
        self.assertContains(response, "Pressão da Unidade de Vácuo")
        self.assertNotContains(response, "Nota de Interpretação")
        self.assertContains(response, "caldeira/desempenho/")
