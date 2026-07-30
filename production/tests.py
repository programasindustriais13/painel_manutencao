from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from maintenance.models import Sector, Machine
from production.models import (
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
)
from production.routers import ScadaRouter


class ProductionIntegrationTestCase(TestCase):
    def setUp(self):
        # Create standard groups
        self.prod_leader_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.operator_group, _ = Group.objects.get_or_create(name="Operadores")
        self.tech_group, _ = Group.objects.get_or_create(name="Tecnicos")
        self.viewer_group, _ = Group.objects.get_or_create(name="Visualizador")
        
        # Create users
        self.prod_user = User.objects.create_user("prod_lider", "prod@test.com", "pwd123")
        self.prod_user.groups.add(self.prod_leader_group)
        
        self.maintenance_operator = User.objects.create_user("maint_op", "maint@test.com", "pwd123")
        self.maintenance_operator.groups.add(self.operator_group)
        
        self.maintenance_tech = User.objects.create_user("maint_tech", "tech@test.com", "pwd123")
        self.maintenance_tech.groups.add(self.tech_group)

        self.admin_user = User.objects.create_superuser("admin_user", "admin@test.com", "pwd123")

    def test_login_redirect_for_production_leader(self):
        """Test that users in 'Liderança de Produção' group are redirected to '/producao/'."""
        client = Client()
        client.force_login(self.prod_user)
        response = client.get(reverse("home_redirect"))
        self.assertRedirects(response, reverse("production:dashboard"))

    def test_login_redirect_for_maintenance_users(self):
        """Test that maintenance users are redirected to their respective endpoints."""
        client = Client()
        
        # Operator -> dashboard
        client.force_login(self.maintenance_operator)
        response = client.get(reverse("home_redirect"))
        self.assertRedirects(response, reverse("dashboard"))
        client.logout()
        
        # Technician -> technician_management
        client.force_login(self.maintenance_tech)
        response = client.get(reverse("home_redirect"))
        self.assertRedirects(response, reverse("technician_management"))

    def test_production_leader_blocked_from_maintenance(self):
        """Test that production leaders cannot access maintenance pages."""
        client = Client()
        client.force_login(self.prod_user)
        
        # Try to access technician_management
        response = client.get(reverse("technician_management"))
        self.assertRedirects(response, reverse("production:dashboard"))
        
        # Try to access dashboard
        response = client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("production:dashboard"))

        # Try to access crud_list
        response = client.get(reverse("crud_list"))
        self.assertRedirects(response, reverse("production:dashboard"))

    def test_maintenance_blocked_from_production(self):
        """Test that maintenance users cannot access production dashboard."""
        client = Client()
        
        # Operator tries to access production
        client.force_login(self.maintenance_operator)
        response = client.get(reverse("production:dashboard"))
        self.assertRedirects(response, reverse("home_redirect"), target_status_code=302)
        client.logout()

        # Technician tries to access production
        client.force_login(self.maintenance_tech)
        response = client.get(reverse("production:dashboard"))
        self.assertRedirects(response, reverse("home_redirect"), target_status_code=302)
        client.logout()

    def test_admin_can_access_production(self):
        """Test that a superuser can access the production dashboard."""
        client = Client()
        client.force_login(self.admin_user)
        response = client.get(reverse("production:dashboard"))
        self.assertEqual(response.status_code, 200)


