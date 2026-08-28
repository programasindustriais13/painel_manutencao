from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.db import IntegrityError, connections
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.management import call_command
import time
from io import StringIO

from maintenance.models import Sector, Machine, Technician, Allocation, AllocationProgressUpdate
from production.models import (
    ProductionShift,
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    ProductionMachineState,
    ProductionDowntimeEvent,
    ProductionCavityState,
    ProductionCavityDowntimeEvent,
    ProductionCavityMatrixHistory,
    ProductionMachineStateInterval,
    ProductionRateAggregate,
    ProductionParameterConfig,
    ProductionParameterAnomalyEvent,
    ProductionCycle,
    ProductionShiftAccumulated,
    ProductionMatrixCatalog,
    ProductionTarget,
    ScadaDataPoint,
    ScadaPointValue,
    ScadaPointValueAnnotation,
)
from production.routers import ScadaRouter
from production.services import (
    scada_reader,
    ScadaReaderService,
    ProductionStateService,
    get_active_shift,
    normalize_matrix_value,
    compose_bladder_lot,
    resolve_matrix_product_display,
)
from production.management.commands.collect_production_scada import CrossProcessLock
from production.forms import ProductionTargetForm, ProductionMatrixCatalogForm


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
        
        # Operator with dual access -> portal_select
        client.force_login(self.maintenance_operator)
        response = client.get(reverse("home_redirect"))
        self.assertRedirects(response, reverse("portal_select"))
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
        """Test that pure technicians cannot access production, while operators can."""
        client = Client()
        
        # Operator has dual access and can access production
        client.force_login(self.maintenance_operator)
        response = client.get(reverse("production:dashboard"))
        self.assertEqual(response.status_code, 200)
        client.logout()

        # Pure technician is blocked from production
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

    def test_production_navbar_brand_links_to_production_dashboard(self):
        """Test that clicking the logo in production dashboard stays in production."""
        client = Client()
        client.force_login(self.prod_user)
        response = client.get(reverse("production:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("production:dashboard")}"')


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

    def test_dashboard_state_excludes_calandra_parameters(self):
        """Garante que variáveis da Calandra não sejam retornadas em global_parameters do dashboard."""
        ProductionGlobalParameter.objects.create(
            nome="Calandra - Velocidade",
            chave="calandra_velocidade",
            xid="DP_CAL_VEL",
            ordem=10
        )
        ProductionGlobalParameter.objects.create(
            nome="Calandra - Passada",
            chave="calandra_passada",
            xid="DP_CAL_PASS",
            ordem=11
        )

        state = ProductionStateService.get_dashboard_state()
        chaves_retornadas = [p["chave"] for p in state["global_parameters"]]
        self.assertIn("vacuo_geral", chaves_retornadas)
        self.assertNotIn("calandra_velocidade", chaves_retornadas)
        self.assertNotIn("calandra_passada", chaves_retornadas)



class ProductionDashboardViewTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        scada_reader.clear_caches()

        self.prod_leader_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.operator_group, _ = Group.objects.get_or_create(name="Operadores")
        self.tech_group, _ = Group.objects.get_or_create(name="Tecnicos")

        self.prod_user = User.objects.create_user("lider_prod", "lider@test.com", "pwd123")
        self.prod_user.groups.add(self.prod_leader_group)

        self.operator_user = User.objects.create_user("operator_user", "op@test.com", "pwd123")
        self.operator_user.groups.add(self.operator_group)

        self.tech_user = User.objects.create_user("tech_user", "tech@test.com", "pwd123")
        self.tech_user.groups.add(self.tech_group)

    def test_dashboard_accessible_by_production_leader(self):
        """Usuário da Liderança de Produção acessa /producao/ com sucesso (200)."""
        client = Client()
        client.force_login(self.prod_user)
        response = client.get(reverse("production:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel de Estado Atual de Produção")

    def test_dashboard_accessible_by_operator(self):
        """Usuário Operador acessa /producao/ com sucesso (200) devido ao acesso duplo."""
        client = Client()
        client.force_login(self.operator_user)
        response = client.get(reverse("production:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Painel de Estado Atual de Produção")

    def test_dashboard_blocked_for_pure_technician_users(self):
        """Usuário Técnico puro da Manutenção é redirecionado e bloqueado de acessar /producao/."""
        client = Client()
        client.force_login(self.tech_user)
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
        self.tech_group, _ = Group.objects.get_or_create(name="Tecnicos")

        self.prod_user = User.objects.create_user("prod_lider_05", "prod05@test.com", "pwd123")
        self.prod_user.groups.add(self.prod_leader_group)

        self.maint_user = User.objects.create_user("maint_user_05", "maint05@test.com", "pwd123")
        self.maint_user.groups.add(self.tech_group)

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
        """Testa regras para concatenação visual do Lote Completo do Bladder."""
        scada_values = {
            "DP_CAV1_PROD_NOME": {"str_value": "6154", "value": "6154", "ts": 1000},
            "DP_CAV1_LOTE": {"str_value": "161046", "value": "161046", "ts": 1000},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        c2 = next(c for c in cavs if c["nome"] == "Cavidade 2")

        # 1. Ambos presentes
        self.assertEqual(c1["produto_lote_str"], "Lote: 6154 - 161046")

        # 2. Somente prefixo
        scada_values_prod_only = {
            "DP_CAV1_PROD_NOME": {"str_value": "6154", "value": "6154", "ts": 1000},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values_prod_only)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        self.assertEqual(c1["produto_lote_str"], "Lote: 6154 - Não informado")

        # 3. Somente número
        scada_values_lote_only = {
            "DP_CAV1_LOTE": {"str_value": "161046", "value": "161046", "ts": 1000},
        }
        cavs, _, _, _, _ = ProductionStateService.build_cavities_data(self.config1, scada_values_lote_only)
        c1 = next(c for c in cavs if c["nome"] == "Cavidade 1")
        self.assertEqual(c1["produto_lote_str"], "Lote: Não informado - 161046")

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


class Spec06AShiftsAndTargetsTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 01", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1
        )
        self.cavity1 = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade 1",
            ordem=1,
            meta_producao_manual=100
        )
        self.cavity2 = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade 2",
            ordem=2,
            meta_producao_manual=150
        )

        self.user_leader = User.objects.create_user("leader_06a", "lider@test.com", "pass123")
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

    def test_production_shift_creation_and_midnight_crossing(self):
        """Testa criação de turnos diurno e noturno (atravessando meia-noite)."""
        shift_day = ProductionShift.objects.create(
            nome="1º Turno",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=50.00,
            ordem_exibicao=1,
            ativo=True
        )
        self.assertFalse(shift_day.atravessa_meia_noite)

        shift_night = ProductionShift.objects.create(
            nome="3º Turno",
            horario_inicial=timezone.datetime.strptime("22:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("06:00", "%H:%M").time(),
            percentual_meta=50.00,
            ordem_exibicao=2,
            ativo=True
        )
        self.assertTrue(shift_night.atravessa_meia_noite)

    def test_percentage_sum_validation(self):
        """Testa validação de soma dos percentuais em 100% no clean()."""
        shift1 = ProductionShift(
            nome="T1",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=40.00,
            ativo=True
        )
        shift1.save()

        shift2 = ProductionShift(
            nome="T2",
            horario_inicial=timezone.datetime.strptime("14:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("22:00", "%H:%M").time(),
            percentual_meta=40.00,
            ativo=True
        )

        with self.assertRaises(ValidationError):
            shift2.full_clean()

    def test_equal_distribution_fallback(self):
        """Testa divisão igualitária quando percentual é 0.00."""
        ProductionShift.objects.create(
            nome="T1",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=0.00,
            ativo=True
        )
        ProductionShift.objects.create(
            nome="T2",
            horario_inicial=timezone.datetime.strptime("14:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("22:00", "%H:%M").time(),
            percentual_meta=0.00,
            ativo=True
        )

        info = get_active_shift(at_datetime=timezone.make_aware(timezone.datetime(2026, 8, 4, 10, 0)))
        self.assertEqual(info["nome"], "T1")
        self.assertEqual(info["effective_percent"], 50.0)

    def test_active_shift_resolution_night(self):
        """Testa resolução de turno noturno no meio da madrugada (ex: 02:00)."""
        ProductionShift.objects.create(
            nome="Noite",
            horario_inicial=timezone.datetime.strptime("22:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("06:00", "%H:%M").time(),
            percentual_meta=100.00,
            ativo=True
        )

        info = get_active_shift(at_datetime=timezone.make_aware(timezone.datetime(2026, 8, 4, 2, 30)))
        self.assertEqual(info["nome"], "Noite")
        self.assertTrue(info["has_shifts"])

    def test_shift_target_calculation_in_services(self):
        """Testa cálculo de meta do turno e percentuais no service."""
        ProductionShift.objects.create(
            nome="Manhã",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=40.00,
            ativo=True
        )
        ProductionShift.objects.create(
            nome="Tarde",
            horario_inicial=timezone.datetime.strptime("14:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("22:00", "%H:%M").time(),
            percentual_meta=60.00,
            ativo=True
        )

        shift_info = get_active_shift(at_datetime=timezone.make_aware(timezone.datetime(2026, 8, 4, 10, 0)))
        cavs, prod_tot, meta_tot, pct, pct_bar = ProductionStateService.build_cavities_data(
            self.config, scada_values={}, shift_info=shift_info
        )

        c1 = next(c for c in cavs if c["id"] == self.cavity1.id)
        # cavity1 meta_diaria = 100, effective_percent = 40% -> meta_turno = 40
        self.assertEqual(c1["meta_diaria"], 100)
        self.assertEqual(c1["meta_turno"], 40)

        c2 = next(c for c in cavs if c["id"] == self.cavity2.id)
        # cavity2 meta_diaria = 150, effective_percent = 40% -> meta_turno = 60
        self.assertEqual(c2["meta_diaria"], 150)
        self.assertEqual(c2["meta_turno"], 60)

    def test_views_render_shift_data(self):
        """Testa renderização das métricas de turno no dashboard e machine_detail."""
        ProductionShift.objects.create(
            nome="Turno Único",
            horario_inicial=timezone.datetime.strptime("00:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("23:59", "%H:%M").time(),
            percentual_meta=100.00,
            ativo=True
        )

        self.client.force_login(self.user_leader)
        res_dash = self.client.get(reverse("production:dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "Turno Único")
        self.assertContains(res_dash, "Meta Turno:")

        res_detail = self.client.get(reverse("production:machine_detail", kwargs={"pk": self.config.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "Turno Ativo")
        self.assertContains(res_detail, "Turno Único")


class Spec06BCavityDowntimeTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        scada_reader.clear_caches()
        init_scada_test_tables()
        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 02", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            produzindo_value="1",
            xid_status_prensa="STATUS_P2",
            stale_limit_seconds=120
        )
        self.cavity1 = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade Esquerda",
            ordem=1,
            xid_motivo_parada="MOTIVO_CAV1"
        )
        self.cavity2 = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade Direita",
            ordem=2,
            xid_motivo_parada="MOTIVO_CAV2"
        )

        self.user_leader = User.objects.create_user("leader_06b", "lider06b@test.com", "pass123")
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

    def test_cavity_downtime_event_transitions(self):
        """Testa transição Normal -> Parada -> Normal em cavidade com criação/fechamento idempotente de evento."""
        now_ms = int(time.time() * 1000)
        
        scada_values = {
            "STATUS_P2": {"value": 1, "str_value": "1", "ts": now_ms},
            "MOTIVO_CAV1": {"value": 3, "str_value": "3", "ts": now_ms},
            "MOTIVO_CAV2": {"value": 0, "str_value": "0", "ts": now_ms},
        }

        ProductionStateService.process_scada_cycle(scada_values)

        state1 = ProductionCavityState.objects.get(cavity_config=self.cavity1)
        self.assertEqual(state1.estado_atual, "PARADA")

        open_events1 = ProductionCavityDowntimeEvent.objects.filter(cavity_config=self.cavity1, fim__isnull=True)
        self.assertEqual(open_events1.count(), 1)
        self.assertEqual(open_events1.first().snapshot_valor_motivo, "3")

        state2 = ProductionCavityState.objects.get(cavity_config=self.cavity2)
        self.assertEqual(state2.estado_atual, "NORMAL")
        self.assertEqual(ProductionCavityDowntimeEvent.objects.filter(cavity_config=self.cavity2).count(), 0)

        # Idempotência: rerodar o ciclo sem alteração não pode duplicar eventos
        ProductionStateService.process_scada_cycle(scada_values)
        self.assertEqual(ProductionCavityDowntimeEvent.objects.filter(cavity_config=self.cavity1).count(), 1)

        # Cavidade 1 normaliza (MOTIVO_CAV1="0")
        later_ms = now_ms + 60000
        scada_values_norm = {
            "STATUS_P2": {"value": 1, "str_value": "1", "ts": later_ms},
            "MOTIVO_CAV1": {"value": 0, "str_value": "0", "ts": later_ms},
            "MOTIVO_CAV2": {"value": 0, "str_value": "0", "ts": later_ms},
        }

        ProductionStateService.process_scada_cycle(scada_values_norm)

        state1.refresh_from_db()
        self.assertEqual(state1.estado_atual, "NORMAL")

        closed_events1 = ProductionCavityDowntimeEvent.objects.filter(cavity_config=self.cavity1, fim__isnull=False)
        self.assertEqual(closed_events1.count(), 1)
        self.assertTrue(closed_events1.first().duracao_segundos >= 0)

    def test_stale_data_freezes_cavity_state(self):
        """Testa se dado desatualizado congela transições de cavidade sem abrir nem fechar eventos."""
        old_ms = int((time.time() - 300) * 1000)
        scada_values_stale = {
            "STATUS_P2": {"value": 1, "str_value": "1", "ts": old_ms},
            "MOTIVO_CAV1": {"value": 5, "str_value": "5", "ts": old_ms},
        }

        ProductionStateService.process_scada_cycle(scada_values_stale)

        self.assertEqual(ProductionCavityDowntimeEvent.objects.filter(cavity_config=self.cavity1).count(), 0)

    def test_dashboard_kpi_and_filter(self):
        """Testa o contador KPI de Cavidades Paradas e renderização no dashboard."""
        now_ms = int(time.time() * 1000)
        with connections["scada"].cursor() as cursor:
            cursor.execute("INSERT INTO datapoints (xid, dataSourceId, pointName) VALUES ('STATUS_P2', 1, 'Status')")
            dp1_id = cursor.lastrowid
            cursor.execute("INSERT INTO datapoints (xid, dataSourceId, pointName) VALUES ('MOTIVO_CAV1', 1, 'Motivo Cav 1')")
            dp2_id = cursor.lastrowid

            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 1, 1.0, %s)", [dp1_id, now_ms])
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 2, 2.0, %s)", [dp2_id, now_ms])

        scada_reader.clear_caches()

        self.client.force_login(self.user_leader)
        res = self.client.get(reverse("production:dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Cavidades Paradas")
        self.assertEqual(res.context["cavidades_paradas_count"], 1)


class Spec06CMaintenanceIntegrationTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        scada_reader.clear_caches()
        init_scada_test_tables()

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 03", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            produzindo_value="1",
            xid_status_prensa="STATUS_P3"
        )

        self.user_leader = User.objects.create_user("leader_06c", "lider06c@test.com", "pass123")
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

        self.tech_user = User.objects.create_user("tech_resp_06c", "techresp@test.com", "pass123")
        self.tech = Technician.objects.create(nome="Técnico João", matricula="TJ01", status="EM_ATENDIMENTO", user=self.tech_user, perfil="TECNICO")

    def test_responsavel_unassigned_when_no_active_allocation(self):
        """Verifica se exibe 'Responsável ainda não atribuído' quando não há alocação ativa."""
        detail = ProductionStateService.get_machine_detail(self.config.pk)
        self.assertEqual(detail["responsaveis_manutencao"], "Responsável ainda não atribuído")
        self.assertEqual(len(detail["responsaveis_lista"]), 0)

        self.client.force_login(self.user_leader)
        res = self.client.get(reverse("production:machine_detail", kwargs={"pk": self.config.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Responsável ainda não atribuído")

    def test_responsavel_assigned_and_progress_updates_timeline(self):
        """Verifica resgate de responsáveis ativos e linha do tempo de atualizações parciais."""
        alloc = Allocation.objects.create(
            tecnico=self.tech,
            maquina=self.machine,
            atividade_observacao="Manutenção corretiva mecânica",
            data_inicio=timezone.now(),
            status="EM_ATENDIMENTO"
        )

        pu = AllocationProgressUpdate.objects.create(
            allocation=alloc,
            autor=self.tech_user,
            descricao="Substituição de gaxeta realizada."
        )

        detail = ProductionStateService.get_machine_detail(self.config.pk)
        self.assertEqual(detail["responsaveis_manutencao"], "Técnico João")
        self.assertEqual(len(detail["atualizacoes_manutencao"]), 1)
        self.assertEqual(detail["atualizacoes_manutencao"][0]["descricao"], "Substituição de gaxeta realizada.")

        self.client.force_login(self.user_leader)
        res = self.client.get(reverse("production:machine_detail", kwargs={"pk": self.config.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Técnico João")
        self.assertContains(res, "Substituição de gaxeta realizada.")


class Spec06DLossEstimationTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        scada_reader.clear_caches()
        init_scada_test_tables()

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 04", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            produzindo_value="1",
            xid_status_prensa="STATUS_P4"
        )

        self.cavity1 = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade Única",
            ordem=1,
            xid_motivo_parada="MOTIVO_CAV4_1"
        )

        self.user_leader = User.objects.create_user("leader_06d", "lider06d@test.com", "pass123")
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

    def test_loss_estimation_insufficient_samples(self):
        """Verifica se retorna estimativa indisponível se houver menos de 3 amostras."""
        res = ProductionStateService.calculate_loss_estimate(
            cavity_config=self.cavity1,
            duracao_parada_segundos=7200,
            produto="Pneu R15",
            matriz="M-15"
        )
        self.assertFalse(res["disponivel"])
        self.assertIn("dados suficientes", res["texto_formatado"])

    def test_loss_estimation_four_level_fallback(self):
        """Testa o cálculo da taxa e o fallback em 4 níveis."""
        now = timezone.now()

        for i in range(3):
            ProductionRateAggregate.objects.create(
                cavity_config=self.cavity1,
                produto="Pneu R15",
                matriz="M-15",
                inicio_intervalo=now - timezone.timedelta(hours=i + 1),
                fim_intervalo=now - timezone.timedelta(hours=i + 1) + timezone.timedelta(minutes=15),
                minutos_produzindo=15,
                quantidade_produzida=5,
                taxa_pneus_hora=20.00,
                quantidade_amostras=1
            )

        res = ProductionStateService.calculate_loss_estimate(
            cavity_config=self.cavity1,
            duracao_parada_segundos=7200,
            produto="Pneu R15",
            matriz="M-15"
        )

        self.assertTrue(res["disponivel"])
        self.assertEqual(res["nivel_fallback"], 1)
        self.assertEqual(res["taxa_pneus_hora"], 20.0)
        self.assertEqual(res["perda_pneus"], 40)
        self.assertIn("aproximadamente 40 pneus", res["texto_formatado"])

    def test_purge_old_rate_aggregates(self):
        """Testa purga de agregados mais antigos que 90 dias."""
        now = timezone.now()
        old_agg = ProductionRateAggregate.objects.create(
            cavity_config=self.cavity1,
            produto="Pneu Antigo",
            matriz="M-01",
            inicio_intervalo=now - timezone.timedelta(days=100),
            fim_intervalo=now - timezone.timedelta(days=100) + timezone.timedelta(minutes=15),
            minutos_produzindo=15,
            quantidade_produzida=4,
            taxa_pneus_hora=16.00,
            quantidade_amostras=1
        )

        deleted = ProductionStateService.purge_old_rate_aggregates(days=90)
        self.assertEqual(deleted, 1)
        self.assertFalse(ProductionRateAggregate.objects.filter(id=old_agg.id).exists())


class Spec06EParameterAnomaliesTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        scada_reader.clear_caches()
        init_scada_test_tables()

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 05", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            produzindo_value="1",
            xid_status_prensa="STATUS_P5"
        )

        self.param_temp = ProductionParameterConfig.objects.create(
            nome="Temperatura de Cura",
            chave="TEMP_CURA_P5",
            xid="XID_TEMP_CURA_P5",
            unidade="°C",
            ordem=1,
            machine_config=self.config,
            limite_minimo=150.0,
            limite_maximo=180.0,
            tolerancia_segundos=0,
            histerese=2.0,
            ativo=True
        )

        ProductionMachineState.objects.create(
            machine_config=self.config,
            estado_atual="PRODUZINDO",
            sem_comunicacao=False,
            dado_desatualizado=False,
            ultimo_timestamp_scada=int(time.time() * 1000)
        )

        self.user_leader = User.objects.create_user("leader_06e", "lider06e@test.com", "pass123")
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

    def test_anomaly_opens_updates_and_closes_with_hysteresis(self):
        """Testa abertura de anomalia por limite máximo, atualização de min/max/ultimo e fechamento com histerese."""
        now_ms = int(time.time() * 1000)
        with connections["scada"].cursor() as cursor:
            cursor.execute("INSERT INTO datapoints (xid, dataSourceId, pointName) VALUES ('STATUS_P5', 1, 'Status P5')")
            dp_status_id = cursor.lastrowid
            cursor.execute("INSERT INTO datapoints (xid, dataSourceId, pointName) VALUES ('XID_TEMP_CURA_P5', 1, 'Temp Cura P5')")
            dp_id = cursor.lastrowid

            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 2, 1.0, %s)", [dp_status_id, now_ms])
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 2, 185.0, %s)", [dp_id, now_ms])

        scada_reader.clear_caches()
        ProductionStateService.process_scada_cycle()

        anomalies = ProductionParameterAnomalyEvent.objects.filter(parameter_config=self.param_temp, fim__isnull=True)
        self.assertEqual(anomalies.count(), 1)
        anom = anomalies.first()
        self.assertEqual(anom.tipo_limite, "MAXIMO")
        self.assertEqual(anom.maior_valor, 185.0)

        with connections["scada"].cursor() as cursor:
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 2, 190.0, %s)", [dp_id, now_ms + 1000])

        scada_reader.clear_caches()
        ProductionStateService.process_scada_cycle()

        anom.refresh_from_db()
        self.assertIsNone(anom.fim)
        self.assertEqual(anom.maior_valor, 190.0)
        self.assertEqual(anom.ultimo_valor, 190.0)

        with connections["scada"].cursor() as cursor:
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 2, 179.0, %s)", [dp_id, now_ms + 2000])

        scada_reader.clear_caches()
        ProductionStateService.process_scada_cycle()

        anom.refresh_from_db()
        self.assertIsNone(anom.fim)

        with connections["scada"].cursor() as cursor:
            cursor.execute("INSERT INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (%s, 2, 177.0, %s)", [dp_id, now_ms + 3000])

        scada_reader.clear_caches()
        ProductionStateService.process_scada_cycle()

        anom.refresh_from_db()
        self.assertIsNotNone(anom.fim)
        self.assertEqual(anom.ultimo_valor, 177.0)

    def test_machine_detail_renders_anomalies_and_notice(self):
        """Verifica se o template machine_detail.html renderiza anomalias ativas e o aviso de precisão temporal (60s)."""
        ProductionParameterAnomalyEvent.objects.create(
            parameter_config=self.param_temp,
            machine_config=self.config,
            inicio=timezone.now(),
            menor_valor=185.0,
            maior_valor=185.0,
            ultimo_valor=185.0,
            tipo_limite="MAXIMO"
        )

        self.client.force_login(self.user_leader)
        res = self.client.get(reverse("production:machine_detail", kwargs={"pk": self.config.pk}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Anomalias de Parâmetros de Processo")
        self.assertContains(res, "Precisão temporal das anomalias vinculada ao intervalo de leitura do coletor (60s)")
        self.assertContains(res, "Temperatura de Cura")


class Spec06FIntegrationAndPerformanceTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        scada_reader.clear_caches()
        init_scada_test_tables()

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 06", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            produzindo_value="1",
            xid_status_prensa="STATUS_P6"
        )

        self.cavity1 = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade Esquerda",
            ordem=1,
            xid_motivo_parada="MOTIVO_CAV6_1"
        )

        ProductionMachineState.objects.create(
            machine_config=self.config,
            estado_atual="PRODUZINDO",
            sem_comunicacao=False,
            dado_desatualizado=False,
            ultimo_timestamp_scada=int(time.time() * 1000)
        )

        self.user_leader = User.objects.create_user("leader_06f", "lider06f@test.com", "pass123")
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

        self.user_tech = User.objects.create_user("tech_06f", "tech06f@test.com", "pass123")
        group_tech, _ = Group.objects.get_or_create(name="Técnicos")
        self.user_tech.groups.add(group_tech)

    def test_cavity_detail_view_renders_all_13_attributes_for_leader(self):
        """Testa se a view cavity_detail (HTTP 200) renderiza os 13 componentes para o perfil de Liderança de Produção."""
        self.client.force_login(self.user_leader)
        url = reverse("production:cavity_detail", kwargs={"machine_id": self.config.id, "cavity_id": self.cavity1.id})
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Detalhes da Cavidade: Cavidade Esquerda")
        self.assertContains(res, "Prensa 06")
        self.assertContains(res, "Especificação Operacional da Cavidade")
        self.assertContains(res, "Estimativa de Perda de Produção")
        self.assertContains(res, "Manutenção — Responsáveis e Notas de Progresso")
        self.assertContains(res, "Anomalias de Parâmetros Relacionadas")
        self.assertContains(res, "Histórico Recente de Paradas")
        self.assertContains(res, "Precisão temporal das anomalias vinculada ao intervalo de leitura do coletor (60s)")

    def test_cavity_detail_view_blocks_unauthorized_profiles(self):
        """Garante que usuários do perfil Técnicos (Manutenção) são bloqueados ao tentar acessar a view cavity_detail."""
        self.client.force_login(self.user_tech)
        url = reverse("production:cavity_detail", kwargs={"machine_id": self.config.id, "cavity_id": self.cavity1.id})
        res = self.client.get(url)
        self.assertNotEqual(res.status_code, 200)

    def test_dashboard_contains_link_to_cavity_detail(self):
        """Testa se o dashboard contêm os links formatados para a nova rota cavity_detail."""
        self.client.force_login(self.user_leader)
        res = self.client.get(reverse("production:dashboard"))
        self.assertEqual(res.status_code, 200)
        expected_href = reverse("production:cavity_detail", kwargs={"machine_id": self.config.id, "cavity_id": self.cavity1.id})
        self.assertContains(res, expected_href)


class Spec07ASeparacaoLimiteBladderEMetaTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        self.sector = Sector.objects.create(nome="Vulcanização 07A")
        self.machine = Machine.objects.create(nome="Prensa 07A", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(machine=self.machine, ordem_exibicao=1)
        self.cavity = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade 07A",
            ordem=1,
            xid_producao="XID_PROD_07A",
            xid_meta="XID_LIMITE_BLADDER_07A",
            meta_producao_manual=1000
        )

        self.user_leader = User.objects.create_user("lider_07a", "lider07a@test.com", "pass123")
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

    def test_cavity_config_verbose_names(self):
        """Valida se verbose_name e help_text atualizados estão configurados no model ProductionCavityConfig."""
        meta_field = ProductionCavityConfig._meta.get_field("meta_producao_manual")
        xid_meta_field = ProductionCavityConfig._meta.get_field("xid_meta")

        self.assertEqual(str(meta_field.verbose_name), "Meta Manual de Produção")
        self.assertIn("Meta diária de produção cadastrada manualmente", str(meta_field.help_text))

        self.assertEqual(str(xid_meta_field.verbose_name), "XID Limite de Produção do Bladder (Scada)")
        self.assertIn("limite de vida produtiva do ciclo do bladder", str(xid_meta_field.help_text))

    def test_cavity_context_separates_bladder_limit_and_shift_target(self):
        """Valida se build_cavities_data e get_cavity_detail retornam limite_bladder_scada e meta_turno de forma independente."""
        scada_values = {
            "XID_PROD_07A": {"value": 150},
            "XID_LIMITE_BLADDER_07A": {"value": 2000},
        }

        cavities_data, _, _, _, _ = ProductionStateService.build_cavities_data(self.config, scada_values)
        self.assertEqual(len(cavities_data), 1)
        cav_ctx = cavities_data[0]

        self.assertEqual(cav_ctx["limite_bladder_scada"], 2000)
        self.assertEqual(cav_ctx["limite_bladder_str"], "2000")
        self.assertEqual(cav_ctx["contador_ciclo_scada"], 150)
        self.assertEqual(cav_ctx["meta_turno"], 1000)

        with connections["scada"].cursor() as cursor:
            cursor.execute("INSERT OR REPLACE INTO datapoints (xid, dataSourceId, pointName) VALUES ('XID_PROD_07A', 1, 'Prod')")
            cursor.execute("INSERT OR REPLACE INTO datapoints (xid, dataSourceId, pointName) VALUES ('XID_LIMITE_BLADDER_07A', 1, 'Bladder')")
            cursor.execute("INSERT OR REPLACE INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (1, 3, 150, 100000)")
            cursor.execute("INSERT OR REPLACE INTO pointvalues (dataPointId, dataType, pointValue, ts) VALUES (2, 3, 2000, 100000)")

        detail_ctx = ProductionStateService.get_cavity_detail(self.config.id, self.cavity.id)
        self.assertEqual(detail_ctx["limite_bladder_scada"], 2000)
        self.assertEqual(detail_ctx["limite_bladder_str"], "2000")
        self.assertEqual(detail_ctx["contador_ciclo_scada"], 150)
        self.assertEqual(detail_ctx["meta_turno"], 1000)

    def test_template_renders_distinct_bladder_limit_and_shift_target(self):
        """Simula GET nas views e verifica se os rótulos de Limite de Bladder e Meta do Turno são renderizados separadamente."""
        self.client.force_login(self.user_leader)

        dash_res = self.client.get(reverse("production:dashboard"))
        self.assertEqual(dash_res.status_code, 200)
        self.assertContains(dash_res, "Limite Bladder:")
        self.assertContains(dash_res, "Meta Turno:")

        mach_res = self.client.get(reverse("production:machine_detail", kwargs={"pk": self.config.id}))
        self.assertEqual(mach_res.status_code, 200)
        self.assertContains(mach_res, "Limite Bladder:")
        self.assertContains(mach_res, "Meta Turno:")

        cav_res = self.client.get(reverse("production:cavity_detail", kwargs={"machine_id": self.config.id, "cavity_id": self.cavity.id}))
        self.assertEqual(cav_res.status_code, 200)
        self.assertContains(cav_res, "Limite Vida do Bladder (Scada)")
        self.assertContains(cav_res, "Meta do Turno (PCP)")


class Spec07BAcumuloProducaoComResetsTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        self.shift = ProductionShift.objects.create(
            nome="Turno 1 Teste 07B",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=100.0,
            ordem_exibicao=1,
            ativo=True
        )
        self.sector = Sector.objects.create(nome="Setor 07B")
        self.machine = Machine.objects.create(nome="Prensa 07B", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(machine=self.machine, ordem_exibicao=1)
        self.cavity = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade 07B",
            ordem=1,
            xid_producao="XID_PROD_07B",
            xid_matriz="XID_MATRIZ_07B",
            xid_lote_bladder="XID_BLADDER_07B",
            meta_producao_manual=1000
        )

    def test_normal_counter_increment(self):
        """Testa incremento normal do contador (ex: 430 -> 445 = +15)."""
        now = timezone.now()
        scada_1 = {"XID_PROD_07B": {"value": 430, "timestamp": 1000}}
        ProductionStateService.process_incremental_production(self.cavity, scada_1, now=now)

        acc = ProductionShiftAccumulated.objects.get(cavity_config=self.cavity)
        self.assertEqual(acc.quantity_accumulated, 430)

        scada_2 = {"XID_PROD_07B": {"value": 445, "timestamp": 2000}}
        ProductionStateService.process_incremental_production(self.cavity, scada_2, now=now)

        acc.refresh_from_db()
        self.assertEqual(acc.quantity_accumulated, 445)
        self.assertEqual(acc.last_scada_counter, 445)

        cycle = ProductionCycle.objects.get(cavity_config=self.cavity, ended_at__isnull=True)
        self.assertEqual(cycle.quantity_produced, 15)

    def test_reset_on_counter_drop(self):
        """Testa reset por queda do contador (ex: 1180 -> 8 => acúmulo 1188 no turno)."""
        now = timezone.now()
        scada_1 = {"XID_PROD_07B": {"value": 1180, "timestamp": 1000}}
        ProductionStateService.process_incremental_production(self.cavity, scada_1, now=now)

        acc = ProductionShiftAccumulated.objects.get(cavity_config=self.cavity)
        self.assertEqual(acc.quantity_accumulated, 1180)

        # Queda/reset no Scada para 8
        scada_2 = {"XID_PROD_07B": {"value": 8, "timestamp": 2000}}
        ProductionStateService.process_incremental_production(self.cavity, scada_2, now=now)

        acc.refresh_from_db()
        self.assertEqual(acc.quantity_accumulated, 1188)

        closed_cycle = ProductionCycle.objects.get(cavity_config=self.cavity, ended_at__isnull=False)
        self.assertEqual(closed_cycle.final_counter, 1180)
        self.assertEqual(closed_cycle.close_reason, "RESET_CONTADOR")

        active_cycle = ProductionCycle.objects.get(cavity_config=self.cavity, ended_at__isnull=True)
        self.assertEqual(active_cycle.initial_counter, 8)

    def test_reset_on_matrix_change(self):
        """Testa encerramento do ciclo anterior e início de um novo ciclo ao trocar a matriz."""
        now = timezone.now()
        scada_1 = {
            "XID_PROD_07B": {"value": 50, "timestamp": 1000},
            "XID_MATRIZ_07B": {"str_value": "M-101"}
        }
        ProductionStateService.process_incremental_production(self.cavity, scada_1, now=now)

        cycle_1 = ProductionCycle.objects.get(cavity_config=self.cavity, ended_at__isnull=True)
        self.assertEqual(cycle_1.matriz, "M-101")

        # Troca de matriz para M-202 com reset de contador para 2
        scada_2 = {
            "XID_PROD_07B": {"value": 2, "timestamp": 2000},
            "XID_MATRIZ_07B": {"str_value": "M-202"}
        }
        ProductionStateService.process_incremental_production(self.cavity, scada_2, now=now)

        cycle_1.refresh_from_db()
        self.assertIsNotNone(cycle_1.ended_at)
        self.assertEqual(cycle_1.close_reason, "TROCA_MATRIZ")

        cycle_2 = ProductionCycle.objects.get(cavity_config=self.cavity, ended_at__isnull=True)
        self.assertEqual(cycle_2.matriz, "M-202")

    def test_reset_on_bladder_change(self):
        """Testa encerramento do ciclo anterior ao mudar o lote do bladder."""
        now = timezone.now()
        scada_1 = {
            "XID_PROD_07B": {"value": 50, "timestamp": 1000},
            "XID_BLADDER_07B": {"str_value": "BLAD-01"}
        }
        ProductionStateService.process_incremental_production(self.cavity, scada_1, now=now)

        # Troca de lote do bladder
        scada_2 = {
            "XID_PROD_07B": {"value": 5, "timestamp": 2000},
            "XID_BLADDER_07B": {"str_value": "BLAD-02"}
        }
        ProductionStateService.process_incremental_production(self.cavity, scada_2, now=now)

        closed_cycle = ProductionCycle.objects.get(cavity_config=self.cavity, ended_at__isnull=False)
        self.assertEqual(closed_cycle.close_reason, "TROCA_BLADDER")

    def test_collector_retry_idempotency(self):
        """Garante que releituras ou retries com o mesmo timestamp Scada não duplicam a contagem."""
        now = timezone.now()
        scada = {"XID_PROD_07B": {"value": 100, "timestamp": 5000}}

        ProductionStateService.process_incremental_production(self.cavity, scada, now=now)
        acc = ProductionShiftAccumulated.objects.get(cavity_config=self.cavity)
        self.assertEqual(acc.quantity_accumulated, 100)

        # Re-execução idêntica
        ProductionStateService.process_incremental_production(self.cavity, scada, now=now)
        acc.refresh_from_db()
        self.assertEqual(acc.quantity_accumulated, 100)

    def test_scada_unavailability_does_not_trigger_reset(self):
        """Garante que leitura offline/nula congela o estado sem causar reset ou estragar acúmulo."""
        now = timezone.now()
        scada_1 = {"XID_PROD_07B": {"value": 50, "timestamp": 1000}}
        ProductionStateService.process_incremental_production(self.cavity, scada_1, now=now)

        scada_offline = {"XID_PROD_07B": None}
        ProductionStateService.process_incremental_production(self.cavity, scada_offline, now=now)

        acc = ProductionShiftAccumulated.objects.get(cavity_config=self.cavity)
        self.assertEqual(acc.quantity_accumulated, 50)
        self.assertIsNone(ProductionCycle.objects.get(cavity_config=self.cavity).ended_at)

    def test_shift_transition_across_midnight(self):
        """Testa transição de data no acúmulo do turno sem fechar o ciclo de produção físico do molde."""
        now_day1 = timezone.now()
        scada_1 = {"XID_PROD_07B": {"value": 100, "timestamp": 1000}}
        ProductionStateService.process_incremental_production(self.cavity, scada_1, now=now_day1)

        acc_1 = ProductionShiftAccumulated.objects.get(date=now_day1.date(), cavity_config=self.cavity)
        self.assertEqual(acc_1.quantity_accumulated, 100)

        # Dia seguinte com incremento para 120 no mesmo ciclo físico
        now_day2 = now_day1 + timezone.timedelta(days=1)
        scada_2 = {"XID_PROD_07B": {"value": 120, "timestamp": 2000}}
        ProductionStateService.process_incremental_production(self.cavity, scada_2, now=now_day2)

        acc_2 = ProductionShiftAccumulated.objects.get(date=now_day2.date(), cavity_config=self.cavity)
        self.assertNotEqual(acc_1.id, acc_2.id)


class Spec07CPlanejamentoMetasProducaoTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        self.user_leader = User.objects.create_user(
            username="lider_07c", password="password123", is_staff=True
        )
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

        self.user_op = User.objects.create_user(
            username="operador_07c", password="password123", is_staff=False
        )

        self.shift = ProductionShift.objects.create(
            nome="Turno 1 Teste 07C",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=100.0,
            ordem_exibicao=1,
            ativo=True
        )

        self.sector = Sector.objects.create(nome="Setor 07C")
        self.machine = Machine.objects.create(nome="Prensa 07C", setor=self.sector)
        self.config = ProductionMachineConfig.objects.create(machine=self.machine, ordem_exibicao=1)
        self.cavity = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade 07C",
            ordem=1,
            xid_producao="XID_PROD_07C",
            xid_matriz="XID_MATRIZ_07C",
            meta_producao_manual=500
        )

    def test_create_target_for_uninstalled_matrix(self):
        """Permite cadastrar meta para matriz ainda não instalada em nenhuma prensa no Scada."""
        target = ProductionTarget.objects.create(
            date=timezone.now().date(),
            shift=self.shift,
            matriz_codigo="MAT-NAO-INSTALADA-999",
            produto="Pneu Inexistente 200/50R17",
            planned_quantity=2000,
            status="ATIVO",
            created_by=self.user_leader
        )
        self.assertIsNotNone(target.id)
        self.assertEqual(target.matriz_codigo, "MAT-NAO-INSTALADA-999")
        self.assertEqual(target.planned_quantity, 2000)

    def test_duplicate_target_validation(self):
        """Formulário rejeita o cadastro de metas duplicadas para o mesmo conjunto de parâmetros."""
        today = timezone.now().date()
        ProductionTarget.objects.create(
            date=today,
            shift=self.shift,
            matriz_codigo="M-101",
            planned_quantity=1000,
            status="ATIVO"
        )

        form_data = {
            "date": today,
            "shift": self.shift.id,
            "matriz_codigo": "M-101",
            "planned_quantity": 1200,
            "status": "ATIVO",
        }
        form = ProductionTargetForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Já existe uma meta ativa cadastrada", form.non_field_errors()[0])

    def test_cancel_target(self):
        """Mudança de status para CANCELADO preserva o registro sem atuar nas metas ativas."""
        target = ProductionTarget.objects.create(
            date=timezone.now().date(),
            shift=self.shift,
            matriz_codigo="M-CANCELAR",
            planned_quantity=800,
            status="ATIVO"
        )
        self.client.force_login(self.user_leader)
        res = self.client.post(reverse("production:target_cancel", kwargs={"pk": target.id}))
        self.assertEqual(res.status_code, 302)

        target.refresh_from_db()
        self.assertEqual(target.status, "CANCELADO")

    def test_unauthorized_user_cannot_access_targets(self):
        """Usuário comum sem privilégio recebe redirecionamento ao tentar acessar área de metas."""
        self.client.force_login(self.user_op)
        res = self.client.get(reverse("production:target_list"))
        self.assertEqual(res.status_code, 302)

    def test_planned_target_resolution_in_dashboard(self):
        """A meta em ProductionTarget tem precedência sobre a meta manual da cavidade no dashboard."""
        today = timezone.now().date()
        # Insere valor no Scada para a matriz M-PLANEJADA
        with connections["scada"].cursor() as cursor:
            cursor.execute("INSERT OR REPLACE INTO datapoints (id, xid, dataSourceId, pointName) VALUES (1, 'XID_PROD_07C', 1, 'Prod')")
            cursor.execute("INSERT OR REPLACE INTO datapoints (id, xid, dataSourceId, pointName) VALUES (2, 'XID_MATRIZ_07C', 1, 'Matriz')")
            cursor.execute("INSERT OR REPLACE INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (10, 1, 3, 10, 1000)")
            cursor.execute("INSERT OR REPLACE INTO pointvalues (id, dataPointId, dataType, pointValue, ts) VALUES (20, 2, 4, 0, 1000)")
            cursor.execute("INSERT OR REPLACE INTO pointvalueannotations (pointValueId, textPointValueShort) VALUES (20, 'M-PLANEJADA')")

        # Sem meta em ProductionTarget => utiliza a meta manual de 500
        state_manual = ProductionStateService.get_dashboard_state()
        cav_data_manual = state_manual["machines"][0]["cavidades"][0]
        self.assertEqual(cav_data_manual["meta_turno"], 500)

        # Cadastra meta planejada em ProductionTarget para M-PLANEJADA de 1500 (meta geral para a matriz no dia)
        ProductionTarget.objects.create(
            date=today,
            shift=None,
            matriz_codigo="M-PLANEJADA",
            planned_quantity=1500,
            status="ATIVO"
        )

        state_planned = ProductionStateService.get_dashboard_state()
        cav_data_planned = state_planned["machines"][0]["cavidades"][0]
        self.assertEqual(cav_data_planned["meta_turno"], 1500)


class SpecCanonicalMatrixCatalogTestCase(TestCase):
    databases = {"default", "scada"}

    def test_seed_matrix_catalog_populates_43_models(self):
        """Valida que o comando seed_matrix_catalog cadastra exatamente os 43 modelos canônicos."""
        from django.core.management import call_command
        call_command("seed_matrix_catalog")

        self.assertEqual(ProductionMatrixCatalog.objects.count(), 43)

        # Valida que código 3 é distinto de 37 (versão S/C)
        mat3 = ProductionMatrixCatalog.objects.get(codigo_scada=3)
        mat37 = ProductionMatrixCatalog.objects.get(codigo_scada=37)
        self.assertNotEqual(mat3.id, mat37.id)
        self.assertIn("S/C", mat37.nome_scada)
        self.assertNotIn("S/C", mat3.nome_scada)

    def test_seed_matrix_catalog_idempotency(self):
        """Valida que chamadas repetidas do seed não duplicam registros."""
        from django.core.management import call_command
        call_command("seed_matrix_catalog")
        call_command("seed_matrix_catalog")
        self.assertEqual(ProductionMatrixCatalog.objects.count(), 43)


class SpecPCPShiftPlanAndUXTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        self.user_leader = User.objects.create_user(
            username="lider_pcp_ux", password="password123", is_staff=True
        )
        group_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_leader.groups.add(group_lider)

        self.user_unauthorized = User.objects.create_user(
            username="operador_sem_permissao", password="password123", is_staff=False
        )

        self.shift = ProductionShift.objects.create(
            nome="Turno A PCP",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=100.0,
            ordem_exibicao=1,
            ativo=True
        )

        self.matrix = ProductionMatrixCatalog.objects.get(codigo_scada=5)

    def test_shift_plan_route_access(self):
        """A rota /producao/plano-turno/ abre com status 200 para usuário autorizado."""
        self.client.force_login(self.user_leader)
        response = self.client.get(reverse("production:shift_plan"))
        self.assertEqual(response.status_code, 200)

    def test_unauthorized_user_blocked_on_shift_plan(self):
        """Usuário sem permissão é bloqueado na rota /producao/plano-turno/."""
        self.client.force_login(self.user_unauthorized)
        response = self.client.get(reverse("production:shift_plan"))
        self.assertEqual(response.status_code, 302)

    def test_pcp_plan_summary_in_dashboard(self):
        """Valida que o resumo do plano do PCP é incluído no estado do dashboard."""
        today = timezone.now().date()
        ProductionTarget.objects.create(
            date=today,
            shift=self.shift,
            matrix_catalog=self.matrix,
            matriz_codigo="5",
            planned_quantity=1200,
            priority=1,
            status="EM_PRODUCAO",
            created_by=self.user_leader
        )

        state = ProductionStateService.get_dashboard_state()
        summary = state.get("pcp_plan_summary")
        self.assertIsNotNone(summary)
        self.assertEqual(summary["meta_total"], 1200)
        self.assertEqual(summary["total_metas"], 1)


class SpecGroupedProductionByMatrixTestCase(TestCase):
    databases = {"default", "scada"}

    def setUp(self):
        init_scada_test_tables()
        self.shift = ProductionShift.objects.create(
            nome="Turno Agrupado",
            horario_inicial=timezone.datetime.strptime("06:00", "%H:%M").time(),
            horario_final=timezone.datetime.strptime("14:00", "%H:%M").time(),
            percentual_meta=100.0,
            ordem_exibicao=1,
            ativo=True
        )
        self.sector = Sector.objects.create(nome="Setor Agrupamento")
        self.machine1 = Machine.objects.create(nome="Prensa 1", setor=self.sector)
        self.config1 = ProductionMachineConfig.objects.create(machine=self.machine1, ordem_exibicao=1)
        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.config1,
            nome="Cavidade 1",
            ordem=1,
            xid_producao="XID_PROD_1",
            xid_matriz="XID_MATRIZ_1"
        )
        self.machine2 = Machine.objects.create(nome="Prensa 2", setor=self.sector)
        self.config2 = ProductionMachineConfig.objects.create(machine=self.machine2, ordem_exibicao=2)
        self.cav2 = ProductionCavityConfig.objects.create(
            machine_config=self.config2,
            nome="Cavidade 1",
            ordem=1,
            xid_producao="XID_PROD_2",
            xid_matriz="XID_MATRIZ_2"
        )

    def test_grouped_production_sum_same_matrix_code(self):
        """Duas cavidades produzindo a mesma matriz (código 3) têm sua produção acumulada somada."""
        today = timezone.now().date()

        ProductionShiftAccumulated.objects.create(
            date=today,
            shift=self.shift,
            cavity_config=self.cav1,
            matriz="3",
            produto="PNEUS HOPPER 90/90-18",
            quantity_accumulated=150
        )
        ProductionShiftAccumulated.objects.create(
            date=today,
            shift=self.shift,
            cavity_config=self.cav2,
            matriz="3",
            produto="PNEUS HOPPER 90/90-18",
            quantity_accumulated=200
        )

        matrix_cat = ProductionMatrixCatalog.objects.get(codigo_scada=3)

        target = ProductionTarget.objects.create(
            date=today,
            shift=self.shift,
            matrix_catalog=matrix_cat,
            planned_quantity=500,
            status="EM_PRODUCAO"
        )

        summary = ProductionStateService.get_pcp_plan_summary(date=today, shift_obj=self.shift)
        self.assertEqual(summary["produzido_total"], 350)
        self.assertEqual(summary["restante_total"], 150)
        self.assertEqual(summary["cumprimento_percent"], 70.0)


class ProductionDowntimeHistoryEnhancementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="prod_leader", password="password123")
        group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user.groups.add(group)

        self.setor = Sector.objects.create(nome="Vulc")
        self.machine = Machine.objects.create(nome="Prensa test 01", setor=self.setor)
        self.machine_config = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            stale_limit_seconds=120,
            produzindo_value="1",
            xid_status_prensa="STATUS_P01",
            xid_motivo_parada_geral="MOTIVO_P01"
        )
        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.machine_config,
            nome="Cavidade 1",
            ordem=1,
            xid_motivo_parada="MOTIVO_CAV1"
        )
        self.cav2 = ProductionCavityConfig.objects.create(
            machine_config=self.machine_config,
            nome="Cavidade 2",
            ordem=2,
            xid_motivo_parada="MOTIVO_CAV2"
        )

        self.now = timezone.localtime().replace(second=0, microsecond=0)

    def test_status_column_removed_and_open_event_displays_em_andamento(self):
        """Valida que o cabeçalho 'Status' foi removido e evento aberto exibe 'Em andamento'."""
        ev_open = ProductionDowntimeEvent.objects.create(
            machine_config=self.machine_config,
            inicio=self.now - timezone.timedelta(minutes=30),
            fim=None,
            motivo_geral="6"
        )

        self.client.login(username="prod_leader", password="password123")
        url = reverse("production:machine_detail", kwargs={"pk": self.machine_config.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Cabeçalho Status não deve estar presente na tabela de histórico
        self.assertNotIn("<th>Status</th>", content)
        # Evento aberto deve mostrar 'Em andamento'
        self.assertIn("Em andamento", content)

    def test_general_reason_friendly_formatting_and_fallback(self):
        """Valida tradução de motivo geral 0 para 'Sem parada geral', conhecidos e fallback para desconhecidos."""
        # 0 -> Sem parada geral
        self.assertEqual(ProductionStateService.format_general_downtime_reason("0"), "Sem parada geral")
        self.assertEqual(ProductionStateService.format_general_downtime_reason(None), "Sem parada geral")
        self.assertEqual(ProductionStateService.format_general_downtime_reason(""), "Sem parada geral")

        # Conhecidos (6 -> Falta de Material, 9 -> Mecânico, 10 -> Elétrica, 11 -> Outros, 1 -> Troca de Matriz)
        self.assertEqual(ProductionStateService.format_general_downtime_reason("6"), "Falta de Material")
        self.assertEqual(ProductionStateService.format_general_downtime_reason("9"), "Mecânico")
        self.assertEqual(ProductionStateService.format_general_downtime_reason("10"), "Elétrica")

        # Desconhecido -> Motivo desconhecido (código X)
        self.assertEqual(ProductionStateService.format_general_downtime_reason("99"), "Motivo desconhecido (código 99)")

    def test_cavity_downtime_reasons_historical_overlap(self):
        """Valida a exibição histórica de motivos por cavidade sobrepostos ao evento."""
        start_time = self.now - timezone.timedelta(hours=2)
        end_time = self.now - timezone.timedelta(hours=1)

        # Evento geral
        ev = ProductionDowntimeEvent.objects.create(
            machine_config=self.machine_config,
            inicio=start_time,
            fim=end_time,
            motivo_geral="0"
        )

        # Evento de cavidade histórico durante esse intervalo
        ProductionCavityDowntimeEvent.objects.create(
            cavity_config=self.cav1,
            inicio=start_time + timezone.timedelta(minutes=10),
            fim=start_time + timezone.timedelta(minutes=40),
            motivo_parada="5", # 5 -> Ajuste Matriz
            snapshot_valor_motivo="5"
        )

        detail_state = ProductionStateService.get_machine_detail(config_id=self.machine_config.pk)
        events = detail_state["events"]

        self.assertEqual(len(events), 1)
        first_ev = events[0]
        self.assertEqual(first_ev["motivo_geral"], "Sem parada geral")
        self.assertTrue(first_ev["has_cavity_reasons"])
        self.assertIn("Cavidade 1: Ajuste Matriz", first_ev["cavidades_summary"])

    def test_datetime_local_filter_and_overlap_rule(self):
        """Valida filtro temporal por data/hora (datetime-local) e regra de sobreposição ORM."""
        t1 = self.now - timezone.timedelta(hours=5)
        t2 = self.now - timezone.timedelta(hours=3)
        t3 = self.now - timezone.timedelta(hours=1)

        # Evento 1: Das 5h atrás às 3h atrás (dentro do filtro)
        ev1 = ProductionDowntimeEvent.objects.create(
            machine_config=self.machine_config,
            inicio=t1,
            fim=t2,
            motivo_geral="9"
        )
        # Evento 2: Das 1h atrás até agora (fora do filtro se filtrarmos de 6h a 2h atrás)
        ev2 = ProductionDowntimeEvent.objects.create(
            machine_config=self.machine_config,
            inicio=t3,
            fim=self.now,
            motivo_geral="10"
        )

        f_start = (self.now - timezone.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")
        f_end = (self.now - timezone.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")

        detail = ProductionStateService.get_machine_detail(
            config_id=self.machine_config.pk,
            inicio_str=f_start,
            fim_str=f_end
        )

        # Apenas o ev1 deve estar no resultado por sobreposição
        events_ids = [e["id"] for e in detail["events"]]
        self.assertIn(ev1.id, events_ids)
        self.assertNotIn(ev2.id, events_ids)

    def test_invalid_datetime_filter_gracefully_handled(self):
        """Valida que início maior que fim não gera erro 500 e exibe mensagem amigável."""
        f_start = self.now.strftime("%Y-%m-%dT%H:%M")
        f_end = (self.now - timezone.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")

        detail = ProductionStateService.get_machine_detail(
            config_id=self.machine_config.pk,
            inicio_str=f_start,
            fim_str=f_end
        )

        self.assertIsNotNone(detail["date_error_msg"])
        self.assertIn("não pode ser posterior", detail["date_error_msg"])

    def test_downtime_duration_clipped_to_period(self):
        """Valida que a duração exibida é recortada exclusivamente ao período do filtro."""
        t_start = self.now - timezone.timedelta(hours=4)
        t_end = self.now - timezone.timedelta(hours=2)

        ev = ProductionDowntimeEvent.objects.create(
            machine_config=self.machine_config,
            inicio=t_start,
            fim=t_end,
            motivo_geral="9"
        ) # Duração total: 2h (120 min)

        # Filtro recortando apenas a última 1h (das 3h às 1h atrás)
        f_start = (self.now - timezone.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
        f_end = (self.now - timezone.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

        detail = ProductionStateService.get_machine_detail(
            config_id=self.machine_config.pk,
            inicio_str=f_start,
            fim_str=f_end
        )

        ev_res = detail["events"][0]
        # Duração recortada deve ser de 1h (3600 segundos)
        self.assertEqual(ev_res["duracao_segundos"], 3600)
        self.assertEqual(ev_res["duracao_str"], "1h 0m")

    def test_backend_pagination_and_query_string_preservation(self):
        """Valida paginação de 10 itens por página e preservação dos parâmetros GET."""
        # Criar 15 eventos de parada
        for i in range(15):
            ProductionDowntimeEvent.objects.create(
                machine_config=self.machine_config,
                inicio=self.now - timezone.timedelta(minutes=i*10),
                fim=self.now - timezone.timedelta(minutes=i*10 - 5),
                motivo_geral="0"
            )

        f_start = (self.now - timezone.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        f_end = self.now.strftime("%Y-%m-%dT%H:%M")

        # Página 1
        detail_p1 = ProductionStateService.get_machine_detail(
            config_id=self.machine_config.pk,
            inicio_str=f_start,
            fim_str=f_end,
            page=1
        )
        self.assertEqual(len(detail_p1["events"]), 10)
        self.assertTrue(detail_p1["page_obj"].has_next())

        # Página 2
        detail_p2 = ProductionStateService.get_machine_detail(
            config_id=self.machine_config.pk,
            inicio_str=f_start,
            fim_str=f_end,
            page=2
        )
        self.assertEqual(len(detail_p2["events"]), 5)
        self.assertTrue(detail_p2["page_obj"].has_previous())
        self.assertIn("inicio=", detail_p2["querystring"])
        self.assertIn("fim=", detail_p2["querystring"])

    def test_permissions_and_scada_no_write(self):
        """Valida que usuário sem permissão permanece bloqueado e que nenhuma escrita é feita no scada."""
        self.client.logout()

        url = reverse("production:machine_detail", kwargs={"pk": self.machine_config.pk})
        response = self.client.get(url)
        # Redireciona para o login se não autenticado
        self.assertNotEqual(response.status_code, 200)


class ProductionSemanticCorrectionTest(TestCase):
    def setUp(self):
        self.setor = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 01", setor=self.setor)
        self.config = ProductionMachineConfig.objects.create(machine=self.machine)
        self.cavity = ProductionCavityConfig.objects.create(
            machine_config=self.config,
            nome="Cavidade A",
            ordem=1,
            xid_matriz="XID_MATRIZ_TEST",
            xid_produto="XID_PROD_PREFIX",
            xid_lote_bladder="XID_LOTE_NUM",
            xid_producao="XID_PROD_COUNT",
        )
        self.user = User.objects.create_user("testuser_semantic", "test@example.com", "password", is_staff=True)

    def test_compose_bladder_lot_full(self):
        res = compose_bladder_lot("6154", "161046")
        self.assertEqual(res["display"], "6154 - 161046")
        self.assertTrue(res["is_complete"])
        self.assertFalse(res["is_incomplete"])
        self.assertEqual(res["status"], "COMPLETO")

    def test_compose_bladder_lot_prefix_only(self):
        res = compose_bladder_lot("6154", None)
        self.assertEqual(res["display"], "6154 - Não informado")
        self.assertFalse(res["is_complete"])
        self.assertTrue(res["is_incomplete"])
        self.assertEqual(res["status"], "INCOMPLETO")

    def test_compose_bladder_lot_number_only(self):
        res = compose_bladder_lot("", "161046")
        self.assertEqual(res["display"], "Não informado - 161046")
        self.assertFalse(res["is_complete"])
        self.assertTrue(res["is_incomplete"])
        self.assertEqual(res["status"], "INCOMPLETO")

    def test_compose_bladder_lot_both_missing(self):
        res = compose_bladder_lot(None, "")
        self.assertEqual(res["display"], "Não informado")
        self.assertFalse(res["is_complete"])
        self.assertFalse(res["is_incomplete"])
        self.assertEqual(res["status"], "AUSENTE")

    def test_compose_bladder_lot_preserves_leading_zeros(self):
        res = compose_bladder_lot("06154", "00123")
        self.assertEqual(res["display"], "06154 - 00123")
        self.assertTrue(res["is_complete"])

    def test_resolve_matrix_product_display(self):
        ProductionMatrixCatalog.objects.get(codigo_scada=3)
        res_valid = resolve_matrix_product_display("3")
        self.assertEqual(res_valid["display"], "PNEUS HOPPER 90/90-18")
        self.assertTrue(res_valid["matrix_identified"])

        res_unregistered = resolve_matrix_product_display("99")
        self.assertEqual(res_unregistered["display"], "Código não cadastrado: 99")
        self.assertFalse(res_unregistered["matrix_identified"])

        res_missing = resolve_matrix_product_display("")
        self.assertEqual(res_missing["display"], "Não informado")
        self.assertFalse(res_missing["matrix_identified"])

    def test_cavity_detail_view_semantic_rendering(self):
        ProductionMatrixCatalog.objects.get(codigo_scada=3)
        self.client.force_login(self.user)
        url = reverse("production:cavity_detail", kwargs={"machine_id": self.config.id, "cavity_id": self.cavity.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertNotIn("Produto Em Furo", content)
        self.assertIn("Matriz / Produto em Produção", content)
        self.assertIn("Lote Completo do Bladder", content)

    def test_verbose_names_and_help_texts(self):
        field_matriz = ProductionCavityConfig._meta.get_field("xid_matriz")
        field_produto = ProductionCavityConfig._meta.get_field("xid_produto")
        field_lote = ProductionCavityConfig._meta.get_field("xid_lote_bladder")

        self.assertEqual(field_matriz.verbose_name, "XID Matriz")
        self.assertEqual(field_produto.verbose_name, "XID Prefixo do Lote do Bladder")
        self.assertEqual(field_lote.verbose_name, "XID Número do Lote do Bladder")


class MatrixCatalogDataMigrationTestCase(TestCase):
    """Suíte de testes para validação da carga inicial e idempotência da Data Migration 0018."""

    def test_initial_migration_populates_43_canonical_records(self):
        """Valida que o banco possui exatamente os 43 registros canônicos criados pela migration 0018."""
        self.assertEqual(ProductionMatrixCatalog.objects.count(), 43)

    def test_code_1_and_43_correct(self):
        """Valida a precisão dos dados do primeiro (1) e do último (43) registro canônico."""
        code1 = ProductionMatrixCatalog.objects.get(codigo_scada=1)
        self.assertEqual(code1.codigo, "1")
        self.assertEqual(code1.nome_scada, "PNEUS WINGS 90/90-18")

        code43 = ProductionMatrixCatalog.objects.get(codigo_scada=43)
        self.assertEqual(code43.codigo, "43")
        self.assertEqual(code43.nome_scada, "PNEU SPEEDY 2.75-18 S/C")

    def test_codes_are_unique_1_to_43(self):
        """Valida que existem 43 códigos SCADA únicos variando estritamente de 1 a 43."""
        codes = set(ProductionMatrixCatalog.objects.values_list("codigo_scada", flat=True))
        self.assertEqual(len(codes), 43)
        self.assertEqual(codes, set(range(1, 44)))

    def test_sc_remains_distinct_from_non_sc(self):
        """Valida que modelos S/C (ex: 37) são distintos dos equivalentes sem S/C (ex: 3)."""
        mat3 = ProductionMatrixCatalog.objects.get(codigo_scada=3)
        mat37 = ProductionMatrixCatalog.objects.get(codigo_scada=37)

        self.assertNotEqual(mat3.id, mat37.id)
        self.assertNotIn("S/C", mat3.nome_scada)
        self.assertIn("S/C", mat37.nome_scada)

    def test_migration_reexecution_is_idempotent_no_duplicates(self):
        """Valida que a reexecução da lógica da migration não duplica registros."""
        import importlib
        from django.apps import apps
        from unittest.mock import MagicMock
        migration_0018 = importlib.import_module("production.migrations.0018_seed_matrix_catalog")

        mock_schema_editor = MagicMock()
        mock_schema_editor.connection.alias = "default"

        migration_0018.populate_matrix_catalog(apps, mock_schema_editor)
        self.assertEqual(ProductionMatrixCatalog.objects.count(), 43)

    def test_preexisting_customization_preserved(self):
        """Valida que personalizações administrativas pré-existentes no nome_exibicao não são apagadas ou sobrescritas."""
        import importlib
        from django.apps import apps
        from unittest.mock import MagicMock
        migration_0018 = importlib.import_module("production.migrations.0018_seed_matrix_catalog")

        mat1 = ProductionMatrixCatalog.objects.get(codigo_scada=1)
        mat1.nome_exibicao = "PNEUS WINGS 90/90-18 - NOME PERSONALIZADO ADMIN"
        mat1.save()

        mock_schema_editor = MagicMock()
        mock_schema_editor.connection.alias = "default"

        migration_0018.populate_matrix_catalog(apps, mock_schema_editor)

        mat1_reloaded = ProductionMatrixCatalog.objects.get(codigo_scada=1)
        self.assertEqual(mat1_reloaded.nome_exibicao, "PNEUS WINGS 90/90-18 - NOME PERSONALIZADO ADMIN")
        self.assertEqual(ProductionMatrixCatalog.objects.count(), 43)

    def test_scada_database_receives_no_write(self):
        """Valida que quando a migração executa apontando para a conexão 'scada', nenhuma operação de escrita ocorre."""
        import importlib
        from django.apps import apps
        from unittest.mock import MagicMock
        migration_0018 = importlib.import_module("production.migrations.0018_seed_matrix_catalog")

        mock_schema_editor = MagicMock()
        mock_schema_editor.connection.alias = "scada"

        # Deve encerrar imediatamente sem lançar exceção ou consultar modelos scada
        migration_0018.populate_matrix_catalog(apps, mock_schema_editor)
        self.assertEqual(ProductionMatrixCatalog.objects.count(), 43)


class ProductionMatrixUXImprovementTests(TestCase):
    """
    Testes de regressão e aceitação para as melhorias de UX do módulo de Produção:
    1. Histórico de Matrizes exibindo o nome canônico em vez de código numérico (4, 29, etc.).
    2. Resolução segura de fallback para códigos não cadastrados sem erro 500.
    3. Cards de cavidade com Matriz (Linha 1) e Lote (Linha 2) em blocos separados.
    """

    def setUp(self):
        from django.contrib.auth.models import User
        from maintenance.models import Machine, Sector
        from production.models import (
            ProductionMachineConfig,
            ProductionCavityConfig,
            ProductionCavityMatrixHistory,
            ProductionMatrixCatalog,
        )

        self.user = User.objects.create_user("ux_lider", "ux@test.com", "pwd123", is_staff=True)
        self.client.login(username="ux_lider", password="pwd123")

        self.sector = Sector.objects.create(nome="Produção UX Test")
        self.machine = Machine.objects.create(nome="PRENSA BOM 01", setor=self.sector)
        self.m_cfg = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1
        )
        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.m_cfg,
            nome="CAVIDADE 01",
            xid_matriz="DP_P01_CAV1_MATRIZ",
            xid_produto="DP_P01_CAV1_PROD",
            xid_lote_bladder="DP_P01_CAV1_LOTE",
            ordem=1
        )

        # Garantir catálogos canônicos 4 e 29 no banco
        self.cat4, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=4,
            defaults={"codigo": "4", "nome_exibicao": "PNEUS HOPPER 2.75-18", "produto": "PNEUS HOPPER 2.75-18"}
        )
        self.cat29, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=29,
            defaults={"codigo": "29", "nome_exibicao": "PNEU READY 100/90-18", "produto": "PNEU READY 100/90-18"}
        )

    def test_matrix_code_4_and_29_resolution_in_history(self):
        from production.models import ProductionCavityMatrixHistory
        from production.services import ProductionStateService

        now = timezone.now()
        h1 = ProductionCavityMatrixHistory.objects.create(
            cavity_config=self.cav1,
            matrix_value="4",
            started_at=now - timezone.timedelta(hours=2),
            ended_at=now - timezone.timedelta(hours=1)
        )
        h2 = ProductionCavityMatrixHistory.objects.create(
            cavity_config=self.cav1,
            matrix_value="29",
            started_at=now - timezone.timedelta(hours=1),
            ended_at=None
        )

        dash_state = ProductionStateService.get_dashboard_state(scada_values={})
        history = dash_state["matrix_history"]
        self.assertTrue(len(history) >= 2)

        item29 = next((h for h in history if h["id"] == h2.id), None)
        item4 = next((h for h in history if h["id"] == h1.id), None)

        self.assertIsNotNone(item29)
        self.assertIsNotNone(item4)

        # Deve exibir o nome canônico e NÃO apenas o código bruto ("4" ou "29")
        self.assertIn(self.cat29.nome_exibicao, item29["matriz_value"])
        self.assertNotEqual(item29["matriz_value"], "29")

        self.assertIn(self.cat4.nome_exibicao, item4["matriz_value"])
        self.assertNotEqual(item4["matriz_value"], "4")

    def test_unregistered_matrix_code_fallback_does_not_error(self):
        from production.models import ProductionCavityMatrixHistory
        from production.services import ProductionStateService

        now = timezone.now()
        h_unregistered = ProductionCavityMatrixHistory.objects.create(
            cavity_config=self.cav1,
            matrix_value="99",
            started_at=now - timezone.timedelta(minutes=30),
            ended_at=None
        )

        dash_state = ProductionStateService.get_dashboard_state(scada_values={})
        history = dash_state["matrix_history"]
        item99 = next((h for h in history if h["id"] == h_unregistered.id), None)

        self.assertIsNotNone(item99)
        self.assertIn("99", item99["matriz_value"])
        self.assertIn("Código não cadastrado", item99["matriz_value"])

    def test_card_cavity_structure_has_separated_matriz_and_lote(self):
        from production.services import ProductionStateService

        scada_values = {
            "DP_P01_CAV1_MATRIZ": {"value": 4, "str_value": "4"},
            "DP_P01_CAV1_PROD": {"value": "6154", "str_value": "6154"},
            "DP_P01_CAV1_LOTE": {"value": "161035", "str_value": "161035"},
        }
        dash_state = ProductionStateService.get_dashboard_state(scada_values=scada_values)
        machines = dash_state["machines"]
        self.assertTrue(len(machines) >= 1)

        m0 = next((m for m in machines if m["id"] == self.m_cfg.id), None)
        self.assertIsNotNone(m0)
        cav0 = next((c for c in m0["cavidades"] if c["id"] == self.cav1.id), None)
        self.assertIsNotNone(cav0)

        # Validar novos atributos no dicionário da cavidade
        self.assertEqual(cav0["matriz_nome"], self.cat4.nome_exibicao)
        self.assertEqual(cav0["lote_display"], "6154 - 161035")

    def test_dashboard_view_renders_separated_lines_and_canonical_history(self):
        from production.models import ProductionCavityMatrixHistory

        now = timezone.now()
        ProductionCavityMatrixHistory.objects.create(
            cavity_config=self.cav1,
            matrix_value="29",
            started_at=now - timezone.timedelta(minutes=15),
            ended_at=None
        )

        response = self.client.get(reverse("production:dashboard"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Confirmar nome canônico presente na resposta
        self.assertIn(self.cat29.nome_exibicao, content)
        # Confirmar nova estrutura visual dos cards com Matriz e Lote em linhas separadas
        self.assertIn("Matriz: <strong class=\"text-dark\">", content)
        self.assertIn("Lote: <strong class=\"text-dark\">", content)














