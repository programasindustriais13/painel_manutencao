import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Group
from maintenance.models import Machine, Sector
from production.models import (
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    ProductionParameterConfig,
)
from production.xid_configuration import (
    XIDRegistry,
    XIDDiagnosticsService,
    XIDTestService,
)



class XIDAccessControlTestCase(TestCase):
    """
    Testa rigorosamente a matriz de controle de acesso para os 8 perfis de usuário.
    A Central de Configuração SCADA é estritamente restrita a superusuários.
    """

    def setUp(self):
        self.client = Client()
        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 01", setor=self.sector)
        self.mc = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            xid_status_prensa="DP_PR01_STATUS"
        )

        self.cav = ProductionCavityConfig.objects.create(
            machine_config=self.mc,
            nome="Cavidade 1",
            ordem=1,
            xid_producao="DP_PR01_C1_PROD"
        )

        # Criar os 8 perfis
        self.superuser = User.objects.create_superuser("admin_user", "admin@test.com", "pass123")
        self.staff_only = User.objects.create_user("staff_user", "staff@test.com", "pass123", is_staff=True)
        self.operador_user = User.objects.create_user("operador_user", "op@test.com", "pass123")
        self.lider_prod_user = User.objects.create_user("lider_prod", "lp@test.com", "pass123")
        self.pcp_user = User.objects.create_user("pcp_user", "pcp@test.com", "pass123")
        self.tecnico_user = User.objects.create_user("tecnico_user", "tec@test.com", "pass123")
        self.tecnico_lider_user = User.objects.create_user("tecnico_lider", "tl@test.com", "pass123")

        # Vincular grupos
        grp_op, _ = Group.objects.get_or_create(name="Operadores")
        grp_lp, _ = Group.objects.get_or_create(name="Liderança de Produção")
        grp_pcp, _ = Group.objects.get_or_create(name="PCP")
        grp_tec, _ = Group.objects.get_or_create(name="Técnicos")
        grp_tl, _ = Group.objects.get_or_create(name="Técnicos Líderes")

        self.operador_user.groups.add(grp_op)
        self.lider_prod_user.groups.add(grp_lp)
        self.pcp_user.groups.add(grp_pcp)
        self.tecnico_user.groups.add(grp_tec)
        self.tecnico_lider_user.groups.add(grp_tl)

        self.dashboard_url = reverse("production:xid_config_dashboard")
        self.machine_url = reverse("production:xid_machine_config", kwargs={"pk": self.machine.pk})
        self.global_url = reverse("production:xid_global_config")
        self.api_test_url = reverse("production:xid_test_api")

    def test_anonymous_user_redirected_to_login(self):
        """Usuário anônimo deve ser redirecionado para a tela de login."""
        for url in [self.dashboard_url, self.machine_url, self.global_url]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302)
            self.assertIn("/login/", res.url)

    def test_unauthorized_profiles_blocked_on_html_pages(self):
        """Perfis não-superuser recebem redirect para production:dashboard com erro."""
        unauthorized_users = [
            self.staff_only,
            self.operador_user,
            self.lider_prod_user,
            self.pcp_user,
            self.tecnico_user,
            self.tecnico_lider_user,
        ]

        for user in unauthorized_users:
            self.client.force_login(user)
            for url in [self.dashboard_url, self.machine_url, self.global_url]:
                res = self.client.get(url)
                self.assertEqual(res.status_code, 302, f"Usuário {user.username} não foi bloqueado em {url}")
                self.assertRedirects(res, reverse("production:dashboard"), fetch_redirect_response=False)


    def test_unauthorized_profiles_blocked_on_api_with_json_403(self):
        """Perfis não-superuser recebem HTTP 403 JSON no endpoint de teste de XID."""
        unauthorized_users = [
            self.staff_only,
            self.operador_user,
            self.lider_prod_user,
            self.pcp_user,
            self.tecnico_user,
            self.tecnico_lider_user,
        ]

        for user in unauthorized_users:
            self.client.force_login(user)
            res = self.client.post(
                self.api_test_url,
                data=json.dumps({"xid": "DP_TEST"}),
                content_type="application/json"
            )
            self.assertEqual(res.status_code, 403, f"Usuário {user.username} não recebeu 403 na API")
            data = res.json()
            self.assertFalse(data["success"])
            self.assertIn("Acesso negado", data["error"])

    def test_superuser_has_full_access_to_all_screens(self):
        """Superusuário tem acesso 200 OK a todas as telas da Central."""
        self.client.force_login(self.superuser)

        res_dash = self.client.get(self.dashboard_url)
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "Central de Configuração SCADA")
        self.assertContains(res_dash, "Prensa 01")

        res_mach = self.client.get(self.machine_url)
        self.assertEqual(res_mach.status_code, 200)
        self.assertContains(res_mach, "Configuração SCADA: Prensa 01")

        res_glob = self.client.get(self.global_url)
        self.assertEqual(res_glob.status_code, 200)
        self.assertContains(res_glob, "Parâmetros &amp; Alarmes Globais")