class ProductionConfigModelsTestCase(TestCase):
    def setUp(self):
        self.sector = Sector.objects.create(nome="Injeção")
        self.machine1 = Machine.objects.create(nome="Prensa 01", setor=self.sector, criticidade="ALTA")
        self.machine2 = Machine.objects.create(nome="Prensa 02", setor=self.sector, criticidade="MEDIA")

    def test_production_machine_config_and_cavities_creation(self):
        """Test creating ProductionMachineConfig and associated cavities."""
        config = ProductionMachineConfig.objects.create(
            machine=self.machine1,
            ordem_exibicao=1,
            stale_limit_seconds=180,
            produzindo_value="1",
            xid_status_prensa="DP_PRENSA_01_STATUS",
            xid_abertura="DP_PRENSA_01_ABERTURA",
            xid_motivo_parada_geral="DP_PRENSA_01_MOTIVO",
        )
        self.assertEqual(str(config), "Config. Produção: Prensa 01")

        cav1 = ProductionCavityConfig.objects.create(
            machine_config=config,
            nome="Cavidade A",
            ordem=1,
            xid_producao="DP_CAV_A_PROD",
            xid_meta="DP_CAV_A_META",
            xid_motivo_parada="DP_CAV_A_MOTIVO",
        )
        cav2 = ProductionCavityConfig.objects.create(
            machine_config=config,
            nome="Cavidade B",
            ordem=2,
            xid_producao="DP_CAV_B_PROD",
            xid_meta="DP_CAV_B_META",
        )
        self.assertEqual(config.cavities.count(), 2)
        self.assertEqual(str(cav1), "Prensa 01 - Cavidade A")
        self.assertEqual(str(cav2), "Prensa 01 - Cavidade B")

    def test_cavity_unique_constraint_same_name_same_machine(self):
        """Test that cavity names must be unique within the same machine config."""
        config = ProductionMachineConfig.objects.create(machine=self.machine1)
        ProductionCavityConfig.objects.create(machine_config=config, nome="Cavidade 1", ordem=1)
        with self.assertRaises(IntegrityError):
            ProductionCavityConfig.objects.create(machine_config=config, nome="Cavidade 1", ordem=2)

    def test_cavity_unique_constraint_same_order_same_machine(self):
        """Test that cavity order must be unique within the same machine config."""
        config = ProductionMachineConfig.objects.create(machine=self.machine1)
        ProductionCavityConfig.objects.create(machine_config=config, nome="Cavidade A", ordem=1)
        with self.assertRaises(IntegrityError):
            ProductionCavityConfig.objects.create(machine_config=config, nome="Cavidade B", ordem=1)

    def test_cavity_same_name_and_order_different_machines_allowed(self):
        """Test that same cavity name and order are allowed across different machines."""
        config1 = ProductionMachineConfig.objects.create(machine=self.machine1)
        config2 = ProductionMachineConfig.objects.create(machine=self.machine2)
        
        cav1 = ProductionCavityConfig.objects.create(machine_config=config1, nome="Cavidade 1", ordem=1)
        cav2 = ProductionCavityConfig.objects.create(machine_config=config2, nome="Cavidade 1", ordem=1)
        
        self.assertIsNotNone(cav1.pk)
        self.assertIsNotNone(cav2.pk)

    def test_stale_limit_seconds_validation_and_constraint(self):
        """Test that stale_limit_seconds requires values >= 1."""
        config = ProductionMachineConfig(machine=self.machine1, stale_limit_seconds=0)
        with self.assertRaises(ValidationError):
            config.full_clean()

        with self.assertRaises(IntegrityError):
            ProductionMachineConfig.objects.create(machine=self.machine1, stale_limit_seconds=0)

    def test_production_global_parameter_and_alarm(self):
        """Test creating global parameters and alarms."""
        param = ProductionGlobalParameter.objects.create(
            nome="Pressão de Vácuo",
            chave="pressao_vacuo",
            xid="DP_VACUO_PRESSAO",
            unidade="mmHg",
            ordem=1,
        )
        self.assertEqual(str(param), "Pressão de Vácuo (pressao_vacuo)")

        alarm = ProductionGlobalAlarm.objects.create(
            nome="Alarme Falha de Ar",
            chave="alarme_ar",
            xid="DP_ALARME_AR",
            ordem=1,
        )
        self.assertEqual(str(alarm), "Alarme Falha de Ar (alarme_ar)")


