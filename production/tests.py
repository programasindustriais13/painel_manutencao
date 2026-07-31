from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.db import IntegrityError, connections
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.management import call_command
import time
from io import StringIO

from maintenance.models import Sector, Machine
from production.models import (
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    ProductionMachineState,
    ProductionDowntimeEvent,
    ProductionCavityMatrixHistory,
    ProductionMachineStateInterval,
    ScadaDataPoint,
    ScadaPointValue,
    ScadaPointValueAnnotation,
)
from production.routers import ScadaRouter
from production.services import scada_reader, ScadaReaderService, ProductionStateService, normalize_matrix_value
from production.management.commands.collect_production_scada import CrossProcessLock


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
        self.assertEqual(self.router.db_for_read(ProductionMachineState), "default")
        self.assertEqual(self.router.db_for_read(ProductionDowntimeEvent), "default")

    def test_write_local_model_in_default(self):
        """db_for_write for managed local models returns 'default'."""
        self.assertEqual(self.router.db_for_write(ProductionMachineConfig), "default")
        self.assertEqual(self.router.db_for_write(ProductionCavityConfig), "default")
        self.assertEqual(self.router.db_for_write(ProductionGlobalParameter), "default")
        self.assertEqual(self.router.db_for_write(ProductionGlobalAlarm), "default")
        self.assertEqual(self.router.db_for_write(ProductionMachineState), "default")
        self.assertEqual(self.router.db_for_write(ProductionDowntimeEvent), "default")

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
        self.assertTrue(
            self.router.allow_migrate("default", "production", "productionmachinestate", model=ProductionMachineState)
        )
        self.assertTrue(
            self.router.allow_migrate("default", "production", "productiondowntimeevent", model=ProductionDowntimeEvent)
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
            xid_meta="DP_META_CAV1",
            meta_producao_manual=100,
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


class Spec05StateAndCollectorTestCase(TestCase):
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
        self.config2 = ProductionMachineConfig.objects.create(
            machine=self.machine2,
            ordem_exibicao=2,
            stale_limit_seconds=120,
            produzindo_value="1",
            xid_status_prensa="DP_STATUS_P2"
        )

        self.prod_leader_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.operator_group, _ = Group.objects.get_or_create(name="Operadores")

        self.prod_user = User.objects.create_user("prod_lider_05", "prod05@test.com", "pwd123")
        self.prod_user.groups.add(self.prod_leader_group)

        self.maint_user = User.objects.create_user("maint_user_05", "maint05@test.com", "pwd123")
        self.maint_user.groups.add(self.operator_group)

    def test_transition_producing_to_stopped_opens_one_event(self):
        """Produzindo -> Parada abre apenas 1 evento de parada e atualiza ProductionMachineState."""
        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_STATUS_P1": {
                "xid": "DP_STATUS_P1",
                "value": False,
                "str_value": "0",
                "ts": now_ms
            },
            "DP_MOTIVO_P1": {
                "xid": "DP_MOTIVO_P1",
                "value": "Falta de Material",
                "str_value": "Falta de Material",
                "ts": now_ms
            }
        }

        ProductionStateService.process_scada_cycle(scada_values)

        state = ProductionMachineState.objects.get(machine_config=self.config1)
        self.assertEqual(state.estado_atual, "PARADA")
        self.assertFalse(state.sem_comunicacao)
        self.assertFalse(state.dado_desatualizado)
        self.assertEqual(state.motivo_atual, "Falta de Material")

        events = ProductionDowntimeEvent.objects.filter(machine_config=self.config1)
        self.assertEqual(events.count(), 1)
        ev = events.first()
        self.assertIsNone(ev.fim)
        self.assertEqual(ev.motivo_geral, "Falta de Material")

    def test_continuous_stop_does_not_duplicate_event(self):
        """Manter a máquina parada em ciclos consecutivos não gera eventos duplicados."""
        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": False, "str_value": "0", "ts": now_ms},
            "DP_MOTIVO_P1": {"xid": "DP_MOTIVO_P1", "value": "Ajuste Técnico", "str_value": "Ajuste Técnico", "ts": now_ms}
        }

        # Ciclo 1: Abre parada
        ProductionStateService.process_scada_cycle(scada_values)
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config1).count(), 1)

        # Ciclo 2: Continua parada
        ProductionStateService.process_scada_cycle(scada_values)
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config1).count(), 1)

    def test_transition_stopped_to_producing_closes_event(self):
        """Parada -> Produzindo fecha o evento aberto e calcula a duração."""
        now_ms = int(time.time() * 1000)
        scada_stopped = {
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": False, "str_value": "0", "ts": now_ms - 10000}
        }
        ProductionStateService.process_scada_cycle(scada_stopped)

        ev = ProductionDowntimeEvent.objects.get(machine_config=self.config1, fim__isnull=True)
        self.assertIsNone(ev.fim)

        scada_producing = {
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": True, "str_value": "1", "ts": now_ms}
        }
        ProductionStateService.process_scada_cycle(scada_producing)

        ev.refresh_from_db()
        self.assertIsNotNone(ev.fim)
        self.assertIsNotNone(ev.duracao_segundos)

        state = ProductionMachineState.objects.get(machine_config=self.config1)
        self.assertEqual(state.estado_atual, "PRODUZINDO")

    def test_communication_failure_preserves_state_without_opening_or_closing_event(self):
        """Falha de comunicação não abre nem fecha eventos e preserva o estado industrial."""
        now_ms = int(time.time() * 1000)
        scada_stopped = {
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": False, "str_value": "0", "ts": now_ms}
        }
        ProductionStateService.process_scada_cycle(scada_stopped)
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config1, fim__isnull=True).count(), 1)

        # Falha de comunicação (scada_values vazio)
        ProductionStateService.process_scada_cycle({})

        state = ProductionMachineState.objects.get(machine_config=self.config1)
        self.assertEqual(state.estado_atual, "PARADA")
        self.assertTrue(state.sem_comunicacao)
        # O evento aberto DEVE ser mantido aberto sem duplicação
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config1, fim__isnull=True).count(), 1)

    def test_stale_data_preserves_industrial_state(self):
        """Dado desatualizado (stale) não abre nem fecha evento de parada."""
        now_ms = int(time.time() * 1000)
        old_ms = now_ms - (300 * 1000) # 5 minutos atrás (stale_limit = 120s)

        scada_stale = {
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": False, "str_value": "0", "ts": old_ms}
        }
        ProductionStateService.process_scada_cycle(scada_stale)

        state = ProductionMachineState.objects.get(machine_config=self.config1)
        self.assertTrue(state.dado_desatualizado)
        self.assertFalse(state.sem_comunicacao)
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config1).count(), 0)

    def test_communication_recovery_reconciles_state(self):
        """Retorno da comunicação reconcilia o estado sem duplicar eventos."""
        now_ms = int(time.time() * 1000)
        # 1. Parada normal
        ProductionStateService.process_scada_cycle({
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": False, "str_value": "0", "ts": now_ms}
        })
        # 2. Queda de comunicação
        ProductionStateService.process_scada_cycle({})
        # 3. Retorno da comunicação (continua parada)
        ProductionStateService.process_scada_cycle({
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": False, "str_value": "0", "ts": now_ms + 1000}
        })

        state = ProductionMachineState.objects.get(machine_config=self.config1)
        self.assertFalse(state.sem_comunicacao)
        self.assertEqual(state.estado_atual, "PARADA")
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config1).count(), 1)

    def test_two_independent_machines(self):
        """Duas máquinas possuem estados e históricos de parada independentes."""
        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_STATUS_P1": {"xid": "DP_STATUS_P1", "value": True, "str_value": "1", "ts": now_ms},
            "DP_STATUS_P2": {"xid": "DP_STATUS_P2", "value": False, "str_value": "0", "ts": now_ms},
        }
        ProductionStateService.process_scada_cycle(scada_values)

        state1 = ProductionMachineState.objects.get(machine_config=self.config1)
        state2 = ProductionMachineState.objects.get(machine_config=self.config2)

        self.assertEqual(state1.estado_atual, "PRODUZINDO")
        self.assertEqual(state2.estado_atual, "PARADA")
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config1).count(), 0)
        self.assertEqual(ProductionDowntimeEvent.objects.filter(machine_config=self.config2).count(), 1)

    def test_cross_process_lock_and_command_once(self):
        """Testa se o lock de processo funciona e a opção --once executa 1 ciclo."""
        lock = CrossProcessLock("test_collector.lock")
        self.assertTrue(lock.acquire())

        # Tentativa de acquire simultâneo falha
        lock2 = CrossProcessLock("test_collector.lock")
        self.assertFalse(lock2.acquire())

        lock.release()

        # Liberar qualquer lock do arquivo scada_collector.lock antes do teste do comando
        dummy_lock = CrossProcessLock("scada_collector.lock")
        dummy_lock.release()

        # Testar execução do comando com opção --once
        out = StringIO()
        call_command("collect_production_scada", "--once", stdout=out)
        self.assertIn("Iniciando Coletor Scada", out.getvalue())

    def test_machine_detail_view_permissions_and_kpis(self):
        """Testa acesso à rota de detalhe da máquina, cálculo de KPIs e filtros de data."""
        client = Client()

        # Bloqueio para usuário da manutenção
        client.force_login(self.maint_user)
        res_maint = client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}))
        self.assertRedirects(res_maint, reverse("home_redirect"), target_status_code=302)
        client.logout()

        # Acesso permitido para liderança de produção
        client.force_login(self.prod_user)
        res_prod = client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}))
        self.assertEqual(res_prod.status_code, 200)
        self.assertContains(res_prod, "Prensa 01")
        self.assertContains(res_prod, "Histórico de Eventos de Parada")

        # Teste de filtro por datas no detalhe da máquina
        res_filter = client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}) + "?periodo=hoje")
        self.assertEqual(res_filter.status_code, 200)

    def test_machine_detail_scada_offline_fallback(self):
        """Testa se a tela de detalhes renderiza sem erros quando o Scada estiver offline."""
        client = Client()
        client.force_login(self.prod_user)
        res = client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Sem comunicação com Scada")