class XIDDiagnosticsServiceTestCase(TestCase):
    """
    Testa o motor de diagnóstico, cálculo de completude, filtros e detecção de duplicidades.
    """

    def setUp(self):
        self.sector = Sector.objects.create(nome="Vulcanização")
        # Prensa 01: parcialmente configurada
        self.m1 = Machine.objects.create(nome="Prensa 01", setor=self.sector)
        self.mc1 = ProductionMachineConfig.objects.create(
            machine=self.m1,
            ordem_exibicao=1,
            xid_status_prensa="DP_PR01_STATUS",
            xid_abertura="DP_PR01_ABERTURA"
        )
        self.c1_1 = ProductionCavityConfig.objects.create(
            machine_config=self.mc1,
            nome="Cavidade 1",
            ordem=1,
            xid_producao="DP_PR01_C1_PROD",
            xid_matriz="DP_SHARED_MATRIZ"  # XID compartilhado proposital
        )
        self.c1_2 = ProductionCavityConfig.objects.create(
            machine_config=self.mc1,
            nome="Cavidade 2",
            ordem=2,
            xid_producao="DP_PR01_C2_PROD"
        )

        # Prensa 02: sem configuração SCADA ainda
        self.m2 = Machine.objects.create(nome="Prensa 02", setor=self.sector)

        # Variável global com XID compartilhado
        self.gp = ProductionGlobalParameter.objects.create(
            nome="Pressão Vácuo",
            chave="pressao_vacuo",
            xid="DP_SHARED_MATRIZ",  # Duplicidade proposital
            ordem=1
        )

    def test_diagnostics_overview_counts(self):
        """Valida os totais calculados pelo serviço de diagnóstico."""
        overview = XIDDiagnosticsService.get_diagnostics_overview()

        self.assertEqual(overview["total_machines"], 2)
        self.assertGreater(overview["total_expected_xids"], 0)
        self.assertGreater(overview["total_filled_xids"], 0)
        self.assertEqual(overview["total_missing_xids"], overview["total_expected_xids"] - overview["total_filled_xids"])

        # Duplicidade detectada
        self.assertIn("DP_SHARED_MATRIZ", overview["duplicates_map"])
        self.assertGreaterEqual(overview["duplicates_count"], 1)

    def test_diagnostics_search_filter(self):
        """Valida busca por nome de máquina ou setor."""
        res_m1 = XIDDiagnosticsService.get_diagnostics_overview(search_query="Prensa 01")
        self.assertEqual(len(res_m1["machines"]), 1)
        self.assertEqual(res_m1["machines"][0]["machine_name"], "Prensa 01")

        res_vulc = XIDDiagnosticsService.get_diagnostics_overview(search_query="Vulcanização")
        self.assertEqual(len(res_vulc["machines"]), 2)

    def test_diagnostics_status_filter(self):
        """Valida filtro por incompletas ou alertas."""
        res_incomp = XIDDiagnosticsService.get_diagnostics_overview(status_filter="incomplete")
        self.assertEqual(len(res_incomp["machines"]), 2)

        res_issues = XIDDiagnosticsService.get_diagnostics_overview(status_filter="issues")
        self.assertEqual(len(res_issues["machines"]), 2)


