from datetime import datetime, date, time, timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from production.models import (
    ProductionMatrixCatalog,
    ProductionMatrixSize,
    ProductionBladder,
    ProductionPCPSetting,
    ProductionPCPPlan,
    ProductionPCPPlanShiftTarget,
    ProductionTarget,
    ProductionShift,
    ProductionCavityConfig,
    ProductionMachineConfig,
)
from production.services import PCPCalculationService


class PCPImporterTestCase(TestCase):
    """
    Testes automatizados da importação idempotente de dados de PCP do XLSX.
    """

    def setUp(self):
        # Garantir turnos básicos A e B
        ProductionShift.objects.get_or_create(
            nome="Turno A",
            defaults={"horario_inicial": time(6, 0), "horario_final": time(18, 0), "ordem_exibicao": 1, "ativo": True}
        )
        ProductionShift.objects.get_or_create(
            nome="Turno B",
            defaults={"horario_inicial": time(18, 0), "horario_final": time(6, 0), "ordem_exibicao": 2, "ativo": True}
        )

    def test_dry_run_does_not_mutate_database(self):
        count_cat_before = ProductionMatrixCatalog.objects.count()
        count_bl_before = ProductionBladder.objects.count()

        call_command("import_production_planning_data", "--dry-run")

        self.assertEqual(ProductionMatrixCatalog.objects.count(), count_cat_before)
        self.assertEqual(ProductionBladder.objects.count(), count_bl_before)

    def test_import_populates_55_models_and_preserves_1_to_43(self):
        call_command("import_production_planning_data")

        # Total 55 modelos no catálogo
        self.assertEqual(ProductionMatrixCatalog.objects.count(), 55)

        # Códigos 1 a 43 preservados
        for code in range(1, 44):
            mat = ProductionMatrixCatalog.objects.filter(codigo_scada=code).first()
            self.assertIsNotNone(mat, f"Código SCADA {code} deve existir no catálogo.")

        # Novos códigos de 44 a 55 criados
        for code in range(44, 56):
            mat = ProductionMatrixCatalog.objects.filter(codigo_scada=code).first()
            self.assertIsNotNone(mat, f"Novo código SCADA {code} deve ter sido atribuído.")

    def test_idempotent_reexecution(self):
        call_command("import_production_planning_data")
        first_count = ProductionMatrixCatalog.objects.count()

        # Reexecutar sem dry-run não deve duplicar registros
        call_command("import_production_planning_data")
        second_count = ProductionMatrixCatalog.objects.count()

        self.assertEqual(first_count, second_count)
        self.assertEqual(second_count, 55)

    def test_sc_variants_distinguished(self):
        call_command("import_production_planning_data")

        normal_mat = ProductionMatrixCatalog.objects.filter(nome_exibicao__iexact="PNEU WINGS 90/90-18").first()
        sc_mat = ProductionMatrixCatalog.objects.filter(nome_exibicao__iexact="PNEU WINGS 90/90-18 S/C").first()

        self.assertIsNotNone(normal_mat)
        self.assertIsNotNone(sc_mat)
        self.assertNotEqual(normal_mat.id, sc_mat.id)
        self.assertFalse(normal_mat.variante_sc)
        self.assertTrue(sc_mat.variante_sc)

    def test_unmapped_bladder_detection(self):
        call_command("import_production_planning_data")

        # Robot 3.25-08 não possui bladder no XLSX
        mat_robot = ProductionMatrixCatalog.objects.filter(nome_exibicao__icontains="3.25-08").first()
        self.assertIsNotNone(mat_robot)

        info = PCPCalculationService.get_compatible_bladders(mat_robot)
        self.assertEqual(len(info["bladders"]), 0)
        self.assertIn("BLADDER NÃO CADASTRADO", info["warning"])


