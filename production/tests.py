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
    ScadaDataPoint,
    ScadaPointValue,
    ScadaPointValueAnnotation,
)
from production.routers import ScadaRouter
from production.services import scada_reader, ProductionStateService
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
            self.router.allow_migrate("default", "production", "productionmachinestate", model=ProductionMachineState)
        )
        self.assertTrue(
            self.router.allow_migrate("default", "production", "productiondowntimeevent", model=ProductionDowntimeEvent)
        )
        self.assertFalse(
            self.router.allow_migrate("scada", "production", "productionmachinestate", model=ProductionMachineState)
        )

    def test_allow_migrate_unmanaged_model(self):
        """allow_migrate for unmanaged models returns False on all databases."""
        self.assertFalse(
            self.router.allow_migrate("default", "production", "scadadatapoint", model=self.UnmanagedModel)
        )
        self.assertFalse(
            self.router.allow_migrate("scada", "production", "scadadatapoint", model=self.UnmanagedModel)
        )


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

        # Testar execução do comando com opção --once
        out = StringIO()
        call_command("collect_production_scada", "--once", stdout=out)
        self.assertIn("Iniciando Coletor Scada Produção", out.getvalue())

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