class XIDMachineConfigViewTestCase(TestCase):
    """
    Testa o fluxo de edição de prensas, atomicidade, formsets e criação sob demanda.
    """

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser("admin_xid", "adm@test.com", "pass123")
        self.client.force_login(self.superuser)

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.m1 = Machine.objects.create(nome="Prensa 01", setor=self.sector)
        self.m2 = Machine.objects.create(nome="Prensa 02", setor=self.sector)


        self.mc1 = ProductionMachineConfig.objects.create(
            machine=self.m1,
            ordem_exibicao=1,
            stale_limit_seconds=120,
            produzindo_value="1",
            xid_status_prensa="DP_PR01_STATUS"
        )
        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.mc1,
            nome="Cavidade 1",
            ordem=1,
            xid_producao="DP_PR01_C1_PROD"
        )
        self.cav2 = ProductionCavityConfig.objects.create(
            machine_config=self.mc1,
            nome="Cavidade 2",
            ordem=2,
            xid_producao="DP_PR01_C2_PROD"
        )

    def test_get_machine_config_screen(self):
        """Carregamento da tela de configuração para máquina existente e nova."""
        url_m1 = reverse("production:xid_machine_config", kwargs={"pk": self.m1.pk})
        res_m1 = self.client.get(url_m1)
        self.assertEqual(res_m1.status_code, 200)
        self.assertContains(res_m1, "DP_PR01_STATUS")
        self.assertContains(res_m1, "Cavidade 1")

        # Máquina 2 (sem config prévia)
        url_m2 = reverse("production:xid_machine_config", kwargs={"pk": self.m2.pk})
        res_m2 = self.client.get(url_m2)
        self.assertEqual(res_m2.status_code, 200)
        self.assertContains(res_m2, "Configuração Inicial")

    def test_post_valid_machine_and_cavities_update(self):
        """Salva com sucesso máquina e múltiplas cavidades, aplicando .strip() nos XIDs."""
        url_m1 = reverse("production:xid_machine_config", kwargs={"pk": self.m1.pk})

        post_data = {
            "ordem_exibicao": "2",
            "stale_limit_seconds": "90",
            "produzindo_value": "1",
            "xid_status_prensa": "  DP_PR01_STATUS_NEW  ",
            "xid_abertura": "DP_PR01_ABERTURA",
            "xid_motivo_parada_geral": "DP_PR01_MOTIVO",
            # Formset management
            "cavities-TOTAL_FORMS": "2",
            "cavities-INITIAL_FORMS": "2",
            "cavities-MIN_NUM_FORMS": "0",
            "cavities-MAX_NUM_FORMS": "1000",
            # Cavidade 1
            "cavities-0-id": str(self.cav1.id),
            "cavities-0-nome": "Cavidade 1",
            "cavities-0-ordem": "1",
            "cavities-0-xid_producao": "  DP_PR01_C1_PROD_NEW  ",
            "cavities-0-xid_matriz": "DP_PR01_C1_MATRIZ",
            "cavities-0-xid_produto": "6154",
            "cavities-0-xid_lote_bladder": "161046",
            "cavities-0-xid_bla_real": "BLA003",
            "cavities-0-xid_meta": "500",
            "cavities-0-xid_motivo_parada": "0",
            "cavities-0-xid_motivo_troca_bladder": "0",
            # Cavidade 2
            "cavities-1-id": str(self.cav2.id),
            "cavities-1-nome": "Cavidade 2",
            "cavities-1-ordem": "2",
            "cavities-1-xid_producao": "DP_PR01_C2_PROD_NEW",
            "cavities-1-xid_matriz": "DP_PR01_C2_MATRIZ",
            "cavities-1-xid_produto": "6154",
            "cavities-1-xid_lote_bladder": "161047",
            "cavities-1-xid_bla_real": "BLA004",
            "cavities-1-xid_meta": "500",
            "cavities-1-xid_motivo_parada": "0",
            "cavities-1-xid_motivo_troca_bladder": "0",
            "action": "save",
        }

        res = self.client.post(url_m1, post_data)
        self.assertEqual(res.status_code, 302)

        self.mc1.refresh_from_db()
        self.cav1.refresh_from_db()
        self.cav2.refresh_from_db()

        self.assertEqual(self.mc1.stale_limit_seconds, 90)
        self.assertEqual(self.mc1.xid_status_prensa, "DP_PR01_STATUS_NEW")
        self.assertEqual(self.cav1.xid_producao, "DP_PR01_C1_PROD_NEW")
        self.assertEqual(self.cav1.xid_bla_real, "BLA003")
        self.assertEqual(self.cav2.xid_producao, "DP_PR01_C2_PROD_NEW")

    def test_atomic_rollback_on_cavity_error(self):
        """Se uma cavidade for inválida (ex: ordem duplicada), nenhuma alteração é persistida."""
        url_m1 = reverse("production:xid_machine_config", kwargs={"pk": self.m1.pk})

        post_data = {
            "ordem_exibicao": "99",
            "stale_limit_seconds": "999",
            "produzindo_value": "1",
            "xid_status_prensa": "DP_SHOULD_ROLLBACK",
            # Formset com ordem duplicada
            "cavities-TOTAL_FORMS": "2",
            "cavities-INITIAL_FORMS": "2",
            "cavities-MIN_NUM_FORMS": "0",
            "cavities-MAX_NUM_FORMS": "1000",
            "cavities-0-id": str(self.cav1.id),
            "cavities-0-nome": "Cavidade 1",
            "cavities-0-ordem": "1",
            "cavities-1-id": str(self.cav2.id),
            "cavities-1-nome": "Cavidade 2",
            "cavities-1-ordem": "1",  # DUPLICADA (1 e 1)
            "action": "save",
        }

        res = self.client.post(url_m1, post_data)
        self.assertEqual(res.status_code, 200)  # Re-renderiza com erro

        self.mc1.refresh_from_db()
        self.assertNotEqual(self.mc1.xid_status_prensa, "DP_SHOULD_ROLLBACK")
        self.assertNotEqual(self.mc1.stale_limit_seconds, 999)