class ScadaRouterDetailedTestCase(TestCase):
    def setUp(self):
        self.router = ScadaRouter()

        class UnmanagedScadaModel:
            class _meta:
                app_label = "production"
                model_name = "scadadatapoint"
                managed = False
                label = "production.ScadaDataPoint"

        self.UnmanagedModel = UnmanagedScadaModel

    def test_read_local_model_in_default(self):
        """db_for_read for managed local models returns 'default'."""
        self.assertEqual(self.router.db_for_read(ProductionMachineConfig), "default")
        self.assertEqual(self.router.db_for_read(ProductionCavityConfig), "default")
        self.assertEqual(self.router.db_for_read(ProductionGlobalParameter), "default")
        self.assertEqual(self.router.db_for_read(ProductionGlobalAlarm), "default")

    def test_write_local_model_in_default(self):
        """db_for_write for managed local models returns 'default'."""
        self.assertEqual(self.router.db_for_write(ProductionMachineConfig), "default")
        self.assertEqual(self.router.db_for_write(ProductionCavityConfig), "default")
        self.assertEqual(self.router.db_for_write(ProductionGlobalParameter), "default")
        self.assertEqual(self.router.db_for_write(ProductionGlobalAlarm), "default")

    def test_read_unmanaged_model_in_scada(self):
        """db_for_read for unmanaged models returns 'scada'."""
        self.assertEqual(self.router.db_for_read(self.UnmanagedModel), "scada")

    def test_write_unmanaged_model_blocked(self):
        """db_for_write for unmanaged models raises PermissionError."""
        with self.assertRaises(PermissionError):
            self.router.db_for_write(self.UnmanagedModel)

    def test_allow_migrate_local_model(self):
        """allow_migrate for local managed models returns True on default and False on scada."""
        self.assertTrue(
            self.router.allow_migrate("default", "production", "productionmachineconfig", model=ProductionMachineConfig)
        )
        self.assertFalse(
            self.router.allow_migrate("scada", "production", "productionmachineconfig", model=ProductionMachineConfig)
        )

    def test_allow_migrate_unmanaged_model(self):
        """allow_migrate for unmanaged models returns False on all databases."""
        self.assertFalse(
            self.router.allow_migrate("default", "production", "scadadatapoint", model=self.UnmanagedModel)
        )
        self.assertFalse(
            self.router.allow_migrate("scada", "production", "scadadatapoint", model=self.UnmanagedModel)
        )

    def test_allow_migrate_scada_db_always_false(self):
        """allow_migrate for scada db always returns False regardless of app or model."""
        self.assertFalse(self.router.allow_migrate("scada", "maintenance", "machine"))
        self.assertFalse(self.router.allow_migrate("scada", "auth", "user"))
        self.assertFalse(self.router.allow_migrate("scada", "production", "productionmachineconfig"))

    def test_allow_migrate_without_hints(self):
        """allow_migrate works deterministically when hints are omitted."""
        self.assertTrue(self.router.allow_migrate("default", "production", "productioncavityconfig"))
        self.assertFalse(self.router.allow_migrate("default", "production", "unknownmodel"))

    def test_allow_migrate_historical_or_dummy_model_in_hints(self):
        """allow_migrate works correctly when model object is passed via hints."""
        self.assertTrue(
            self.router.allow_migrate("default", "production", hints={"model": ProductionGlobalParameter})
        )
        self.assertFalse(
            self.router.allow_migrate("default", "production", hints={"model": self.UnmanagedModel})
        )

    def test_unknown_model_name_of_production_app(self):
        """Unknown model names under production app return False for migration on default."""
        self.assertFalse(self.router.allow_migrate("default", "production", "unknown_prod_model"))

    def test_other_apps_unaffected_by_router(self):
        """Apps other than production return None for db_for_read, db_for_write and allow_migrate."""
        class MaintenanceModel:
            class _meta:
                app_label = "maintenance"
                model_name = "machine"
                managed = True

        self.assertIsNone(self.router.db_for_read(MaintenanceModel))
        self.assertIsNone(self.router.db_for_write(MaintenanceModel))
        self.assertIsNone(self.router.allow_migrate("default", "maintenance", "machine"))

    def test_allow_relation_machine_and_production_config(self):
        """allow_relation permits relation between Machine and ProductionMachineConfig."""
        class MachineDummy:
            class _meta:
                app_label = "maintenance"
                model_name = "machine"
                managed = True

        self.assertTrue(self.router.allow_relation(MachineDummy, ProductionMachineConfig))
        self.assertTrue(self.router.allow_relation(ProductionMachineConfig, MachineDummy))

    def test_allow_relation_unmanaged_scada_model_blocked(self):
        """allow_relation blocks relations involving unmanaged Scada models."""
        self.assertFalse(self.router.allow_relation(ProductionMachineConfig, self.UnmanagedModel))


