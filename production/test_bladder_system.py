import os
import time
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User
from maintenance.models import Sector, Machine
from production.models import (
    ProductionShift,
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionMatrixSize,
    ProductionBladder,
    ProductionMatrixCatalog,
    ProductionBladderUsage,
    ProductionBladderChangeReason,
    ProductionCycle,
    ProductionShiftAccumulated,
)
from production.services import (
    normalize_bladder_code,
    get_expected_bladders_for_matrix,
    compose_bladder_lot,
    ProductionStateService,
    _pending_bladder_reasons,
)


class BladderFoundationTrackingTestCase(TestCase):
    def setUp(self):
        _pending_bladder_reasons.clear()

        self.user = User.objects.create_user(username="test_leader", password="password123")
        self.setor = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="PRENSA 07", setor=self.setor, criticidade="A")
        self.m_cfg = ProductionMachineConfig.objects.create(
            machine=self.machine,
            ordem_exibicao=1,
            produzindo_value="1",
            stale_limit_seconds=120,
            xid_status_prensa="DP_PR07_STATUS",
        )
        self.cav = ProductionCavityConfig.objects.create(
            machine_config=self.m_cfg,
            nome="CAVIDADE 2",
            ordem=1,
            xid_matriz="DP_PR07_C2_MATRIZ",
            xid_produto="DP_PR07_C2_PROD",
            xid_lote_bladder="DP_PR07_C2_LOTE",
            xid_producao="DP_PR07_C2_PROD_CONT",
            xid_meta="DP_PR07_C2_META",
            xid_bla_real="DP_PR07_C2_BLA",
            xid_motivo_troca_bladder="DP_PR07_C2_MOTIVO_TROCA",
        )
        self.shift = ProductionShift.objects.create(
            nome="Turno 1",
            horario_inicial="06:00:00",
            horario_final="18:00:00",
            ativo=True,
            ordem_exibicao=1,
        )

        self.size_90_90 = ProductionMatrixSize.objects.create(medida="90/90-18", medida_normalizada="90/90-18")
        self.size_275 = ProductionMatrixSize.objects.create(medida="2.75-18", medida_normalizada="2.75-18")

        self.bla003 = ProductionBladder.objects.create(codigo_bladder="BLA003", descricao="Bladder 90/90-18")
        self.bla003.medidas.add(self.size_90_90)

        self.bla006 = ProductionBladder.objects.create(codigo_bladder="BLA006", descricao="Bladder 2.75-18")
        self.bla006.medidas.add(self.size_275)

        self.mat_wings = ProductionMatrixCatalog.objects.filter(codigo_scada=1).first()
        if not self.mat_wings:
            self.mat_wings = ProductionMatrixCatalog.objects.create(
                codigo_scada=1,
                codigo="1",
                nome_scada="PNEUS WINGS 90/90-18",
                nome_exibicao="PNEUS WINGS 90/90-18",
                produto="PNEUS WINGS 90/90-18",
                medida_size=self.size_90_90,
                medida_str="90/90-18",
            )
        else:
            self.mat_wings.medida_size = self.size_90_90
            self.mat_wings.save()

    def test_normalize_bladder_code(self):
        """Valida a normalização canônica para todos os formatos previstos e fallbacks seguros."""
        self.assertEqual(normalize_bladder_code(3), "BLA003")
        self.assertEqual(normalize_bladder_code(3.0), "BLA003")
        self.assertEqual(normalize_bladder_code("3"), "BLA003")
        self.assertEqual(normalize_bladder_code("03"), "BLA003")
        self.assertEqual(normalize_bladder_code("003"), "BLA003")
        self.assertEqual(normalize_bladder_code("bla003"), "BLA003")
        self.assertEqual(normalize_bladder_code("BLA003"), "BLA003")
        self.assertEqual(normalize_bladder_code("bla 3"), "BLA003")
        self.assertEqual(normalize_bladder_code("BLA-03"), "BLA003")
        self.assertEqual(normalize_bladder_code("BLA_003"), "BLA003")
        self.assertEqual(normalize_bladder_code(10), "BLA010")

        # Casos nulos, zero ou inválidos
        self.assertEqual(normalize_bladder_code(0), "")
        self.assertEqual(normalize_bladder_code("0"), "")
        self.assertEqual(normalize_bladder_code("0.0"), "")
        self.assertEqual(normalize_bladder_code(None), "")
        self.assertEqual(normalize_bladder_code(""), "")
        self.assertEqual(normalize_bladder_code("NONE"), "")
        self.assertEqual(normalize_bladder_code("N/A"), "")
        self.assertEqual(normalize_bladder_code("texto_invalido"), "")

    def test_get_expected_bladders_for_matrix(self):
        """Valida resolução da lista de bladders canônicos esperados para uma matriz."""
        expected = get_expected_bladders_for_matrix("1")
        self.assertEqual(expected, ["BLA003"])

        # Matriz não cadastrada ou sem medida
        self.assertEqual(get_expected_bladders_for_matrix("999"), [])
        self.assertEqual(get_expected_bladders_for_matrix(""), [])
        self.assertEqual(get_expected_bladders_for_matrix(None), [])

    def test_initial_stable_observation_opens_usage(self):
        """Primeira observação com identidade completa abre ProductionBladderUsage com snapshots."""
        now = timezone.now()
        scada_values = {
            "DP_PR07_STATUS": {"value": 1, "str_value": "1", "ts": 1000},
            "DP_PR07_C2_PROD": {"value": "6154", "str_value": "6154", "ts": 1000},
            "DP_PR07_C2_LOTE": {"value": "161046", "str_value": "161046", "ts": 1000},
            "DP_PR07_C2_BLA": {"value": 3, "str_value": "3", "ts": 1000},
            "DP_PR07_C2_PROD_CONT": {"value": 100, "str_value": "100", "ts": 1000},
            "DP_PR07_C2_META": {"value": 3500, "str_value": "3500", "ts": 1000},
            "DP_PR07_C2_MATRIZ": {"value": 1, "str_value": "1", "ts": 1000},
        }

        ProductionStateService.process_incremental_production(self.cav, scada_values, now=now)

        usages = list(ProductionBladderUsage.objects.filter(cavity_config=self.cav))
        self.assertEqual(len(usages), 1)
        u = usages[0]
        self.assertEqual(u.codigo_bla_real, "BLA003")
        self.assertEqual(u.lote_prefixo, "6154")
        self.assertEqual(u.lote_numero, "161046")
        self.assertEqual(u.lote_completo_snapshot, "6154 - 161046")
        self.assertEqual(u.machine_name_snapshot, "PRENSA 07")
        self.assertEqual(u.cavity_name_snapshot, "CAVIDADE 2")
        self.assertEqual(u.passadas_acumuladas, 0)
        self.assertEqual(u.limite_vida_snapshot, 3500)
        self.assertEqual(u.status, "EM_USO")
        self.assertIsNone(u.ended_at)

    def test_incremental_production_and_counter_resets_accumulate_safely(self):
        """Passadas aumentam com deltas e resets de contador não zeram nem diminuem passadas acumuladas."""
        t1 = timezone.now()
        scada_v1 = {
            "DP_PR07_C2_PROD": {"value": "6154", "str_value": "6154", "ts": 1000},
            "DP_PR07_C2_LOTE": {"value": "161046", "str_value": "161046", "ts": 1000},
            "DP_PR07_C2_BLA": {"value": "BLA003", "str_value": "BLA003", "ts": 1000},
            "DP_PR07_C2_PROD_CONT": {"value": 100, "str_value": "100", "ts": 1000},
            "DP_PR07_C2_META": {"value": 3500, "str_value": "3500", "ts": 1000},
            "DP_PR07_C2_MATRIZ": {"value": 1, "str_value": "1", "ts": 1000},
        }
        ProductionStateService.process_incremental_production(self.cav, scada_v1, now=t1)

        # Delta normal (+50 pneus)
        t2 = t1 + timedelta(minutes=10)
        scada_v2 = {**scada_v1, "DP_PR07_C2_PROD_CONT": {"value": 150, "str_value": "150", "ts": 2000}}
        ProductionStateService.process_incremental_production(self.cav, scada_v2, now=t2)

        u = ProductionBladderUsage.objects.get(cavity_config=self.cav, status="EM_USO")
        self.assertEqual(u.passadas_acumuladas, 50)

        # Reset do contador no SCADA: contador vai para 12 (ex: operador zerou o PLC)
        t3 = t2 + timedelta(minutes=10)
        scada_v3 = {**scada_v1, "DP_PR07_C2_PROD_CONT": {"value": 12, "str_value": "12", "ts": 3000}}
        ProductionStateService.process_incremental_production(self.cav, scada_v3, now=t3)

        u.refresh_from_db()
        self.assertEqual(u.passadas_acumuladas, 62)  # 50 + 12 = 62
        self.assertEqual(u.status, "EM_USO")

    def test_bladder_change_closes_usage_and_attaches_pending_reason(self):
        """Troca de lote/BLA fecha a utilização anterior, consome o motivo pendente e abre nova utilização."""
        t1 = timezone.now()
        scada_v1 = {
            "DP_PR07_C2_PROD": {"value": "6154", "str_value": "6154", "ts": 1000},
            "DP_PR07_C2_LOTE": {"value": "161046", "str_value": "161046", "ts": 1000},
            "DP_PR07_C2_BLA": {"value": "BLA003", "str_value": "BLA003", "ts": 1000},
            "DP_PR07_C2_PROD_CONT": {"value": 500, "str_value": "500", "ts": 1000},
            "DP_PR07_C2_META": {"value": 3500, "str_value": "3500", "ts": 1000},
            "DP_PR07_C2_MATRIZ": {"value": 1, "str_value": "1", "ts": 1000},
        }
        ProductionStateService.process_incremental_production(self.cav, scada_v1, now=t1)

        # Motivo informado (ex: 1 = Vazamento)
        t2 = t1 + timedelta(minutes=5)
        scada_v2 = {
            **scada_v1,
            "DP_PR07_C2_MOTIVO_TROCA": {"value": 1, "str_value": "1", "ts": 1500},
            "DP_PR07_C2_PROD_CONT": {"value": 520, "str_value": "520", "ts": 1500},
        }
        ProductionStateService.process_incremental_production(self.cav, scada_v2, now=t2)

        # Novo bladder instalado (lote novo: 6154 - 161047)
        t3 = t2 + timedelta(minutes=5)
        scada_v3 = {
            "DP_PR07_C2_PROD": {"value": "6154", "str_value": "6154", "ts": 2000},
            "DP_PR07_C2_LOTE": {"value": "161047", "str_value": "161047", "ts": 2000},
            "DP_PR07_C2_BLA": {"value": "BLA003", "str_value": "BLA003", "ts": 2000},
            "DP_PR07_C2_PROD_CONT": {"value": 5, "str_value": "5", "ts": 2000},
            "DP_PR07_C2_META": {"value": 3500, "str_value": "3500", "ts": 2000},
            "DP_PR07_C2_MATRIZ": {"value": 1, "str_value": "1", "ts": 2000},
            "DP_PR07_C2_MOTIVO_TROCA": {"value": 0, "str_value": "0", "ts": 2000},
        }
        ProductionStateService.process_incremental_production(self.cav, scada_v3, now=t3)

        usages = list(ProductionBladderUsage.objects.filter(cavity_config=self.cav).order_by("started_at"))
        self.assertEqual(len(usages), 2)

        # Utilização 1 (Finalizada)
        u1 = usages[0]
        self.assertEqual(u1.lote_numero, "161046")
        self.assertEqual(u1.status, "FINALIZADO")
        self.assertEqual(u1.passadas_acumuladas, 20)
        self.assertEqual(u1.motivo_troca, ProductionBladderChangeReason.VAZAMENTO)
        self.assertIsNotNone(u1.ended_at)

        # Utilização 2 (Em uso)
        u2 = usages[1]
        self.assertEqual(u2.lote_numero, "161047")
        self.assertEqual(u2.status, "EM_USO")
        self.assertEqual(u2.passadas_acumuladas, 0)
        self.assertIsNone(u2.ended_at)

    def test_temporary_blank_identity_does_not_close_usage(self):
        """Identidade temporariamente em branco por falha de leitura transitória não encerra o uso."""
        t1 = timezone.now()
        scada_v1 = {
            "DP_PR07_C2_PROD": {"value": "6154", "str_value": "6154", "ts": 1000},
            "DP_PR07_C2_LOTE": {"value": "161046", "str_value": "161046", "ts": 1000},
            "DP_PR07_C2_BLA": {"value": "BLA003", "str_value": "BLA003", "ts": 1000},
            "DP_PR07_C2_PROD_CONT": {"value": 100, "str_value": "100", "ts": 1000},
            "DP_PR07_C2_META": {"value": 3500, "str_value": "3500", "ts": 1000},
            "DP_PR07_C2_MATRIZ": {"value": 1, "str_value": "1", "ts": 1000},
        }
        ProductionStateService.process_incremental_production(self.cav, scada_v1, now=t1)

        # Leitura com BLA vazio/nulo (glitch de comunicação)
        t2 = t1 + timedelta(minutes=1)
        scada_v2 = {**scada_v1, "DP_PR07_C2_BLA": {"value": "", "str_value": "", "ts": 1100}}
        ProductionStateService.process_incremental_production(self.cav, scada_v2, now=t2)

        usages = list(ProductionBladderUsage.objects.filter(cavity_config=self.cav))
        self.assertEqual(len(usages), 1)
        self.assertEqual(usages[0].status, "EM_USO")
        self.assertIsNone(usages[0].ended_at)

    def test_active_bladders_context_and_filters(self):
        """Valida o serviço BladderTrackingService.get_active_bladders_context e seus filtros."""
        from production.services import BladderTrackingService

        now = timezone.now()
        ProductionBladderUsage.objects.create(
            cavity_config=self.cav,
            machine_name_snapshot="PRENSA 07",
            cavity_name_snapshot="CAVIDADE 2",
            codigo_bla_real="BLA003",
            lote_prefixo="6154",
            lote_numero="161046",
            lote_completo_snapshot="6154 - 161046",
            started_at=now - timedelta(hours=5),
            passadas_acumuladas=2900,
            limite_vida_snapshot=3000,
            status="EM_USO",
        )

        ctx = BladderTrackingService.get_active_bladders_context()
        self.assertEqual(ctx["total_em_uso"], 1)
        self.assertEqual(ctx["total_critico"], 1)  # 2900 / 3000 = 96.6% >= 95%
        self.assertEqual(len(ctx["bladders"]), 1)
        b = ctx["bladders"][0]
        self.assertEqual(b["codigo_bla"], "BLA003")
        self.assertEqual(b["lote_completo"], "6154 - 161046")
        self.assertEqual(b["vida_status"], "CRITICO")

        # Teste de filtro por texto de busca
        ctx_search = BladderTrackingService.get_active_bladders_context({"q": "161046"})
        self.assertEqual(len(ctx_search["bladders"]), 1)

        ctx_search_none = BladderTrackingService.get_active_bladders_context({"q": "999999"})
        self.assertEqual(len(ctx_search_none["bladders"]), 0)

    def test_bladder_history_kpis_and_overlapping_filter(self):
        """Valida o serviço de histórico, sobreposição de datas e cálculo de KPIs."""
        from production.services import BladderTrackingService

        now = timezone.now()

        # Uso 1: Fechado há 10 dias por vazamento (1500 passadas)
        u1 = ProductionBladderUsage.objects.create(
            cavity_config=self.cav,
            machine_name_snapshot="PRENSA 07",
            cavity_name_snapshot="CAVIDADE 2",
            codigo_bla_real="BLA003",
            lote_prefixo="6154",
            lote_numero="161040",
            lote_completo_snapshot="6154 - 161040",
            started_at=now - timedelta(days=12),
            ended_at=now - timedelta(days=10),
            passadas_acumuladas=1500,
            limite_vida_snapshot=3000,
            motivo_troca=ProductionBladderChangeReason.VAZAMENTO,
            status="FINALIZADO",
        )

        # Uso 2: Fechado há 2 dias por desgaste (2800 passadas)
        u2 = ProductionBladderUsage.objects.create(
            cavity_config=self.cav,
            machine_name_snapshot="PRENSA 07",
            cavity_name_snapshot="CAVIDADE 2",
            codigo_bla_real="BLA003",
            lote_prefixo="6154",
            lote_numero="161041",
            lote_completo_snapshot="6154 - 161041",
            started_at=now - timedelta(days=9),
            ended_at=now - timedelta(days=2),
            passadas_acumuladas=2800,
            limite_vida_snapshot=3000,
            motivo_troca=ProductionBladderChangeReason.DESGASTE_NATURAL,
            status="FINALIZADO",
        )

        ctx = BladderTrackingService.get_bladder_history_context({
            "data_inicio": (now - timedelta(days=15)).strftime("%Y-%m-%d"),
            "data_fim": now.strftime("%Y-%m-%d"),
        })

        self.assertEqual(ctx["total_utilizacoes"], 2)
        self.assertEqual(ctx["total_passadas"], 4300)
        self.assertEqual(ctx["total_trocas"], 2)
        self.assertEqual(ctx["media_passadas"], 2150)
        self.assertEqual(len(ctx["motivos_breakdown"]), 2)

    def test_bladder_consolidated_detail_multi_segment(self):
        """Valida agregação de múltiplos segmentos da mesma identidade BLA + Lote sem duplicação."""
        from production.services import BladderTrackingService

        now = timezone.now()

        # Segmento 1 na Prensa 07 (1000 passadas)
        ProductionBladderUsage.objects.create(
            cavity_config=self.cav,
            machine_name_snapshot="PRENSA 07",
            cavity_name_snapshot="CAVIDADE 2",
            codigo_bla_real="BLA003",
            lote_prefixo="6154",
            lote_numero="161099",
            lote_completo_snapshot="6154 - 161099",
            started_at=now - timedelta(days=5),
            ended_at=now - timedelta(days=3),
            passadas_acumuladas=1000,
            limite_vida_snapshot=3500,
            motivo_troca=ProductionBladderChangeReason.TROCA_MATRIZ,
            status="FINALIZADO",
        )

        # Segmento 2 na Prensa 07 (500 passadas adicionais)
        u2 = ProductionBladderUsage.objects.create(
            cavity_config=self.cav,
            machine_name_snapshot="PRENSA 07",
            cavity_name_snapshot="CAVIDADE 2",
            codigo_bla_real="BLA003",
            lote_prefixo="6154",
            lote_numero="161099",
            lote_completo_snapshot="6154 - 161099",
            started_at=now - timedelta(days=2),
            ended_at=None,
            passadas_acumuladas=500,
            limite_vida_snapshot=3500,
            status="EM_USO",
        )

        detail = BladderTrackingService.get_bladder_consolidated_detail(usage_id=u2.id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["codigo_bla"], "BLA003")
        self.assertEqual(detail["lote_completo"], "6154 - 161099")
        self.assertEqual(detail["total_passadas"], 1500)
        self.assertEqual(detail["total_instalacoes"], 2)
        self.assertTrue(detail["is_em_uso"])
        self.assertIn("PRENSA 07", detail["situacao_str"])

    def test_views_access_and_rendering(self):
        """Valida que as views de bladder respondem com HTTP 200 para líderes de produção."""
        from django.contrib.auth.models import Group
        lider_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user.groups.add(lider_group)
        self.client.force_login(self.user)

        # 1. Bladders em uso
        resp_list = self.client.get("/producao/bladders/")
        self.assertEqual(resp_list.status_code, 200)

        # 2. Histórico
        resp_hist = self.client.get("/producao/bladders/historico/")
        self.assertEqual(resp_hist.status_code, 200)

        # 3. Ficha detalhe inexistente redireciona
        resp_det_none = self.client.get("/producao/bladders/99999/")
        self.assertEqual(resp_det_none.status_code, 302)

    def test_setup_mismatch_stabilization_and_resolution(self):
        """Valida estabilização (3 ciclos), abertura do evento, acúmulo de passadas em divergência e fechamento."""
        from production.models import ProductionBladderSetupMismatchEvent
        from production.services import _setup_divergence_counter

        _setup_divergence_counter.clear()
        now = timezone.now()

        # Matriz 1 espera BLA003. Instalamos BLA006 (divergência).
        mismatch_scada = {
            "DP_PR07_C2_PROD": {"value": "6154", "str_value": "6154", "ts": 1000},
            "DP_PR07_C2_LOTE": {"value": "161046", "str_value": "161046", "ts": 1000},
            "DP_PR07_C2_BLA": {"value": "BLA006", "str_value": "BLA006", "ts": 1000},  # BLA006 é incorreto para matriz 1
            "DP_PR07_C2_PROD_CONT": {"value": 100, "str_value": "100", "ts": 1000},
            "DP_PR07_C2_META": {"value": 3500, "str_value": "3500", "ts": 1000},
            "DP_PR07_C2_MATRIZ": {"value": 1, "str_value": "1", "ts": 1000},
        }

        # Ciclo 1: Divergência detectada, mas aguarda estabilização
        ProductionStateService.process_incremental_production(self.cav, mismatch_scada, now=now)
        self.assertEqual(ProductionBladderSetupMismatchEvent.objects.count(), 0)

        # Ciclo 2: Ainda em estabilização
        ProductionStateService.process_incremental_production(self.cav, mismatch_scada, now=now + timedelta(seconds=5))
        self.assertEqual(ProductionBladderSetupMismatchEvent.objects.count(), 0)

        # Ciclo 3: 3º ciclo consecutivo -> Abre evento de divergência
        ProductionStateService.process_incremental_production(self.cav, mismatch_scada, now=now + timedelta(seconds=10))
        self.assertEqual(ProductionBladderSetupMismatchEvent.objects.count(), 1)
        ev = ProductionBladderSetupMismatchEvent.objects.first()
        self.assertEqual(ev.status, "EM_ABERTO")
        self.assertEqual(ev.codigo_bla_instalado, "BLA006")
        self.assertEqual(ev.bladders_esperados_snapshot, "BLA003")
        self.assertEqual(ev.passadas_produzidas_em_divergencia, 0)

        # Produção continua em divergência (+25 pneus)
        mismatch_scada_prod = {**mismatch_scada, "DP_PR07_C2_PROD_CONT": {"value": 125, "str_value": "125", "ts": 2000}}
        ProductionStateService.process_incremental_production(self.cav, mismatch_scada_prod, now=now + timedelta(minutes=5))
        ev.refresh_from_db()
        self.assertEqual(ev.passadas_produzidas_em_divergencia, 25)
        self.assertEqual(ev.status, "EM_ABERTO")

        # Correção do setup: instalou o BLA003 correto
        correct_scada = {
            "DP_PR07_C2_PROD": {"value": "6154", "str_value": "6154", "ts": 3000},
            "DP_PR07_C2_LOTE": {"value": "161047", "str_value": "161047", "ts": 3000},
            "DP_PR07_C2_BLA": {"value": "BLA003", "str_value": "BLA003", "ts": 3000},  # BLA003 correto!
            "DP_PR07_C2_PROD_CONT": {"value": 125, "str_value": "125", "ts": 3000},
            "DP_PR07_C2_META": {"value": 3500, "str_value": "3500", "ts": 3000},
            "DP_PR07_C2_MATRIZ": {"value": 1, "str_value": "1", "ts": 3000},
        }
        ProductionStateService.process_incremental_production(self.cav, correct_scada, now=now + timedelta(minutes=10))

        ev.refresh_from_db()
        self.assertEqual(ev.status, "FINALIZADO")
        self.assertEqual(ev.resolvido_por, "SETUP_CORRIGIDO")
        self.assertIsNotNone(ev.ended_at)
        self.assertGreaterEqual(ev.duracao_segundos, 0)