class XIDGlobalConfigViewTestCase(TestCase):
    """
    Testa o cadastro e edição de Parâmetros Globais e Alarmes Globais.
    """

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser("admin_glob", "glob@test.com", "pass123")
        self.client.force_login(self.superuser)
        self.url = reverse("production:xid_global_config")

    def test_create_and_edit_global_parameter(self):
        """Cria e edita um parâmetro global via POST action=save_param."""
        # Criação
        res_create = self.client.post(self.url, {
            "action": "save_param",
            "param_id": "",
            "nome": "Pressão de Vapor Lado 1",
            "chave": "vapor_lado_1",
            "xid": "DP_VAPOR_L1",
            "unidade": "bar",
            "ordem": "1",
        })
        self.assertEqual(res_create.status_code, 302)

        param = ProductionGlobalParameter.objects.get(chave="vapor_lado_1")
        self.assertEqual(param.nome, "Pressão de Vapor Lado 1")
        self.assertEqual(param.xid, "DP_VAPOR_L1")

        # Edição
        res_edit = self.client.post(self.url, {
            "action": "save_param",
            "param_id": str(param.pk),
            "nome": "Pressão de Vapor Lado 1 (Novo)",
            "chave": "vapor_lado_1",
            "xid": "DP_VAPOR_L1_NEW",
            "unidade": "bar",
            "ordem": "2",
        })
        self.assertEqual(res_edit.status_code, 302)
        param.refresh_from_db()
        self.assertEqual(param.nome, "Pressão de Vapor Lado 1 (Novo)")
        self.assertEqual(param.xid, "DP_VAPOR_L1_NEW")

    def test_create_and_edit_global_alarm(self):
        """Cria e edita um alarme global via POST action=save_alarm."""
        res_create = self.client.post(self.url, {
            "action": "save_alarm",
            "alarm_id": "",
            "nome": "Alarme Falha de Ar",
            "chave": "alarme_ar",
            "xid": "DP_ALARME_AR",
            "ordem": "1",
        })
        self.assertEqual(res_create.status_code, 302)

        alarm = ProductionGlobalAlarm.objects.get(chave="alarme_ar")
        self.assertEqual(alarm.nome, "Alarme Falha de Ar")
        self.assertEqual(alarm.xid, "DP_ALARME_AR")

    def test_global_parameter_list_excludes_calandra_parameters(self):
        """Garante que a lista de parâmetros globais exclua variáveis da Calandra."""
        ProductionGlobalParameter.objects.create(
            nome="Pressão de Ar Pneumático",
            chave="pressao_ar",
            xid="DP_AR",
            ordem=1
        )
        ProductionGlobalParameter.objects.create(
            nome="Calandra - Passada",
            chave="calandra_passada",
            xid="DP_CAL_PASSADA",
            ordem=2
        )
        ProductionGlobalParameter.objects.create(
            nome="Calandra - Furador",
            chave="calandra_furador",
            xid="DP_CAL_FURADOR",
            ordem=3
        )

        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        params = res.context["global_params"]
        param_keys = [p.chave for p in params]
        self.assertIn("pressao_ar", param_keys)
        self.assertNotIn("calandra_passada", param_keys)
        self.assertNotIn("calandra_furador", param_keys)