# ==============================================================================
# TESTES DA SPEC 04 — LEITURA SCADA, NORMALIZAÇÃO, ESTADO E DASHBOARD
# ==============================================================================

from django.db import connections
import time
from production.models import ScadaDataPoint, ScadaPointValue, ScadaPointValueAnnotation
from production.services import scada_reader, ScadaReaderService, ProductionStateService


def init_scada_test_tables():
    """Cria fisicamente as tabelas do Scada no banco de testes 'scada' (SQLite)."""
    with connections["scada"].cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datapoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                xid VARCHAR(50) UNIQUE NOT NULL,
                dataSourceId INTEGER NOT NULL,
                pointName VARCHAR(250),
                plcAlarmLevel INTEGER
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pointvalues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataPointId INTEGER NOT NULL,
                dataType INTEGER NOT NULL,
                pointValue DOUBLE,
                ts BIGINT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pointvalueannotations (
                pointValueId INTEGER PRIMARY KEY,
                textPointValueShort VARCHAR(128),
                textPointValueLong TEXT
            );
        """)


class ScadaUnmanagedModelsTestCase(TestCase):
    def setUp(self):
        self.router = ScadaRouter()

    def test_unmanaged_scada_models_routed_to_scada_for_read(self):
        """Modelos não gerenciados do Scada são lidos exclusivamente no banco 'scada'."""
        self.assertEqual(self.router.db_for_read(ScadaDataPoint), "scada")
        self.assertEqual(self.router.db_for_read(ScadaPointValue), "scada")
        self.assertEqual(self.router.db_for_read(ScadaPointValueAnnotation), "scada")

    def test_unmanaged_scada_models_blocked_for_write(self):
        """Escrita via ORM em modelos não gerenciados dispara PermissionError."""
        with self.assertRaises(PermissionError):
            self.router.db_for_write(ScadaDataPoint)
        with self.assertRaises(PermissionError):
            self.router.db_for_write(ScadaPointValue)
        with self.assertRaises(PermissionError):
            self.router.db_for_write(ScadaPointValueAnnotation)

    def test_unmanaged_scada_models_blocked_for_migrate(self):
        """Migrações para modelos não gerenciados do Scada são categoricamente bloqueadas."""
        self.assertFalse(self.router.allow_migrate("default", "production", "scadadatapoint"))
        self.assertFalse(self.router.allow_migrate("scada", "production", "scadadatapoint"))


class ScadaReaderServiceTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        scada_reader.clear_caches()
        
        # Inserir dados de teste na base scada via SQL bruto
        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalueannotations;")
            cursor.execute("DELETE FROM pointvalues;")
            cursor.execute("DELETE FROM datapoints;")

            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId, pointName) VALUES (1, 'DP_STATUS_P1', 10, 'Status P1');")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId, pointName) VALUES (2, 'DP_PROD_CAV1', 10, 'Prod Cav 1');")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId, pointName) VALUES (3, 'DP_MOTIVO_P1', 10, 'Motivo P1');")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId, pointName) VALUES (4, 'DP_VACUO', 10, 'Vácuo');")

            now_ms = int(time.time() * 1000)
            old_ms = now_ms - (300 * 1000)  # 5 minutos atrás

            # Status P1 (Binary dataType=1)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (101, 1, 1, 1.0, ?);", [now_ms])
            # Prod Cav 1 (Numeric dataType=3)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (102, 2, 3, 150.0, ?);", [now_ms])
            # Motivo P1 (String dataType=4)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (103, 3, 4, NULL, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalueannotations (pointValueId, textPointValueShort) VALUES (103, 'Troca de Molde');")
            # Vácuo (Numeric desatualizado)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (104, 4, 3, 750.5, ?);", [old_ms])

    def test_get_data_point_ids_batch_and_cache(self):
        """Testa resolução em lote de XIDs e cache em memória."""
        ids = scada_reader.get_data_point_ids(["DP_STATUS_P1", "DP_PROD_CAV1", "XID_INEXISTENTE"])
        self.assertEqual(ids.get("DP_STATUS_P1"), 1)
        self.assertEqual(ids.get("DP_PROD_CAV1"), 2)
        self.assertNotIn("XID_INEXISTENTE", ids)

        # Segunda busca deve vir do cache
        ids_cached = scada_reader.get_data_point_ids(["DP_STATUS_P1"])
        self.assertEqual(ids_cached.get("DP_STATUS_P1"), 1)

    def test_normalize_value_types(self):
        """Testa normalização dos 4 tipos nativos do Scada-LTS."""
        # 1: Binary
        val, s_val = scada_reader.normalize_value(1, 1.0)
        self.assertTrue(val)
        self.assertEqual(s_val, "1")

        val, s_val = scada_reader.normalize_value(1, 0.0)
        self.assertFalse(val)
        self.assertEqual(s_val, "0")

        # 2: Multistate
        val, s_val = scada_reader.normalize_value(2, 3.0)
        self.assertEqual(val, 3)
        self.assertEqual(s_val, "3")

        # 3: Numeric
        val, s_val = scada_reader.normalize_value(3, 45.5)
        self.assertEqual(val, 45.5)
        self.assertEqual(s_val, "45.50")

        # 4: String
        class AnnDummy:
            text_point_value_short = "Alarme Ativo"
            text_point_value_long = None

        val, s_val = scada_reader.normalize_value(4, None, AnnDummy())
        self.assertEqual(val, "Alarme Ativo")
        self.assertEqual(s_val, "Alarme Ativo")

    def test_get_last_values_batch_max_ts(self):
        """Testa consulta dos últimos valores em lote via subquery MAX(ts)."""
        res = scada_reader.get_last_values_batch(["DP_STATUS_P1", "DP_PROD_CAV1", "DP_MOTIVO_P1"])
        self.assertIn("DP_STATUS_P1", res)
        self.assertEqual(res["DP_STATUS_P1"]["value"], True)

        self.assertIn("DP_PROD_CAV1", res)
        self.assertEqual(res["DP_PROD_CAV1"]["value"], 150)

        self.assertIn("DP_MOTIVO_P1", res)
        self.assertEqual(res["DP_MOTIVO_P1"]["value"], "Troca de Molde")


class ProductionStateServiceTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        scada_reader.clear_caches()

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine1 = Machine.objects.create(nome="Prensa 01", setor=self.sector)
        self.machine2 = Machine.objects.create(nome="Prensa 02", setor=self.sector)

        self.config1 = ProductionMachineConfig.objects.create(
            machine=self.machine1,
            ordem_exibicao=1,
            stale_limit_seconds=120,
            produzindo_value="1",
            xid_status_prensa="DP_STATUS_P1",
            xid_motivo_parada_geral="DP_MOTIVO_P1"
        )
        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 1",
            ordem=1,
            xid_producao="DP_PROD_CAV1",
            xid_meta="DP_META_CAV1"
        )

        self.config2 = ProductionMachineConfig.objects.create(
            machine=self.machine2,
            ordem_exibicao=2,
            stale_limit_seconds=60,
            produzindo_value="1",
            xid_status_prensa="DP_STATUS_P2"
        )

        self.param_vacuo = ProductionGlobalParameter.objects.create(
            nome="Vácuo Geral",
            chave="vacuo_geral",
            xid="DP_VACUO",
            unidade="mmHg",
            ordem=1
        )
        self.alarm_ar = ProductionGlobalAlarm.objects.create(
            nome="Alarme Ar",
            chave="alarme_ar",
            xid="DP_ALARME_AR",
            ordem=1
        )

        now_ms = int(time.time() * 1000)
        old_ms = now_ms - (300 * 1000)  # 5 min atrás (desatualizado para P2)

        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalueannotations;")
            cursor.execute("DELETE FROM pointvalues;")
            cursor.execute("DELETE FROM datapoints;")

            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (1, 'DP_STATUS_P1', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (2, 'DP_PROD_CAV1', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (3, 'DP_META_CAV1', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (4, 'DP_STATUS_P2', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (5, 'DP_VACUO', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (6, 'DP_ALARME_AR', 1);")

            # P1 Produzindo
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (1, 1, 1, 1.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (2, 2, 3, 80.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (3, 3, 3, 100.0, ?);", [now_ms])

            # P2 Parada e Dado desatualizado
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (4, 4, 1, 0.0, ?);", [old_ms])

            # Vácuo
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (5, 5, 3, 760.0, ?);", [now_ms])

            # Alarme Ar (Desativado)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (6, 6, 1, 0.0, ?);", [now_ms])

    def test_dashboard_state_aggregation(self):
        """Testa agregação completa do estado atual de máquinas, cavidades e parâmetros."""
        state = ProductionStateService.get_dashboard_state()
        self.assertEqual(state["total_count"], 2)
        self.assertEqual(state["produzindo_count"], 1)
        self.assertEqual(state["paradas_count"], 1)
        self.assertEqual(state["sem_comunicacao_count"], 0)

        # Checar P1 (Produzindo)
        m1 = next(m for m in state["machines"] if m["nome"] == "Prensa 01")
        self.assertEqual(m1["state"], "PRODUZINDO")
        self.assertFalse(m1["is_stale"])
        self.assertEqual(m1["producao_total"], 80)
        self.assertEqual(m1["meta_total"], 100)
        self.assertEqual(m1["percentual_total"], 80)

        # Checar P2 (Parada e Desatualizada)
        m2 = next(m for m in state["machines"] if m["nome"] == "Prensa 02")
        self.assertEqual(m2["state"], "PARADA")
        self.assertTrue(m2["is_stale"])

        # Checar Parâmetro Global
        p_vacuo = next(p for p in state["global_parameters"] if p["chave"] == "vacuo_geral")
        self.assertEqual(p_vacuo["valor"], "760")

        # Checar Alarme Global
        a_ar = next(a for a in state["global_alarms"] if a["chave"] == "alarme_ar")
        self.assertFalse(a_ar["is_active"])

    def test_dashboard_loads_when_scada_offline(self):
        """Testa se a montagem do estado funciona amigavelmente quando o Scada estiver sem dados."""
        scada_reader.clear_caches()
        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalues;")

        state = ProductionStateService.get_dashboard_state()
        self.assertEqual(state["total_count"], 2)
        self.assertEqual(state["produzindo_count"], 0)
        self.assertEqual(state["paradas_count"], 0)
        self.assertEqual(state["sem_comunicacao_count"], 2)
        self.assertTrue(state["scada_offline"])


class ProductionDashboardViewTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        scada_reader.clear_caches()

        self.prod_leader_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.operator_group, _ = Group.objects.get_or_create(name="Operadores")

        self.prod_user = User.objects.create_user("lider_prod", "lider@test.com", "pwd123")
        self.prod_user.groups.add(self.prod_leader_group)

        self.maint_user = User.objects.create_user("maint_user", "maint@test.com", "pwd123")
        self.maint_user.groups.add(self.operator_group)

    def test_dashboard_accessible_by_production_leader(self):
        """Usuário da Liderança de Produção acessa /producao/ com sucesso (200)."""
        client = Client()
        client.force_login(self.prod_user)
        response = client.get(reverse("production:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel de Estado Atual de Produção")

    def test_dashboard_blocked_for_maintenance_users(self):
        """Usuário da Manutenção é redirecionado e bloqueado de acessar /producao/."""
        client = Client()
        client.force_login(self.maint_user)
        response = client.get(reverse("production:dashboard"))
        self.assertRedirects(response, reverse("home_redirect"), target_status_code=302)