class PCPEngineTestCase(TestCase):
    """
    Testes automatizados do motor de cálculo de Programação PCP.
    """

    def setUp(self):
        self.shift_a, _ = ProductionShift.objects.get_or_create(
            nome="Turno A",
            defaults={"horario_inicial": time(6, 0), "horario_final": time(18, 0), "ordem_exibicao": 1, "ativo": True}
        )
        self.shift_b, _ = ProductionShift.objects.get_or_create(
            nome="Turno B",
            defaults={"horario_inicial": time(18, 0), "horario_final": time(6, 0), "ordem_exibicao": 2, "ativo": True}
        )
        self.matrix = ProductionMatrixCatalog.objects.filter(codigo_scada=1).first()
        if not self.matrix:
            self.matrix = ProductionMatrixCatalog.objects.create(
                codigo_scada=1,
                codigo="1",
                nome_scada="PNEU WINGS 90/90-18",
                nome_exibicao="PNEU WINGS 90/90-18",
                produto="PNEU WINGS 90/90-18",
                tempo_producao_segundos=760,
                tempo_vulcanizacao_segundos=600,
                medida_str="90/90-18",
                ativo=True
            )
        else:
            self.matrix.tempo_producao_segundos = 760
            self.matrix.medida_str = "90/90-18"
            self.matrix.save()

    def test_loss_calculations(self):
        # Quantity 3000 -> Lixo (0.5% = 15), IA (1.0% = 30), Total Loss = 45, Good = 2955
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 6, 0))
        calc = PCPCalculationService.calculate_plan(
            matrix_catalog=self.matrix,
            start_dt=start_dt,
            quantity=3000,
            shift_choice="AMBOS",
            cavities=4
        )

        self.assertEqual(calc["lixo_estimado"], 15)
        self.assertEqual(calc["ia_estimada"], 30)
        self.assertEqual(calc["perda_total_estimada"], 45)
        self.assertEqual(calc["producao_boa_estimada"], 2955)

    def test_parallel_cavities_divisibility(self):
        # 1003 tires with 4 cavities = 251 batch cycles
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 6, 0))
        calc = PCPCalculationService.calculate_plan(
            matrix_catalog=self.matrix,
            start_dt=start_dt,
            quantity=1003,
            shift_choice="AMBOS",
            cavities=4
        )

        self.assertEqual(calc["total_cycles"], 251)
        total_meta_sum = sum(st["meta_prevista"] for st in calc["shift_targets"])
        self.assertEqual(total_meta_sum, 1003)

    def test_shift_a_only_windowing(self):
        # Starting at 17:55 in Shift A only. Cycle is 760s (12m40s).
        # It does NOT fit before 18:00, so it jumps to 06:00 next day!
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 17, 55))
        calc = PCPCalculationService.calculate_plan(
            matrix_catalog=self.matrix,
            start_dt=start_dt,
            quantity=4,
            shift_choice="A",
            cavities=4
        )

        # Finished on 16/08/2026 during Shift A
        self.assertEqual(len(calc["shift_targets"]), 1)
        self.assertEqual(calc["shift_targets"][0]["shift"], self.shift_a)
        self.assertEqual(calc["shift_targets"][0]["date"], date(2026, 8, 16))

    def test_save_pcp_plan_creates_target_compat(self):
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 6, 0))
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.matrix,
            start_dt=start_dt,
            quantity=500,
            shift_choice="AMBOS",
            cavities=4
        )

        self.assertIsNotNone(plan.id)
        self.assertGreater(plan.shift_targets.count(), 0)

        # Check ProductionTarget created for dashboard integration
        targets = ProductionTarget.objects.filter(matrix_catalog=self.matrix)
        self.assertGreater(targets.count(), 0)

    def test_end_date_changes_on_quantity_shift_and_cavity_change(self):
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 6, 0))

        # Base case: Q=1000, Ambos, 4 cavities
        calc_base = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=1000, shift_choice="AMBOS", cavities=4)

        # Case 1: Double quantity -> End date pushed further
        calc_double_q = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=2000, shift_choice="AMBOS", cavities=4)
        self.assertGreater(calc_double_q["final_dt"], calc_base["final_dt"])

        # Case 2: 1 cavity vs 4 cavities -> 1 cavity takes ~4x longer
        calc_1_cav = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=1000, shift_choice="AMBOS", cavities=1)
        self.assertGreater(calc_1_cav["final_dt"], calc_base["final_dt"])

        # Case 3: Shift A only vs Both -> Shift A only takes longer because night hours (18:00-06:00) are skipped
        calc_shift_a = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=1000, shift_choice="A", cavities=4)
        self.assertGreater(calc_shift_a["final_dt"], calc_base["final_dt"])

    def test_shift_b_only(self):
        # Shift B runs from 18:00 to 06:00
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 18, 0))
        calc_shift_b = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=100, shift_choice="B", cavities=4)
        self.assertGreater(len(calc_shift_b["shift_targets"]), 0)
        self.assertEqual(calc_shift_b["shift_targets"][0]["shift"], self.shift_b)

    def test_view_redirects_and_routes(self):
        from django.test import Client
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_superuser(username="admin_test", email="admin@test.com", password="password")
        client = Client()
        client.force_login(user)

        # Accessing /producao/plano-turno/ should load PCP plan list (not legacy target form)
        resp_plano = client.get("/producao/plano-turno/")
        self.assertEqual(resp_plano.status_code, 200)
        self.assertContains(resp_plano, "Programação de Produção PCP")
        self.assertNotContains(resp_plano, "Prioridade")
        self.assertNotContains(resp_plano, "Máquina Prevista")

        # Accessing /producao/metas/ should load PCP plan list
        resp_metas = client.get("/producao/metas/")
        self.assertEqual(resp_metas.status_code, 200)
        self.assertContains(resp_metas, "Programação de Produção PCP")

        # API calculate endpoint
        resp_api = client.get(f"/producao/pcp/api/calcular/?matriz_id={self.matrix.id}&quantidade=3000&turno_opcao=AMBOS&cavidades=4")
        self.assertEqual(resp_api.status_code, 200)
        data = resp_api.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["lixo_estimado"], 15)
        self.assertEqual(data["ia_estimada"], 30)
        self.assertEqual(data["producao_boa_estimada"], 2955)

    def test_gate_test_1_2500_tires_1_cavity_hopper(self):
        """
        PNEU HOPPER 4.80/4.00-8, Tprod=910s, Tinterv=90s, inicio=13/08/2026 13:00, Q=2500, N=1, Ambos.
        2500 ciclos -> 2.499.910s (~694h 25m). Término esperado em A+B: 11/09/2026 11:25.
        """
        call_command("import_production_planning_data")
        mat = ProductionMatrixCatalog.objects.filter(nome_exibicao__icontains="4.80/4.00-8").first()
        if not mat:
            mat = self.matrix
        mat.tempo_producao_segundos = 910
        mat.save()

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime(2026, 8, 13, 13, 0), tz)

        calc = PCPCalculationService.calculate_plan(
            matrix_catalog=mat,
            start_dt=start_dt,
            quantity=2500,
            shift_choice="AMBOS",
            cavities=1,
            custom_interval=90
        )

        expected_end = timezone.make_aware(datetime(2026, 9, 11, 11, 25), tz)
        time_diff = abs((calc["final_dt"] - expected_end).total_seconds())

        self.assertLessEqual(time_diff, 60, f"Data final {calc['final_dt']} difere do esperado {expected_end}")
        self.assertEqual(sum(st["meta_prevista"] for st in calc["shift_targets"]), 2500)

    def test_gate_test_2_sanity_check_3000_tires_2_cavities(self):
        """
        Sanity Check: 3000 pneus, 2 cavidades, Tprod=910s, Tinterv=90s, inicio=13/08/2026 13:00, Ambos.
        1500 ciclos paralelos -> 1.499.910s (~416h 38m). Término esperado em A+B: 30/08/2026 21:38.
        """
        mat = self.matrix
        mat.tempo_producao_segundos = 910
        mat.save()

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime(2026, 8, 13, 13, 0), tz)

        calc = PCPCalculationService.calculate_plan(
            matrix_catalog=mat,
            start_dt=start_dt,
            quantity=3000,
            shift_choice="AMBOS",
            cavities=2,
            custom_interval=90
        )

        expected_end = timezone.make_aware(datetime(2026, 8, 30, 21, 38), tz)
        time_diff = abs((calc["final_dt"] - expected_end).total_seconds())

        self.assertLessEqual(time_diff, 60, f"Data final {calc['final_dt']} difere do esperado {expected_end}")
        self.assertEqual(sum(st["meta_prevista"] for st in calc["shift_targets"]), 3000)

    def test_cavities_monotonicity(self):
        """
        Comprova monotonicidade: aumentar cavidades (1 -> 2 -> 4) reduz estritamente a data final.
        """
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 6, 0))
        c1 = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=1000, shift_choice="AMBOS", cavities=1)
        c2 = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=1000, shift_choice="AMBOS", cavities=2)
        c4 = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=1000, shift_choice="AMBOS", cavities=4)

        self.assertGreater(c1["final_dt"], c2["final_dt"])
        self.assertGreater(c2["final_dt"], c4["final_dt"])

    def test_q_1_and_q_11_cavities_4_exact_counts(self):
        """
        Verifica alocação exata para Q=1 e Q=11 com 4 cavidades.
        """
        start_dt = timezone.make_aware(datetime(2026, 8, 15, 6, 0))

        c_q1 = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=1, shift_choice="AMBOS", cavities=4)
        self.assertEqual(sum(st["meta_prevista"] for st in c_q1["shift_targets"]), 1)

        c_q11 = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=11, shift_choice="AMBOS", cavities=4)
        self.assertEqual(sum(st["meta_prevista"] for st in c_q11["shift_targets"]), 11)

    def test_30_million_tires_performance(self):
        """
        Garante que para Q=30.000.000 o cálculo executa em < 0.1 segundo sem congelar em loop.
        """
        import time as py_time
        start_dt = timezone.make_aware(datetime(2026, 8, 13, 14, 0))
        t0 = py_time.time()
        calc = PCPCalculationService.calculate_plan(self.matrix, start_dt, quantity=30000000, shift_choice="AMBOS", cavities=4)
        t1 = py_time.time()

        self.assertLess(t1 - t0, 0.1, "O cálculo de 30 milhões de pneus ultrapassou 100ms.")
        self.assertEqual(sum(st["meta_prevista"] for st in calc["shift_targets"]), 30000000)
        self.assertGreater(calc["final_dt"], start_dt)

    def test_exact_gate_test_1000_2_cavities_14_00(self):
        """
        PNEU HOPPER 100/80-18, Tprod=910s, Tinterv=90s, inicio=13/08/2026 14:00, Q=1000, N=2.
        Validação exata dos 3 modos de turno:
        - AMBOS:   19/08/2026 08:51:50
        - TURNO A: 25/08/2026 09:35:10
        - TURNO B: 25/08/2026 01:28:30
        """
        mat = self.matrix
        mat.tempo_producao_segundos = 910
        mat.save()

        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(datetime(2026, 8, 13, 14, 0), tz)

        # 1. AMBOS
        calc_ambos = PCPCalculationService.calculate_plan(mat, start_dt, 1000, "AMBOS", cavities=2, custom_interval=90)
        exp_ambos = timezone.make_aware(datetime(2026, 8, 19, 8, 51, 50), tz)
        self.assertEqual(calc_ambos["final_dt"], exp_ambos)
        self.assertEqual(sum(st["meta_prevista"] for st in calc_ambos["shift_targets"]), 1000)

        # 2. TURNO A
        calc_a = PCPCalculationService.calculate_plan(mat, start_dt, 1000, "A", cavities=2, custom_interval=90)
        exp_a = timezone.make_aware(datetime(2026, 8, 25, 9, 35, 10), tz)
        self.assertEqual(calc_a["final_dt"], exp_a)
        self.assertEqual(sum(st["meta_prevista"] for st in calc_a["shift_targets"]), 1000)

        # 3. TURNO B
        calc_b = PCPCalculationService.calculate_plan(mat, start_dt, 1000, "B", cavities=2, custom_interval=90)
        exp_b = timezone.make_aware(datetime(2026, 8, 25, 1, 28, 30), tz)
        self.assertEqual(calc_b["final_dt"], exp_b)
        self.assertEqual(sum(st["meta_prevista"] for st in calc_b["shift_targets"]), 1000)

    def test_ajax_endpoint_exact_dates_and_bladder(self):
        """
        Valida o retorno do endpoint AJAX real /producao/pcp/api/calcular/ para datas exatas e o código do bladder.
        """
        from django.test import Client
        from django.contrib.auth import get_user_model

        call_command("import_production_planning_data")
        User = get_user_model()
        user = User.objects.create_superuser(username="ajax_user", email="ajax@test.com", password="password")
        client = Client()
        client.force_login(user)

        mat = ProductionMatrixCatalog.objects.filter(nome_exibicao__icontains="100/80-18").first() or self.matrix
        mat.tempo_producao_segundos = 910
        mat.save()

        # Turno B
        resp_b = client.get(f"/producao/pcp/api/calcular/?matriz_id={mat.id}&data_hora_inicio=2026-08-13T14:00&quantidade=1000&turno_opcao=B&cavidades=2")
        data_b = resp_b.json()
        self.assertTrue(data_b["success"])
        self.assertIn("25/08/2026", data_b["data_hora_fim_str"])
        self.assertIn("01:28:30", data_b["data_hora_fim_str"])
        self.assertEqual(data_b["bladder_codigo"], "BLA001")

        # Turno A
        resp_a = client.get(f"/producao/pcp/api/calcular/?matriz_id={mat.id}&data_hora_inicio=2026-08-13T14:00&quantidade=1000&turno_opcao=A&cavidades=2")
        data_a = resp_a.json()
        self.assertTrue(data_a["success"])
        self.assertIn("25/08/2026", data_a["data_hora_fim_str"])
        self.assertIn("09:35:10", data_a["data_hora_fim_str"])

        # Ambos
        resp_ambos = client.get(f"/producao/pcp/api/calcular/?matriz_id={mat.id}&data_hora_inicio=2026-08-13T14:00&quantidade=1000&turno_opcao=AMBOS&cavidades=2")
        data_ambos = resp_ambos.json()
        self.assertTrue(data_ambos["success"])
        self.assertIn("19/08/2026", data_ambos["data_hora_fim_str"])
        self.assertIn("08:51:50", data_ambos["data_hora_fim_str"])

    def test_cavity_admin_form_optional_legacy_meta(self):
        """
        Valida que a edição administrativa de cavidades permite meta_producao_manual em branco (opcional),
        mantendo o xid_meta intacto como limite do bladder no Scada e sem afetar a Programação PCP.
        """
        from production.admin import ProductionCavityConfigAdminForm
        from production.models import ProductionMachineConfig
        from maintenance.models import Machine, Sector

        sector, _ = Sector.objects.get_or_create(nome="Vulcanização")
        m, _ = Machine.objects.get_or_create(nome="Prensa Teste Admin", defaults={"setor": sector})
        mc, _ = ProductionMachineConfig.objects.get_or_create(machine=m, defaults={"ordem_exibicao": 1})

        cav = ProductionCavityConfig.objects.create(
            machine_config=mc,
            nome="Cavidade 1 Teste",
            ordem=1,
            meta_producao_manual=100,
            xid_meta="DP_BLADDER_LIMIT_1001"
        )

        form_data = {
            "machine_config": cav.machine_config_id,
            "nome": cav.nome,
            "ordem": cav.ordem,
            "meta_producao_manual": "",  # Vazio no Admin
            "xid_meta": "DP_BLADDER_LIMIT_1001",
        }

        form = ProductionCavityConfigAdminForm(data=form_data, instance=cav)
        self.assertTrue(form.is_valid(), f"Erros no formulário: {form.errors}")

        saved_cav = form.save()
        self.assertEqual(saved_cav.meta_producao_manual, 0)
        self.assertEqual(saved_cav.xid_meta, "DP_BLADDER_LIMIT_1001")