class XIDTestAPITestCase(TestCase):
    """
    Testa o endpoint assíncrono de teste de XID com mocks de ScadaReaderService.
    Garante resiliência e que nenhuma escrita no banco ocorra.
    """

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser("admin_api", "api@test.com", "pass123")
        self.client.force_login(self.superuser)
        self.url = reverse("production:xid_test_api")

    def test_empty_xid_returns_friendly_message(self):
        """Testa XID vazio ou em branco."""
        res = self.client.post(self.url, {"xid": "   "})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "EMPTY")

    @patch("production.xid_configuration.scada_reader.get_data_point_ids")
    def test_xid_not_found(self, mock_get_dp_ids):
        """Testa quando o XID não existe no Scada-LTS."""
        mock_get_dp_ids.return_value = {}  # Não localizado

        res = self.client.post(self.url, {"xid": "DP_INEXISTENTE"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "NOT_FOUND")
        self.assertIn("não foi localizado", data["message"])

    @patch("production.xid_configuration.scada_reader.get_last_values_batch")
    @patch("production.xid_configuration.scada_reader.get_data_point_ids")
    def test_xid_found_multistate(self, mock_get_dp_ids, mock_get_values):
        """Testa XID existente com valor multistate."""
        mock_get_dp_ids.return_value = {"DP_STATUS_P1": 101}
        mock_get_values.return_value = {
            "DP_STATUS_P1": {
                "xid": "DP_STATUS_P1",
                "data_point_id": 101,
                "data_type": 2,
                "value": 1,
                "str_value": "1",
                "ts": 1724240000000,
            }
        }

        res = self.client.post(
            self.url,
            data=json.dumps({"xid": "DP_STATUS_P1"}),
            content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "OK")
        self.assertEqual(data["data_point_id"], 101)
        self.assertEqual(data["str_value"], "1")

    @patch("production.xid_configuration.scada_reader.get_data_point_ids")
    def test_scada_offline_graceful_handling(self, mock_get_dp_ids):
        """Simula falha de banco/timeout no Scada sem lançar erro 500."""
        mock_get_dp_ids.side_effect = Exception("Conexão recusada com MySQL Scada")

        res = self.client.post(self.url, {"xid": "DP_TEST"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "SCADA_OFFLINE")
        self.assertIn("Não foi possível consultar o Scada-LTS", data["message"])



class XIDInventoryExhaustivenessTestCase(TestCase):
    """
    Metateste automatizado: garante que 100% dos campos xid_* ou xid existentes nos models
    de configuração do app production estejam catalogados no XIDRegistry da Central.
    """

    def test_all_xid_fields_are_registered_in_central(self):
        models_to_check = [
            ProductionMachineConfig,
            ProductionCavityConfig,
            ProductionGlobalParameter,
            ProductionGlobalAlarm,
            ProductionParameterConfig,
        ]

        registered_map = XIDRegistry.get_registered_fields_by_model()

        for model in models_to_check:
            model_name = model.__name__
            self.assertIn(model_name, registered_map, f"Modelo {model_name} não cadastrado no XIDRegistry.")
            registered_fields = set(registered_map[model_name])

            # Descobrir via introspecção do ORM todos os campos que representam XID
            model_xid_fields = {
                field.name for field in model._meta.fields
                if field.name.startswith("xid_") or field.name == "xid"
            }

            missing_in_registry = model_xid_fields - registered_fields
            self.assertEqual(
                missing_in_registry,
                set(),
                f"O modelo {model_name} possui campos de XID {missing_in_registry} que NÃO foram registrados no XIDRegistry da Central!"
            )