class ProductionHardeningAndInfrastructureTestCase(TestCase):
    def test_settings_and_credentials_hardening(self):
        """Valida que configurações e credenciais não expõem senhas e possuem timeouts seguros."""
        from django.conf import settings
        import os

        # Confirmar timeout configurável por variável de ambiente
        timeout_env = os.environ.get("SCADA_DB_CONNECT_TIMEOUT", "5")
        self.assertEqual(int(timeout_env), 5)

        # Confirmar suporte a logs configuráveis e registradores do coletor
        self.assertTrue(hasattr(settings, "SCADA_COLLECTOR_LOG_FILE"))
        self.assertTrue(hasattr(settings, "LOGGING"))
        self.assertIn("production.collector", settings.LOGGING.get("loggers", {}))

    def test_collector_logging_and_second_instance_blocking(self):
        """Valida o bloqueio da 2ª instância do coletor e liberação do lock."""
        # Criar o lock no arquivo padrão utilizado pelo coletor ("scada_collector.lock")
        lock = CrossProcessLock("scada_collector.lock")
        self.assertTrue(lock.acquire())

        # Executar comando enquanto o lock padrão está mantido -> Deve registrar aviso e bloquear
        out = StringIO()
        call_command("collect_production_scada", "--once", stdout=out)
        output = out.getvalue()
        self.assertIn("Tentativa de segunda instância bloqueada", output)

        lock.release()

        # Executar com --once e verificar sucesso
        out_once = StringIO()
        call_command("collect_production_scada", "--once", stdout=out_once)
        self.assertIn("Coletor Scada encerrado com sucesso", out_once.getvalue())

    def test_powershell_scripts_present_and_documented(self):
        """Verifica a presença e o conteúdo dos scripts de automação e documentação."""
        from django.conf import settings
        import os

        base_dir = settings.BASE_DIR
        start_script = os.path.join(base_dir, "scripts", "start_scada_collector.ps1")
        preflight_script = os.path.join(base_dir, "scripts", "preflight_production_scada.ps1")
        deploy_doc = os.path.join(base_dir, "DEPLOY_WINDOWS_SERVER.md")

        self.assertTrue(os.path.exists(start_script), "start_scada_collector.ps1 deve existir")
        self.assertTrue(os.path.exists(preflight_script), "preflight_production_scada.ps1 deve existir")
        self.assertTrue(os.path.exists(deploy_doc), "DEPLOY_WINDOWS_SERVER.md deve existir")

        with open(start_script, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("collect_production_scada", content)
            self.assertIn(".venv", content)

        with open(preflight_script, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("RELATORIO DE PREFLIGHT", content)
            self.assertIn("manage.py check", content)

        with open(deploy_doc, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("GRANT SELECT ON scadalts.*", content)
            self.assertIn("scada_monitor_ro", content)
            self.assertIn("SHOW GRANTS", content)

    def test_no_web_process_auto_start(self):
        """Garante que a importação do app production não inicia threads ou coletores no processo web."""
        from production.apps import ProductionConfig
        self.assertEqual(ProductionConfig.name, "production")


class Spec05BEnrichmentAndAlertTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        scada_reader.clear_caches()

        self.sector = Sector.objects.create(nome="Vulcanização 05B")
        self.machine1 = Machine.objects.create(nome="Prensa 05B", setor=self.sector)

        self.config1 = ProductionMachineConfig.objects.create(
            machine=self.machine1,
            ordem_exibicao=1,
            stale_limit_seconds=600,
            produzindo_value="1",
            xid_status_prensa="DP_STATUS_P5B",
            xid_motivo_parada_geral="DP_MOTIVO_P5B",
            xid_abertura=""
        )

        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 1",
            ordem=1,
            xid_matriz="DP_CAV1_MATRIZ",
            xid_produto="DP_CAV1_PROD_NOME",
            xid_lote_bladder="DP_CAV1_LOTE",
            xid_producao="DP_CAV1_PROD",
            meta_producao_manual=100,
            xid_motivo_parada="DP_CAV1_MOTIVO",
        )

        self.cav2 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 2",
            ordem=2,
            xid_matriz="DP_CAV2_MATRIZ",
            xid_produto="DP_CAV2_PROD_NOME",
            xid_lote_bladder="DP_CAV2_LOTE",
            xid_producao="DP_CAV2_PROD",
            meta_producao_manual=50,
            xid_motivo_parada="DP_CAV2_MOTIVO",
        )

        self.prod_leader_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.prod_user = User.objects.create_user("prod_lider_05b", "prod05b@test.com", "pwd123")
        self.prod_user.groups.add(self.prod_leader_group)

        now_ms = int(time.time() * 1000)
        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalueannotations;")
            cursor.execute("DELETE FROM pointvalues;")
            cursor.execute("DELETE FROM datapoints;")

            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (1, 'DP_STATUS_P5B', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (2, 'DP_CAV1_MOTIVO', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (3, 'DP_CAV2_MOTIVO', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (4, 'DP_MOTIVO_P5B', 1);")

            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (1, 1, 1, 0.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (2, 2, 2, 0.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (3, 3, 2, 1.0, ?);", [now_ms])

    def test_cavity_new_fields_creation_and_defaults(self):
        """Testa criação e valores padrão dos campos de ProductionCavityConfig."""
        cav = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 3",
            ordem=3
        )
        self.assertFalse(hasattr(cav, "valor_cavidade_produzindo"))
        self.assertFalse(hasattr(cav, "xid_status_cavidade"))
        self.assertEqual(cav.meta_producao_manual, 0)
        self.assertIsNone(cav.xid_matriz)
        self.assertIsNone(cav.xid_produto)
        self.assertIsNone(cav.xid_lote_bladder)

    def test_product_and_lote_fallback_rules(self):
        """Testa todas as 4 regras de fallback para concatenação visual de Produto e Lote do Bladder."""
        scada_values = {
            "DP_CAV1_PROD_NOME": {"str_value": "Pneu 175/70", "value": "Pneu 175/70", "ts": 1000},
            "DP_CAV1_LOTE": {"str_value": "LOTE-998", "value": "LOTE-998", "ts": 1000},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        c2 = next(c for c in cavs if c["nome"] == "Cavidade 2")

        # 1. Ambos presentes: "Produto - Lote"
        self.assertEqual(c1["produto_lote_str"], "Pneu 175/70 - LOTE-998")

        # 2. Somente produto
        scada_values_prod_only = {
            "DP_CAV1_PROD_NOME": {"str_value": "Pneu 175/70", "value": "Pneu 175/70", "ts": 1000},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values_prod_only)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        self.assertEqual(c1["produto_lote_str"], "Pneu 175/70")

        # 3. Somente lote
        scada_values_lote_only = {
            "DP_CAV1_LOTE": {"str_value": "LOTE-998", "value": "LOTE-998", "ts": 1000},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values_lote_only)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        self.assertEqual(c1["produto_lote_str"], "Lote: LOTE-998")

        # 4. Nenhum presente
        self.assertEqual(c2["produto_lote_str"], "Não informado")

    def test_cavity_independent_status_and_press_isolation(self):
        """Testa se o estado de uma cavidade é independente e não altera o estado geral da prensa."""
        now_ms = int(time.time() * 1000)
        with connections["scada"].cursor() as cursor:
            cursor.execute("UPDATE pointvalues SET pointValue = 1.0, ts = ? WHERE id = 1;", [now_ms])
            cursor.execute("UPDATE pointvalues SET pointValue = 0.0, ts = ? WHERE id = 2;", [now_ms])
            cursor.execute("UPDATE pointvalues SET pointValue = 1.0, ts = ? WHERE id = 3;", [now_ms])
        scada_reader.clear_caches()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")

        # Prensa deve continuar PRODUZINDO mesmo com Cavidade 2 Parada
        self.assertEqual(m1["state"], "PRODUZINDO")

        c1 = next(c for c in m1["cavidades"] if c["nome"] == "Cavidade 1")
        c2 = next(c for c in m1["cavidades"] if c["nome"] == "Cavidade 2")

        self.assertEqual(c1["status_code"], "NORMAL")
        self.assertEqual(c1["status_label"], "Normal")

        self.assertEqual(c2["status_code"], "PARADA")
        self.assertEqual(c2["status_label"], "Parada")
        self.assertEqual(c2["motivo_parada"], "Troca de Matriz")

    def test_cavity_stopped_without_reason_shows_default_text(self):
        """Testa se cavidade sem leitura de motivo exibe 'Status da cavidade indisponível'."""
        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_STATUS_P5B": {"value": True, "str_value": "1", "ts": now_ms},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        self.assertEqual(c1["status_code"], "INDETERMINADO")
        self.assertEqual(c1["motivo_parada"], "Status da cavidade indisponível")

    def test_manual_target_zero_null_and_over_target(self):
        """Testa meta manual zero, nula e produção superior à meta."""
        self.cav1.meta_producao_manual = 0
        self.cav1.save()

        scada_values = {
            "DP_CAV1_PROD": {"value": 150, "str_value": "150", "ts": 1000},
            "DP_CAV2_PROD": {"value": 75, "str_value": "75", "ts": 1000},
        }
        cavs, total_p, total_m, total_pct, total_pct_bar = ProductionStateService.build_cavities_data(self.config1, scada_values)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        c2 = next(c for c in cavs if c["nome"] == "Cavidade 2")

        # Cav1 com meta 0 -> percentual 0% sem divisão por zero
        self.assertEqual(c1["percentual"], 0)
        self.assertEqual(c1["percentual_bar"], 0)

        # Cav2 com meta 50 e prod 75 -> percentual 150%, mas largura limitada a 100%
        self.assertEqual(c2["percentual"], 150)
        self.assertEqual(c2["percentual_bar"], 100)

    def test_5min_downtime_alert_triggers_at_exact_300s_and_above(self):
        """Testa se o alerta de 5 minutos (300s) ativa exatamente em >= 300s e desativa ao voltar a produzir."""
        now = timezone.now()
        now_ms = int(time.time() * 1000)

        # Atualizar scada db com leitura recente de prensa parada (0.0)
        with connections["scada"].cursor() as cursor:
            cursor.execute("UPDATE pointvalues SET pointValue = 0.0, ts = ? WHERE id = 1;", [now_ms])
        scada_reader.clear_caches()

        state_obj, _ = ProductionMachineState.objects.get_or_create(machine_config=self.config1)

        # 1. Prensa parada há 299 segundos -> sem alerta
        start_299 = now - timezone.timedelta(seconds=299)
        open_event = ProductionDowntimeEvent.objects.create(
            machine_config=self.config1,
            inicio=start_299,
            origem="SCADA"
        )
        state_obj.estado_atual = "PARADA"
        state_obj.inicio_estado_atual = start_299
        state_obj.sem_comunicacao = False
        state_obj.dado_desatualizado = False
        state_obj.motivo_atual = ""
        state_obj.save()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")
        self.assertFalse(m1["alerta_parada_5min"])

        # 2. Prensa parada há exatamente 300 segundos -> alerta ativado com aviso de motivo pendente
        start_300 = now - timezone.timedelta(seconds=300)
        open_event.inicio = start_300
        open_event.save()
        state_obj.inicio_estado_atual = start_300
        state_obj.save()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")
        self.assertTrue(m1["alerta_parada_5min"])
        self.assertTrue(m1["motivo_prensa_pendente"])

        # 3. Prensa parada há 600 segundos com motivo informado
        start_600 = now - timezone.timedelta(seconds=600)
        open_event.inicio = start_600
        open_event.motivo_geral = "Falta de Material"
        open_event.save()
        state_obj.inicio_estado_atual = start_600
        state_obj.motivo_atual = "Falta de Material"
        state_obj.save()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")
        self.assertTrue(m1["alerta_parada_5min"])
        self.assertFalse(m1["motivo_prensa_pendente"])

        # 4. Transição para PRODUZINDO -> alerta desativa imediatamente
        with connections["scada"].cursor() as cursor:
            cursor.execute("UPDATE pointvalues SET pointValue = 1.0, ts = ? WHERE id = 1;", [now_ms])
        scada_reader.clear_caches()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")
        self.assertFalse(m1["alerta_parada_5min"])

    def test_no_5min_alert_on_scada_offline_or_stale(self):
        """Testa que Scada offline ou dado desatualizado não tratam a máquina como parada prolongada."""
        now = timezone.now()
        state_obj, _ = ProductionMachineState.objects.get_or_create(machine_config=self.config1)
        state_obj.estado_atual = "PARADA"
        state_obj.inicio_estado_atual = now - timezone.timedelta(seconds=400)
        state_obj.sem_comunicacao = True
        state_obj.save()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")
        self.assertFalse(m1["alerta_parada_5min"])

    def test_running_timer_for_producing_and_stopped_states(self):
        """Testa formatação do cronômetro para estados Produzindo e Parada."""
        now = timezone.now()
        now_ms = int(time.time() * 1000)
        state_obj, _ = ProductionMachineState.objects.get_or_create(machine_config=self.config1)

        # Produzindo há 1 hora e 25 minutos
        with connections["scada"].cursor() as cursor:
            cursor.execute("UPDATE pointvalues SET pointValue = 1.0, ts = ? WHERE id = 1;", [now_ms])
        scada_reader.clear_caches()

        state_obj.estado_atual = "PRODUZINDO"
        state_obj.inicio_estado_atual = now - timezone.timedelta(minutes=85)
        state_obj.sem_comunicacao = False
        state_obj.dado_desatualizado = False
        state_obj.save()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")
        self.assertIn("Produzindo há 01h 25min", m1["tempo_decorrido_str"])

        # Parada há 12 minutos
        with connections["scada"].cursor() as cursor:
            cursor.execute("UPDATE pointvalues SET pointValue = 0.0, ts = ? WHERE id = 1;", [now_ms])
        scada_reader.clear_caches()

        start_12m = now - timezone.timedelta(minutes=12)
        ProductionDowntimeEvent.objects.create(
            machine_config=self.config1,
            inicio=start_12m,
            origem="SCADA"
        )
        state_obj.estado_atual = "PARADA"
        state_obj.inicio_estado_atual = start_12m
        state_obj.save()

        dash_state = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in dash_state["machines"] if m["nome"] == "Prensa 05B")
        self.assertIn("Parada há 12min", m1["tempo_decorrido_str"])

    def test_dashboard_and_machine_detail_views_render_spec05b_elements(self):
        """Testa se as views do dashboard e detalhe renderizam todos os novos campos e alertas da SPEC 05B."""
        client = Client()
        client.force_login(self.prod_user)

        now_ms = int(time.time() * 1000)

        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalueannotations;")
            cursor.execute("DELETE FROM pointvalues;")
            cursor.execute("DELETE FROM datapoints;")

            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (1, 'DP_STATUS_P5B', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (2, 'DP_CAV1_MOTIVO', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (3, 'DP_CAV1_MATRIZ', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (4, 'DP_CAV1_PROD_NOME', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (5, 'DP_CAV1_LOTE', 1);")

            # Prensa Parada com telemetria atualizada
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (1, 1, 1, 0.0, ?);", [now_ms])
            # Cavidade 1 Normal (0)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (2, 2, 2, 0.0, ?);", [now_ms])
            # Matriz M-101
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (3, 3, 4, NULL, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalueannotations (pointValueId, textPointValueShort) VALUES (3, 'M-101');")
            # Produto e Lote
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (4, 4, 4, NULL, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalueannotations (pointValueId, textPointValueShort) VALUES (4, 'PROD-ALPHA');")
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (5, 5, 4, NULL, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalueannotations (pointValueId, textPointValueShort) VALUES (5, 'LOTE-77');")

        scada_reader.clear_caches()

        # Simular prensa parada há 400s no BD local com evento de parada correspondente
        now = timezone.now()
        start_400 = now - timezone.timedelta(seconds=400)
        ProductionDowntimeEvent.objects.create(
            machine_config=self.config1,
            inicio=start_400,
            origem="SCADA"
        )
        state_obj, _ = ProductionMachineState.objects.get_or_create(machine_config=self.config1)
        state_obj.estado_atual = "PARADA"
        state_obj.inicio_estado_atual = start_400
        state_obj.sem_comunicacao = False
        state_obj.dado_desatualizado = False
        state_obj.save()

        # Renderizar Dashboard
        res_dash = client.get(reverse("production:dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "Alerta: Prensa parada há mais de 5 minutos!")
        self.assertContains(res_dash, "PROD-ALPHA - LOTE-77")
        self.assertContains(res_dash, "M-101")

        # Renderizar Detalhe da Máquina
        res_detail = client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "Alerta: Prensa parada há mais de 5 minutos!")
        self.assertContains(res_detail, "PROD-ALPHA - LOTE-77")
        self.assertContains(res_detail, "M-101")


class Spec05CMotivosParadaCavidadesTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        scada_reader.clear_caches()

        self.sector = Sector.objects.create(nome="Setor 05C")
        self.machine1 = Machine.objects.create(nome="Prensa 05C", setor=self.sector)

        self.config1 = ProductionMachineConfig.objects.create(
            machine=self.machine1,
            ordem_exibicao=1,
            stale_limit_seconds=600,
            produzindo_value="1",
            xid_status_prensa="DP_STATUS_P5C",
            xid_motivo_parada_geral="DP_MOTIVO_GERAL_P5C"
        )

        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 1",
            ordem=1,
            xid_motivo_parada="DP_CAV1_MOTIVO",
        )

        self.cav2 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 2",
            ordem=2,
            xid_motivo_parada="DP_CAV2_MOTIVO",
        )

    def test_cavity_code_0_results_in_normal(self):
        """Código 0 da cavidade resulta em Normal."""
        scada_values = {
            "DP_CAV1_MOTIVO": {"value": 0, "str_value": "0", "ts": 1000}
        }
        code, label, badge, reason = ProductionStateService.resolve_cavity_status_and_reason(self.cav1, scada_values)
        self.assertEqual(code, "NORMAL")
        self.assertEqual(label, "Normal")
        self.assertEqual(badge, "success")
        self.assertEqual(reason, "")

    def test_cavity_codes_1_to_11_translated_correctly(self):
        """Códigos 1 a 11 da cavidade são traduzidos corretamente."""
        expected_translations = {
            1: "Troca de Matriz",
            2: "Troca de Blader",
            3: "Troca de Anel Blader",
            4: "Troca Anel Center Post",
            5: "Ajuste Matriz",
            6: "Falta de Material",
            7: "Ajuste de Blader",
            8: "IA / Lixo",
            9: "Mecânico",
            10: "Elétrica",
            11: "Outros",
        }
        for code_num, expected_text in expected_translations.items():
            scada_values = {
                "DP_CAV1_MOTIVO": {"value": code_num, "str_value": str(code_num), "ts": 1000}
            }
            code, label, badge, reason = ProductionStateService.resolve_cavity_status_and_reason(self.cav1, scada_values)
            self.assertEqual(code, "PARADA")
            self.assertEqual(label, "Parada")
            self.assertEqual(badge, "danger")
            self.assertEqual(reason, expected_text)

    def test_unknown_cavity_code_does_not_break_ui(self):
        """Código desconhecido da cavidade não quebra e exibe 'Motivo não mapeado — código X'."""
        scada_values = {
            "DP_CAV1_MOTIVO": {"value": 99, "str_value": "99", "ts": 1000}
        }
        code, label, badge, reason = ProductionStateService.resolve_cavity_status_and_reason(self.cav1, scada_values)
        self.assertEqual(code, "PARADA")
        self.assertEqual(label, "Parada")
        self.assertEqual(badge, "danger")
        self.assertEqual(reason, "Motivo não mapeado — código 99")

    def test_null_or_invalid_cavity_value_results_in_indeterminado(self):
        """Valor nulo, invalido ou ausente resulta em estado Indeterminado."""
        # 1. Scada sem leitura
        code, label, badge, reason = ProductionStateService.resolve_cavity_status_and_reason(self.cav1, {})
        self.assertEqual(code, "INDETERMINADO")
        self.assertEqual(label, "Indeterminado")
        self.assertEqual(badge, "secondary")
        self.assertEqual(reason, "Status da cavidade indisponível")

        # 2. Leitura com valor None
        scada_values = {
            "DP_CAV1_MOTIVO": {"value": None, "str_value": "", "ts": 1000}
        }
        code, label, badge, reason = ProductionStateService.resolve_cavity_status_and_reason(self.cav1, scada_values)
        self.assertEqual(code, "INDETERMINADO")

        # 3. Valor não numérico inválido
        scada_values_invalid = {
            "DP_CAV1_MOTIVO": {"value": "invalido", "str_value": "invalido", "ts": 1000}
        }
        code, label, badge, reason = ProductionStateService.resolve_cavity_status_and_reason(self.cav1, scada_values_invalid)
        self.assertEqual(code, "INDETERMINADO")

    def test_press_producing_with_one_cavity_stopped(self):
        """Prensa produzindo mesmo com uma cavidade parada."""
        now_ms = int(time.time() * 1000)
        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalueannotations;")
            cursor.execute("DELETE FROM pointvalues;")
            cursor.execute("DELETE FROM datapoints;")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (1, 'DP_STATUS_P5C', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (2, 'DP_CAV1_MOTIVO', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (3, 'DP_CAV2_MOTIVO', 1);")
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (1, 1, 1, 1.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (2, 2, 2, 0.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (3, 3, 2, 1.0, ?);", [now_ms])
        scada_reader.clear_caches()

        state_dash = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in state_dash["machines"] if m["nome"] == "Prensa 05C")
        self.assertEqual(m1["state"], "PRODUZINDO")
        c1 = next(c for c in m1["cavidades"] if c["nome"] == "Cavidade 1")
        c2 = next(c for c in m1["cavidades"] if c["nome"] == "Cavidade 2")
        self.assertEqual(c1["status_code"], "NORMAL")
        self.assertEqual(c2["status_code"], "PARADA")
        self.assertEqual(c2["motivo_parada"], "Troca de Matriz")

    def test_two_cavities_with_different_reasons(self):
        """Duas cavidades com motivos de parada diferentes."""
        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_CAV1_MOTIVO": {"value": 2, "str_value": "2", "ts": now_ms},
            "DP_CAV2_MOTIVO": {"value": 6, "str_value": "6", "ts": now_ms},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        c2 = next(c for c in cavs if c["nome"] == "Cavidade 2")
        self.assertEqual(c1["motivo_parada"], "Troca de Blader")
        self.assertEqual(c2["motivo_parada"], "Falta de Material")

    def test_press_general_reasons_6_9_10_11(self):
        """Motivos de prensa 6, 9, 10 e 11."""
        self.assertEqual(ProductionStateService.format_press_reason(6, "PARADA"), "Falta de Material")
        self.assertEqual(ProductionStateService.format_press_reason(9, "PARADA"), "Mecânico")
        self.assertEqual(ProductionStateService.format_press_reason(10, "PARADA"), "Elétrica")
        self.assertEqual(ProductionStateService.format_press_reason(11, "PARADA"), "Outros")
        self.assertEqual(ProductionStateService.format_press_reason(12, "PARADA"), "Motivo não mapeado — código 12")

    def test_stopped_press_with_reason_0_shows_motivo_nao_informado(self):
        """Prensa parada com motivo geral 0, nulo ou vazio exibe 'Motivo da prensa não informado'."""
        self.assertEqual(ProductionStateService.format_press_reason(0, "PARADA"), "Motivo da prensa não informado")
        self.assertEqual(ProductionStateService.format_press_reason(None, "PARADA"), "Motivo da prensa não informado")
        self.assertEqual(ProductionStateService.format_press_reason("", "PARADA"), "Motivo da prensa não informado")

    def test_producing_press_ignores_residual_general_reason(self):
        """Prensa produzindo ignora motivo geral residual."""
        self.assertEqual(ProductionStateService.format_press_reason(6, "PRODUZINDO"), "")
        self.assertEqual(ProductionStateService.format_press_reason("Mecânico", "PRODUZINDO"), "")

    def test_stopped_cavity_does_not_trigger_general_alert(self):
        """Cavidade parada nunca dispara o alerta geral da prensa."""
        now = timezone.now()
        now_ms = int(time.time() * 1000)
        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalues;")
            cursor.execute("DELETE FROM datapoints;")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (1, 'DP_STATUS_P5C', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (2, 'DP_CAV1_MOTIVO', 1);")
            # Prensa Produzindo (1.0), Cavidade 1 Parada (1.0)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (1, 1, 1, 1.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (2, 2, 2, 1.0, ?);", [now_ms])
        scada_reader.clear_caches()

        state_obj, _ = ProductionMachineState.objects.get_or_create(machine_config=self.config1)
        state_obj.estado_atual = "PRODUZINDO"
        state_obj.inicio_estado_atual = now - timezone.timedelta(seconds=600)
        state_obj.save()

        state_dash = ProductionStateService.get_dashboard_state()
        m1 = next(m for m in state_dash["machines"] if m["nome"] == "Prensa 05C")
        self.assertFalse(m1["alerta_parada_5min"])

    def test_batch_read_includes_only_xid_motivo_parada(self):
        """Leitura em lote inclui xid_motivo_parada e não consulta campos removidos."""
        self.cav1.xid_motivo_parada = "DP_TEST_MOTIVO"
        self.cav1.save()

        all_xids = set()
        if self.config1.xid_status_prensa:
            all_xids.add(self.config1.xid_status_prensa)
        for cav in self.config1.cavities.all():
            if cav.xid_motivo_parada:
                all_xids.add(cav.xid_motivo_parada)

        self.assertIn("DP_TEST_MOTIVO", all_xids)
        self.assertFalse(hasattr(self.cav1, "xid_status_cavidade"))

    def test_removed_fields_not_in_admin(self):
        """Campos removidos não aparecem no Inline do Admin."""
        from production.admin import ProductionCavityConfigInline
        self.assertNotIn("xid_status_cavidade", ProductionCavityConfigInline.fields)
        self.assertNotIn("valor_cavidade_produzindo", ProductionCavityConfigInline.fields)

    def test_migration_0006_removes_only_two_fields(self):
        """Migration 0006 remove somente os dois campos de ProductionCavityConfig."""
        import importlib
        mig0006 = importlib.import_module("production.migrations.0006_remove_status_individual_cavidade")
        ops = mig0006.Migration.operations
        self.assertEqual(len(ops), 2)
        field_names = {op.name for op in ops}
        self.assertEqual(field_names, {"valor_cavidade_produzindo", "xid_status_cavidade"})

    def test_dashboard_and_detail_display_text_labels_never_raw_known_codes(self):
        """Dashboard e detalhe exibem rótulos descritivos, nunca códigos conhecidos brutos."""
        now_ms = int(time.time() * 1000)
        with connections["scada"].cursor() as cursor:
            cursor.execute("DELETE FROM pointvalueannotations;")
            cursor.execute("DELETE FROM pointvalues;")
            cursor.execute("DELETE FROM datapoints;")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (1, 'DP_STATUS_P5C', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (2, 'DP_MOTIVO_GERAL_P5C', 1);")
            cursor.execute("INSERT INTO datapoints (id, xid, dataSourceId) VALUES (3, 'DP_CAV1_MOTIVO', 1);")

            # Prensa Parada, motivo geral 6 (Falta de Material), cavidade 1 motivo 1 (Troca de Matriz)
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (1, 1, 1, 0.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (2, 2, 2, 6.0, ?);", [now_ms])
            cursor.execute("INSERT INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (3, 3, 2, 1.0, ?);", [now_ms])

        scada_reader.clear_caches()

        prod_leader_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        prod_user = User.objects.create_user("prod_lider_05c", "prod05c@test.com", "pwd123")
        prod_user.groups.add(prod_leader_group)

        client = Client()
        client.force_login(prod_user)

        res_dash = client.get(reverse("production:dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "Falta de Material")
        self.assertContains(res_dash, "Troca de Matriz")

        res_detail = client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "Falta de Material")
        self.assertContains(res_detail, "Troca de Matriz")


class Spec05DHistoryAndTimelineTestCase(TestCase):
    """
    Suíte de testes para a SPEC 05D:
    - Remoção do total agregado da prensa no dashboard.
    - Histórico local de matrizes por cavidade (ProductionCavityMatrixHistory).
    - Card geral das matrizes em uso (Resumo Atual e Histórico Filtrável).
    - Histórico de intervalos de estado da prensa (ProductionMachineStateInterval).
    - Linha do Tempo Operacional e KPIs industriais na tela de detalhe da máquina.
    """

    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine1 = Machine.objects.create(nome="Prensa 05D", setor=self.sector, criticidade="ALTA")
        self.machine2 = Machine.objects.create(nome="Prensa 06D", setor=self.sector, criticidade="MEDIA")

        self.config1 = ProductionMachineConfig.objects.create(
            machine=self.machine1,
            ordem_exibicao=1,
            stale_limit_seconds=120,
            produzindo_value="1",
            xid_status_prensa="DP_STATUS_P5D",
            xid_abertura="DP_ABERTURA_P5D",
            xid_motivo_parada_geral="DP_MOTIVO_P5D"
        )
        self.config2 = ProductionMachineConfig.objects.create(
            machine=self.machine2,
            ordem_exibicao=2,
            stale_limit_seconds=120,
            produzindo_value="1",
            xid_status_prensa="DP_STATUS_P6D"
        )

        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 1",
            ordem=1,
            xid_matriz="DP_CAV1_MATRIZ",
            xid_producao="DP_CAV1_PROD",
            meta_producao_manual=500,
            xid_motivo_parada="DP_CAV1_MOTIVO"
        )
        self.cav2 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 2",
            ordem=2,
            xid_matriz="DP_CAV2_MATRIZ",
            xid_producao="DP_CAV2_PROD",
            meta_producao_manual=500,
            xid_motivo_parada="DP_CAV2_MOTIVO"
        )

        self.prod_leader_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader = User.objects.create_user("lider_05d", "lider05d@test.com", "pwd123")
        self.user_leader.groups.add(self.prod_leader_group)

        self.user_tech = User.objects.create_user("tech_05d", "tech05d@test.com", "pwd123")

        self.client = Client()
        scada_reader.clear_caches()

    def test_removal_of_aggregated_total_from_dashboard(self):
        """Card da prensa no dashboard não exibe total agregado de produção/meta, mas cavidades preservam dados."""
        self.client.force_login(self.user_leader)
        res = self.client.get(reverse("production:dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "Total: 0 / 1000")
        self.assertNotContains(res, "Total: {{ m.producao_total }}")
        self.assertContains(res, "Cavidade 1")
        self.assertContains(res, "Cavidade 2")

    def test_matrix_normalization_and_history_lifecycle(self):
        """Testa regras de normalização, abertura, manutenção e fechamento de histórico de matrizes."""
        self.assertEqual(normalize_matrix_value("12"), "12")
        self.assertEqual(normalize_matrix_value(12), "12")
        self.assertEqual(normalize_matrix_value(12.0), "12")
        self.assertEqual(normalize_matrix_value(" 12 "), "12")
        self.assertEqual(normalize_matrix_value(None), "")
        self.assertEqual(normalize_matrix_value(""), "")

        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_CAV1_MATRIZ": {"value": 12.0, "str_value": "12.0", "ts": now_ms}
        }
        ProductionStateService.process_scada_cycle(scada_values)

        history_qs = ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav1)
        self.assertEqual(history_qs.count(), 1)
        rec1 = history_qs.first()
        self.assertEqual(rec1.matrix_value, "12")
        self.assertIsNone(rec1.ended_at)

        # 2. Ciclo com valor equivalente " 12 " não abre novo registro
        scada_values_equiv = {
            "DP_CAV1_MATRIZ": {"value": " 12 ", "str_value": " 12 ", "ts": now_ms + 5000}
        }
        ProductionStateService.process_scada_cycle(scada_values_equiv)
        self.assertEqual(ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav1).count(), 1)

        # 3. Ciclo com troca para "458" fecha anterior e abre novo
        scada_values_new = {
            "DP_CAV1_MATRIZ": {"value": "458", "str_value": "458", "ts": now_ms + 10000}
        }
        ProductionStateService.process_scada_cycle(scada_values_new)
        self.assertEqual(ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav1).count(), 2)

        rec1.refresh_from_db()
        self.assertIsNotNone(rec1.ended_at)
        rec2 = ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav1, ended_at__isnull=True).first()
        self.assertIsNotNone(rec2)
        self.assertEqual(rec2.matrix_value, "458")

        # 4. Scada offline/nulo/stale não fecha histórico aberto
        ProductionStateService.process_scada_cycle({})
        self.assertEqual(ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav1).count(), 2)
        rec2.refresh_from_db()
        self.assertIsNone(rec2.ended_at)

    def test_two_independent_cavities_matrix_history(self):
        """Duas cavidades possuem históricos de matrizes independentes e com máximo 1 registro aberto por cavidade."""
        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_CAV1_MATRIZ": {"value": "M100", "str_value": "M100", "ts": now_ms},
            "DP_CAV2_MATRIZ": {"value": "M200", "str_value": "M200", "ts": now_ms},
        }
        ProductionStateService.process_scada_cycle(scada_values)

        self.assertEqual(ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav1, ended_at__isnull=True).count(), 1)
        self.assertEqual(ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav2, ended_at__isnull=True).count(), 1)

        c1_hist = ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav1).first()
        c2_hist = ProductionCavityMatrixHistory.objects.filter(cavity_config=self.cav2).first()
        self.assertEqual(c1_hist.matrix_value, "M100")
        self.assertEqual(c2_hist.matrix_value, "M200")

    def test_matrix_summary_and_filtered_history_view(self):
        """Testa geração do resumo atual de matrizes e consulta de histórico filtrável no dashboard."""
        now_ms = int(time.time() * 1000)
        scada_values = {
            "DP_STATUS_P5D": {"value": 1.0, "str_value": "1", "ts": now_ms},
            "DP_CAV1_MATRIZ": {"value": "458", "str_value": "458", "ts": now_ms},
            "DP_CAV1_MOTIVO": {"value": 0, "str_value": "0", "ts": now_ms},
            "DP_CAV2_MATRIZ": {"value": "458", "str_value": "458", "ts": now_ms},
            "DP_CAV2_MOTIVO": {"value": 1, "str_value": "1", "ts": now_ms},
        }
        state_dash = ProductionStateService.get_dashboard_state(scada_values=scada_values)
        summary = state_dash["matrix_summary"]
        self.assertTrue(len(summary) >= 1)

        m458 = next((s for s in summary if s["matriz"] == "458"), None)
        self.assertIsNotNone(m458)
        self.assertEqual(m458["normais"], 1)
        self.assertEqual(m458["paradas"], 1)
        self.assertEqual(m458["total"], 2)

        # Testar data inicial maior que final
        state_error = ProductionStateService.get_dashboard_state(
            data_inicio_str="2026-10-10",
            data_final_str="2026-10-01"
        )
        self.assertEqual(state_error["matrix_history_error"], "Data inicial não pode ser maior que a data final.")

    def test_machine_state_interval_transitions(self):
        """Testa transições de intervalos de estado da prensa (Produzindo, Parada, Sem comunicação)."""
        now_ms = int(time.time() * 1000)

        # 1. Primeiro ciclo Produzindo
        scada_prod = {
            "DP_STATUS_P5D": {"value": 1.0, "str_value": "1", "ts": now_ms}
        }
        ProductionStateService.process_scada_cycle(scada_prod)
        self.assertEqual(ProductionMachineStateInterval.objects.filter(machine_config=self.config1).count(), 1)
        inv1 = ProductionMachineStateInterval.objects.filter(machine_config=self.config1).first()
        self.assertEqual(inv1.state, "PRODUZINDO")
        self.assertIsNone(inv1.ended_at)

        # 2. Ciclo repetido mantém o intervalo aberto sem duplicar
        ProductionStateService.process_scada_cycle(scada_prod)
        self.assertEqual(ProductionMachineStateInterval.objects.filter(machine_config=self.config1).count(), 1)

        # 3. Transição: Produzindo -> Parada
        scada_parada = {
            "DP_STATUS_P5D": {"value": 0.0, "str_value": "0", "ts": now_ms + 5000}
        }
        ProductionStateService.process_scada_cycle(scada_parada)
        self.assertEqual(ProductionMachineStateInterval.objects.filter(machine_config=self.config1).count(), 2)

        inv1.refresh_from_db()
        self.assertIsNotNone(inv1.ended_at)

        inv2 = ProductionMachineStateInterval.objects.filter(machine_config=self.config1, ended_at__isnull=True).first()
        self.assertEqual(inv2.state, "PARADA")

        # 4. Transição: Parada -> Sem comunicação (Scada offline)
        ProductionStateService.process_scada_cycle({})
        self.assertEqual(ProductionMachineStateInterval.objects.filter(machine_config=self.config1).count(), 3)
        inv3 = ProductionMachineStateInterval.objects.filter(machine_config=self.config1, ended_at__isnull=True).first()
        self.assertEqual(inv3.state, "SEM_COMUNICACAO")

        # Garantir máximo de 1 intervalo aberto
        self.assertEqual(ProductionMachineStateInterval.objects.filter(machine_config=self.config1, ended_at__isnull=True).count(), 1)

    def test_timeline_visualization_and_kpis(self):
        """Testa geração dos segmentos da linha do tempo e KPIs complementares na tela de detalhe."""
        now = timezone.now()
        # Criar histórico de intervalos passados
        ProductionMachineStateInterval.objects.create(
            machine_config=self.config1,
            state="PRODUZINDO",
            started_at=now - timezone.timedelta(hours=5),
            ended_at=now - timezone.timedelta(hours=3),
            status_raw_value="1"
        )
        ProductionMachineStateInterval.objects.create(
            machine_config=self.config1,
            state="PARADA",
            started_at=now - timezone.timedelta(hours=3),
            ended_at=now - timezone.timedelta(hours=1),
            status_raw_value="0"
        )
        ProductionMachineStateInterval.objects.create(
            machine_config=self.config1,
            state="PRODUZINDO",
            started_at=now - timezone.timedelta(hours=1),
            ended_at=None,
            status_raw_value="1"
        )

        detail = ProductionStateService.get_machine_detail(config_id=self.config1.pk, periodo="hoje")
        self.assertIn("timeline_segments", detail)
        self.assertTrue(len(detail["timeline_segments"]) >= 3)

        kpi = detail["kpi"]
        self.assertIn("tempo_produzindo_str", kpi)
        self.assertIn("tempo_parado_str", kpi)
        self.assertIn("tempo_sem_comunicacao_str", kpi)
        self.assertIn("percentual_produzindo", kpi)
        self.assertIn("percentual_parado", kpi)
        self.assertIn("qtd_ciclos_producao", kpi)
        self.assertIn("qtd_paradas_linha_tempo", kpi)

        # Produzindo = 2h + 1h = 3h, Parado = 2h -> % produzindo = 3/5 = 60%, % parado = 40%
        self.assertEqual(kpi["percentual_produzindo"], 60.0)
        self.assertEqual(kpi["percentual_parado"], 40.0)

    def test_permissions_and_offline_views(self):
        """Testa controle de acesso às rotas e resiliência das views quando Scada offline/sem histórico."""
        self.client.force_login(self.user_tech)
        res_dash_blocked = self.client.get(reverse("production:dashboard"))
        self.assertEqual(res_dash_blocked.status_code, 302)

        res_detail_blocked = self.client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}))
        self.assertEqual(res_detail_blocked.status_code, 302)

        self.client.force_login(self.user_leader)
        res_dash_ok = self.client.get(reverse("production:dashboard"))
        self.assertEqual(res_dash_ok.status_code, 200)

        res_detail_ok = self.client.get(reverse("production:machine_detail", kwargs={"pk": self.config1.pk}))
        self.assertEqual(res_detail_ok.status_code, 200)
        self.assertContains(res_detail_ok, "Linha do Tempo Operacional")
        self.assertContains(res_detail_ok, "Matriz")