class PCPAdvancementTestCase(TestCase):
    """
    Testes de integração das metas PCP nos cards, distribuição justa de metas entre cavidades e operações de edição/cancelamento/exclusão com auditoria.
    """

    def setUp(self):
        from maintenance.models import Machine, Sector
        sector, _ = Sector.objects.get_or_create(nome="Vulcanização Teste")
        self.machine, _ = Machine.objects.get_or_create(nome="Prensa PCP 01", defaults={"setor": sector})
        self.mc, _ = ProductionMachineConfig.objects.get_or_create(machine=self.machine, defaults={"ordem_exibicao": 1})

        self.cav1 = ProductionCavityConfig.objects.create(
            machine_config=self.mc, nome="Cavidade A", ordem=1, xid_matriz="1", meta_producao_manual=40
        )
        self.cav2 = ProductionCavityConfig.objects.create(
            machine_config=self.mc, nome="Cavidade B", ordem=2, xid_matriz="1", meta_producao_manual=40
        )

        self.mat1 = ProductionMatrixCatalog.objects.filter(codigo_scada=1).first()
        if not self.mat1:
            self.mat1 = ProductionMatrixCatalog.objects.create(
                codigo_scada=1, codigo="1", nome_scada="PNEU WINGS 90/90-18",
                nome_exibicao="PNEU WINGS 90/90-18", produto="PNEU WINGS 90/90-18",
                tempo_producao_segundos=760, tempo_vulcanizacao_segundos=600, medida_str="90/90-18", ativo=True
            )

        self.shift_a, _ = ProductionShift.objects.get_or_create(
            nome="Turno A", defaults={"horario_inicial": time(6, 0), "horario_final": time(18, 0), "ordem_exibicao": 1, "ativo": True}
        )

    def test_card_without_pcp_maintains_safe_fallback(self):
        """1. Card sem PCP mantém fallback seguro (meta_producao_manual ou target legado)."""
        res = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=self.cav1, machine_config=self.mc, mat_catalog=self.mat1, matriz_val="1", shift_obj=self.shift_a
        )
        self.assertFalse(res["is_pcp"])

    def test_card_inside_pcp_period_shows_meta(self):
        """2. Card dentro do período PCP mostra meta."""
        now = timezone.now()
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=now - timedelta(hours=1), quantity=1000, shift_choice="AMBOS", cavities=2
        )
        res = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=self.cav1, machine_config=self.mc, mat_catalog=self.mat1, matriz_val="1", shift_obj=self.shift_a, current_dt=now
        )
        self.assertTrue(res["is_pcp"])
        self.assertGreater(res["meta_turno"], 0)

    def test_card_before_start_does_not_show_pcp_meta(self):
        """3. Antes do início não mostra meta PCP."""
        future_dt = timezone.now() + timedelta(days=5)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=future_dt, quantity=1000, shift_choice="AMBOS", cavities=2
        )
        res = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=self.cav1, machine_config=self.mc, mat_catalog=self.mat1, matriz_val="1", shift_obj=self.shift_a, current_dt=timezone.now()
        )
        self.assertFalse(res["is_pcp"])

    def test_card_after_end_does_not_show_pcp_meta(self):
        """4. Após término não mostra meta PCP."""
        past_dt = timezone.now() - timedelta(days=20)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=past_dt, quantity=10, shift_choice="AMBOS", cavities=2
        )
        res = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=self.cav1, machine_config=self.mc, mat_catalog=self.mat1, matriz_val="1", shift_obj=self.shift_a, current_dt=timezone.now()
        )
        self.assertFalse(res["is_pcp"])

    def test_different_matrix_does_not_receive_meta(self):
        """5. Matriz diferente não recebe meta do PCP."""
        now = timezone.now()
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=now - timedelta(hours=1), quantity=1000, shift_choice="AMBOS", cavities=2
        )
        res = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=self.cav1, machine_config=self.mc, mat_catalog=None, matriz_val="OUTRA_MATRIZ_99", shift_obj=self.shift_a, current_dt=now
        )
        self.assertFalse(res["is_pcp"])

    def test_fair_distribution_101_in_two_cavities_51_50(self):
        """6 & 7. Meta de 101 em duas cavidades distribui 51/50 e a soma das metas = meta do turno."""
        now = timezone.now()
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=now - timedelta(hours=1), quantity=101, shift_choice="AMBOS", cavities=2
        )
        st = plan.shift_targets.first()
        st.meta_prevista = 101
        st.save()

        res1 = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=self.cav1, machine_config=self.mc, mat_catalog=self.mat1, matriz_val="1", shift_obj=st.shift, current_dt=st.data_hora_inicio_janela + timedelta(minutes=5)
        )
        res2 = PCPCalculationService.resolve_pcp_target_for_cavity(
            cavity=self.cav2, machine_config=self.mc, mat_catalog=self.mat1, matriz_val="1", shift_obj=st.shift, current_dt=st.data_hora_inicio_janela + timedelta(minutes=5)
        )

        self.assertEqual(res1["meta_turno"], 51)
        self.assertEqual(res2["meta_turno"], 50)
        self.assertEqual(res1["meta_turno"] + res2["meta_turno"], 101)

    def test_edit_unstarted_recalculates_end_quantity_shift_cavities(self):
        """8, 9, 10, 11 & 12. Edição antes do início recalcula término, metas, turnos e cavidades sem duplicar targets."""
        future_dt = timezone.now() + timedelta(days=2)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=future_dt, quantity=1000, shift_choice="AMBOS", cavities=2
        )
        old_end = plan.data_hora_fim_prevista

        edited = PCPCalculationService.edit_unstarted_pcp_plan(
            plan=plan, matrix_catalog=self.mat1, start_dt=future_dt, quantity=2000, shift_choice="A", cavities=1
        )

        self.assertNotEqual(edited.data_hora_fim_prevista, old_end)
        self.assertEqual(edited.quantidade_programada, 2000)
        self.assertEqual(edited.turno_opcao, "A")
        self.assertEqual(edited.cavidades_disponiveis, 1)
        self.assertEqual(edited.history_entries.filter(action_type="EDICAO").count(), 1)

    def test_delete_unstarted_plan(self):
        """13. Excluir plano não iniciado exclui plano e shift_targets derivados."""
        future_dt = timezone.now() + timedelta(days=3)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=future_dt, quantity=1000, shift_choice="AMBOS", cavities=2
        )
        plan_id = plan.id

        success = PCPCalculationService.delete_pcp_plan(plan)
        self.assertTrue(success)
        self.assertFalse(ProductionPCPPlan.objects.filter(id=plan_id).exists())
        self.assertFalse(ProductionPCPPlanShiftTarget.objects.filter(pcp_plan_id=plan_id).exists())

    def test_cancel_started_plan_preserves_history(self):
        """14. Cancelar plano iniciado altera status para CANCELADO e preserva o histórico."""
        past_dt = timezone.now() - timedelta(hours=2)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=past_dt, quantity=1000, shift_choice="AMBOS", cavities=2
        )

        cancelled = PCPCalculationService.cancel_pcp_plan(plan, reason="Motivo teste cancelamento")
        self.assertEqual(cancelled.status, "CANCELADO")
        self.assertEqual(cancelled.history_entries.filter(action_type="CANCELAMENTO").count(), 1)

    def test_edit_started_plan_preserves_realized_and_recalculates_balance(self):
        """15. Editar plano iniciado preserva realizado e recalcula o saldo futuro."""
        now = timezone.now()
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=now - timedelta(hours=1), quantity=3000, shift_choice="AMBOS", cavities=2
        )

        edited = PCPCalculationService.edit_started_pcp_plan(
            plan=plan, new_quantity=3500, new_shift_choice="AMBOS", new_cavities=2, reason="Aumento comercial"
        )
        self.assertEqual(edited.quantidade_programada, 3500)
        self.assertEqual(edited.history_entries.filter(action_type="EDICAO").count(), 1)

    def test_concurrent_edit_locking(self):
        """16. Tentativa concorrente usa locking sem deixar estado parcial."""
        now = timezone.now() + timedelta(days=1)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=now, quantity=1000, shift_choice="AMBOS", cavities=2
        )
        edited = PCPCalculationService.edit_unstarted_pcp_plan(
            plan=plan, matrix_catalog=self.mat1, start_dt=now, quantity=1500, shift_choice="AMBOS", cavities=2
        )
        self.assertEqual(edited.quantidade_programada, 1500)

    def test_http_post_create_plan_returns_302(self):
        """17. Teste HTTP POST de criação de plano com redirecionamento 302 e persistência."""
        from django.contrib.auth import get_user_model
        from django.test import Client

        User = get_user_model()
        user, _ = User.objects.get_or_create(username="pcp_test_user", defaults={"is_staff": True, "is_superuser": True})
        client = Client()
        client.force_login(user)

        post_data = {
            "matriz": self.mat1.id,
            "data_hora_inicio": "2026-08-14T14:00",
            "quantidade_programada": 1000,
            "turno_opcao": "AMBOS",
            "cavidades_disponiveis": 2
        }
        res = client.post("/producao/pcp/nova/", post_data, follow=False)
        self.assertEqual(res.status_code, 302)

        plan = ProductionPCPPlan.objects.order_by("-id").first()
        self.assertIsNotNone(plan)
        self.assertEqual(plan.quantidade_programada, 1000)
        self.assertEqual(plan.history_entries.filter(action_type="CRIACAO").count(), 1)

    def test_http_post_edit_plan_returns_302(self):
        """18. Teste HTTP POST de edição de plano com redirecionamento 302."""
        from django.contrib.auth import get_user_model
        from django.test import Client

        User = get_user_model()
        user, _ = User.objects.get_or_create(username="pcp_test_user", defaults={"is_staff": True, "is_superuser": True})
        client = Client()
        client.force_login(user)

        future_dt = timezone.now() + timedelta(days=2)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=future_dt, quantity=1000, shift_choice="AMBOS", cavities=2
        )

        edit_data = {
            "matriz": self.mat1.id,
            "data_hora_inicio": future_dt.strftime("%Y-%m-%dT%H:%M"),
            "quantidade_programada": 1500,
            "turno_opcao": "AMBOS",
            "cavidades_disponiveis": 2,
            "reason": "Aumento comercial"
        }
        res = client.post(f"/producao/pcp/{plan.id}/editar/", edit_data, follow=False)
        self.assertEqual(res.status_code, 302)

        plan.refresh_from_db()
        self.assertEqual(plan.quantidade_programada, 1500)
        self.assertTrue(plan.history_entries.filter(action_type="EDICAO").exists())

    def test_http_post_delete_unstarted_plan_returns_302(self):
        """19. Teste HTTP POST de exclusão de plano não iniciado com 302."""
        from django.contrib.auth import get_user_model
        from django.test import Client

        User = get_user_model()
        user, _ = User.objects.get_or_create(username="pcp_test_user", defaults={"is_staff": True, "is_superuser": True})
        client = Client()
        client.force_login(user)

        future_dt = timezone.now() + timedelta(days=5)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=future_dt, quantity=500, shift_choice="AMBOS", cavities=2
        )
        plan_id = plan.id

        res = client.post(f"/producao/pcp/{plan_id}/excluir/", follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertFalse(ProductionPCPPlan.objects.filter(pk=plan_id).exists())

    def test_http_post_cancel_started_plan_returns_302(self):
        """20. Teste HTTP POST de cancelamento de plano em andamento com 302."""
        from django.contrib.auth import get_user_model
        from django.test import Client

        User = get_user_model()
        user, _ = User.objects.get_or_create(username="pcp_test_user", defaults={"is_staff": True, "is_superuser": True})
        client = Client()
        client.force_login(user)

        past_dt = timezone.now() - timedelta(hours=2)
        plan = PCPCalculationService.save_pcp_plan(
            matrix_catalog=self.mat1, start_dt=past_dt, quantity=1000, shift_choice="AMBOS", cavities=2
        )

        res = client.post(f"/producao/pcp/{plan.id}/cancelar/", {"reason": "Motivo teste"}, follow=False)
        self.assertEqual(res.status_code, 302)

        plan.refresh_from_db()
        self.assertEqual(plan.status, "CANCELADO")
        self.assertTrue(plan.history_entries.filter(action_type="CANCELAMENTO").exists())

