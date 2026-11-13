from datetime import datetime, timedelta
from io import StringIO
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from maintenance.models import Sector

from .dashboard import MatrizariaDashboardService
from .forms import DashboardFiltroForm
from .models import CicloExecucaoMatrizaria, HistoricoTransicaoServicoMatrizaria, MatrizFisica, SolicitacaoServicoMatrizaria
from .tests import MatrizariaBaseTestCase


User = get_user_model()


class MatrizariaDashboardTestCase(MatrizariaBaseTestCase):
    @classmethod
    def dt(cls, day, hour=0, minute=0):
        return timezone.make_aware(datetime(2026, 11, day, hour, minute))

    @classmethod
    def request_record(cls, **overrides):
        defaults = dict(prensa=cls.prensa_01, tipo_servico=cls.tipo_ajuste,
                        solicitado_por=cls.solicitante_user, descricao_solicitacao="Dashboard",
                        data_solicitacao=cls.dt(1, 8), matriz_fisica=cls.matriz_fisica_01)
        return SolicitacaoServicoMatrizaria.objects.create(**{**defaults, **overrides})

    @classmethod
    def event(cls, request, kind, previous, state, dt):
        return HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=request, tipo_evento=kind, status_anterior=previous,
            status_novo=state, data_evento=dt,
        )

    @classmethod
    def cycle(cls, request, number, start, end=None):
        return CicloExecucaoMatrizaria.objects.create(
            solicitacao=request, numero_ciclo=number, usuario_inicio=cls.tecnico_matrizaria_1,
            data_inicio=start, data_fim=end,
            forma_encerramento="FINALIZADO_TECNICO" if end else "EM_ANDAMENTO",
        )

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.now = cls.dt(13, 12)
        cls.waiting = cls.request_record(status="AGUARDANDO_CONFERENCIA", prioridade="URGENTE",
                                         finalizado_por=cls.tecnico_matrizaria_1,
                                         quantidade_retrabalhos=20)
        cls.event(cls.waiting, "CRIACAO", "INEXISTENTE", "SOLICITADO", cls.dt(1, 8))
        cls.event(cls.waiting, "INICIO", "SOLICITADO", "EM_EXECUCAO", cls.dt(12, 8))
        cls.event(cls.waiting, "FINALIZACAO_EXECUCAO", "EM_EXECUCAO", "AGUARDANDO_CONFERENCIA", cls.dt(12, 9))
        cls.event(cls.waiting, "REJEICAO_RETRABALHO", "AGUARDANDO_CONFERENCIA", "AGUARDANDO_RETRABALHO", cls.dt(12, 10))
        cls.event(cls.waiting, "INICIO", "AGUARDANDO_RETRABALHO", "EM_EXECUCAO", cls.dt(13, 8))
        cls.event(cls.waiting, "FINALIZACAO_EXECUCAO", "EM_EXECUCAO", "AGUARDANDO_CONFERENCIA", cls.dt(13, 9))
        cls.event(cls.waiting, "ALTERACAO_DADO", "AGUARDANDO_CONFERENCIA", "AGUARDANDO_CONFERENCIA", cls.dt(13, 10))
        cls.cycle(cls.waiting, 1, cls.dt(12, 8), cls.dt(12, 9))
        cls.cycle(cls.waiting, 2, cls.dt(13, 8), cls.dt(13, 9))

        cls.completed = cls.request_record(status="CONCLUIDO", data_solicitacao=cls.dt(11, 22),
                                           data_conferencia=cls.dt(13, 11))
        cls.event(cls.completed, "REJEICAO_RETRABALHO", "AGUARDANDO_CONFERENCIA", "AGUARDANDO_RETRABALHO", cls.dt(12, 8))
        cls.event(cls.completed, "REJEICAO_RETRABALHO", "AGUARDANDO_CONFERENCIA", "AGUARDANDO_RETRABALHO", cls.dt(12, 11))
        cls.event(cls.completed, "CONFERENCIA_APROVADA", "AGUARDANDO_CONFERENCIA", "CONCLUIDO", cls.dt(13, 11))
        cls.cycle(cls.completed, 1, cls.dt(11, 23), cls.dt(12, 1))
        cls.cycle(cls.completed, 2, cls.dt(12, 9), cls.dt(12, 10))
        cls.cycle(cls.completed, 3, cls.dt(13, 8), cls.dt(13, 9))

        cls.cancelled = cls.request_record(status="CANCELADO", prensa=cls.prensa_02,
            data_solicitacao=cls.dt(12, 9), data_cancelamento=cls.dt(12, 11))
        cls.event(cls.cancelled, "CANCELAMENTO", "SOLICITADO", "CANCELADO", cls.dt(12, 11))
        cls.internal = cls.request_record(status="EM_EXECUCAO", destino="MATRIZARIA", prensa=None,
            matriz_fisica=None, data_solicitacao=cls.dt(13, 10), responsavel_atribuido=cls.tecnico_matrizaria_2)
        cls.event(cls.internal, "CRIACAO", "INEXISTENTE", "SOLICITADO", cls.dt(13, 10))
        cls.event(cls.internal, "INICIO", "SOLICITADO", "EM_EXECUCAO", cls.dt(13, 11))
        cls.event(cls.internal, "TRANSFERENCIA", "EM_EXECUCAO", "EM_EXECUCAO", cls.dt(13, 11, 30))
        cls.cycle(cls.internal, 1, cls.dt(13, 11))
        cls.matrix2 = MatrizFisica.objects.create(modelo=cls.cat_hopper, numero_sequencial=2,
                                                 identificador_estavel="MF-HOPPER-002")
        cls.incomplete = cls.request_record(data_solicitacao=cls.dt(2, 8), matriz_fisica=cls.matrix2)
        cls.technical_leader = User.objects.create_user(username="lider_tecnico_dashboard")
        cls.technical_leader.groups.add(Group.objects.get(name="Tecnicos_Lideres"))
        cls.reader = User.objects.create_user(username="leitor_dashboard")
        cls.dashboard_perm = Permission.objects.get(codename="view_dashboard_matrizaria")
        cls.reader.user_permissions.add(cls.dashboard_perm)

    def setUp(self):
        self.params = {"periodo": "personalizado", "data_inicio": "2026-11-12", "data_fim": "2026-11-13"}
        self.url = reverse("matrizaria:dashboard")
        self.detail_url = reverse("matrizaria:dashboard_detalhes")

    def service(self, **overrides):
        form = DashboardFiltroForm({**self.params, **overrides})
        self.assertTrue(form.is_valid(), form.errors)
        return MatrizariaDashboardService(form.cleaned_data, self.now)

    def response(self, user=None, details=False, **params):
        self.client.force_login(user or self.lider_user)
        with patch("matrizaria.dashboard.timezone.now", return_value=self.now):
            return self.client.get(self.detail_url if details else self.url, {**self.params, **params})

    def test_metrics_use_period_events_and_distinct_requests(self):
        metrics = self.service().build()["metrics"]
        self.assertEqual(metrics["opened"], 2)
        self.assertEqual(metrics["completed"], 1)
        self.assertEqual(metrics["rejected"], 3)
        self.assertEqual(metrics["inspections"], 4)
        self.assertEqual(metrics["rejection_rate"], 75)
        self.assertEqual(metrics["cancelled"], 1)
        self.assertEqual(metrics["median_release"], "1d 13h")
        self.assertEqual(metrics["p90_release"], "1d 13h")

    def test_current_queue_includes_old_requests_and_marks_missing_history(self):
        data = self.service().build()
        self.assertEqual(data["metrics"]["pending"], 3)
        self.assertEqual(data["metrics"]["urgent"], 1)
        self.assertEqual(data["metrics"]["waiting"], 1)
        self.assertEqual(data["metrics"]["oldest"]["id"], self.waiting.pk)
        self.assertEqual(data["metrics"]["oldest_wait"], "3h 00m")
        self.assertEqual(data["metrics"]["incomplete"], 1)
        rows = {r["id"]: r for r in data["pending_rows"]}
        self.assertEqual(rows[self.waiting.pk]["phase_seconds"], 3 * 3600)
        self.assertEqual(rows[self.internal.pk]["phase_seconds"], 3600)
        self.assertEqual(rows[self.internal.pk]["responsible"], "Roberto Ferramenteiro")
        self.assertTrue(rows[self.incomplete.pk]["history_incomplete"])
        self.assertIsNone(rows[self.incomplete.pk]["phase_seconds"])

    def test_pareto_clamps_cross_day_and_open_cycles_without_inflating_requests(self):
        items = self.service().build()["pareto"]["items"]
        self.assertEqual([i["count"] for i in items], [2, 1])
        self.assertEqual(items[0]["seconds"], 5 * 3600)
        self.assertEqual(items[1]["seconds"], 3600)
        self.assertEqual(items[1]["label"], "Matrizaria / serviço interno")
        self.assertEqual(items[-1]["cumulative"], 100)

    def test_rework_counts_events_and_affected_requests(self):
        data = self.service().build()
        self.assertEqual(data["rework"][0]["count"], 3)
        self.assertEqual(data["rework"][0]["requests"], 2)
        self.assertEqual(data["daily"]["days"][0]["opened"], 1)
        self.assertEqual(data["daily"]["days"][1]["completed"], 1)

    def test_matrix_identity_is_not_inferred_from_snapshots(self):
        self.event(self.incomplete, "REJEICAO_RETRABALHO", "AGUARDANDO_CONFERENCIA",
                   "AGUARDANDO_RETRABALHO", self.dt(12, 12))
        SolicitacaoServicoMatrizaria.objects.filter(pk__in=[self.waiting.pk, self.incomplete.pk]).update(
            matriz_identificador_snapshot="Rótulo igual")
        data = self.service().build()
        self.assertEqual(len(data["rework"]), 2)
        self.assertEqual({i["label"] for i in data["rework"]}, {"MF-HOPPER-001", "MF-HOPPER-002"})

    def test_missing_matrix_gets_its_own_drilldown(self):
        self.event(self.internal, "REJEICAO_RETRABALHO", "AGUARDANDO_CONFERENCIA",
                   "AGUARDANDO_RETRABALHO", self.dt(13, 11, 45))
        data = self.service().build()
        item = next(i for i in data["rework"] if i["label"] == "Matriz não informada")
        self.assertIn("__SEM_MATRIZ__", item["url"])
        rows = self.service(visao="retrabalho", matriz="__SEM_MATRIZ__").detail_rows()
        self.assertEqual([r["id"] for r in rows], [self.internal.pk])

    def test_all_entity_filters_apply_to_period_and_current_queue(self):
        data = self.service(prensa=str(self.prensa_01.pk), tipo_servico=str(self.tipo_ajuste.pk),
                            matriz=str(self.matriz_fisica_01.pk), prioridade="URGENTE").build()
        self.assertEqual(data["metrics"]["opened"], 0)
        self.assertEqual(data["metrics"]["pending"], 1)
        self.assertEqual(data["metrics"]["rejected"], 1)
        data = self.service(prensa="__MATRIZARIA__").build()
        self.assertEqual(data["metrics"]["opened"], 1)
        self.assertEqual(data["metrics"]["pending"], 1)
        self.assertEqual(data["pareto"]["items"][0]["label"], "Matrizaria / serviço interno")

    def test_details_reconcile_each_selection(self):
        expected = {"abertas": {self.cancelled.pk, self.internal.pk}, "concluidas": {self.completed.pk},
                    "execucao": {self.waiting.pk, self.completed.pk, self.internal.pk},
                    "retrabalho": {self.waiting.pk, self.completed.pk},
                    "conferencias": {self.waiting.pk, self.completed.pk}, "canceladas": {self.cancelled.pk},
                    "fila": {self.waiting.pk, self.internal.pk, self.incomplete.pk}}
        for selection, ids in expected.items():
            with self.subTest(selection=selection):
                rows = self.service(visao=selection).detail_rows()
                self.assertEqual({r["id"] for r in rows}, ids)

    def test_daily_and_stage_drilldown(self):
        self.assertEqual([r["id"] for r in self.service(visao="abertas", dia="2026-11-13").detail_rows()], [self.internal.pk])
        self.assertEqual([r["id"] for r in self.service(visao="fila", estado="AGUARDANDO_CONFERENCIA").detail_rows()], [self.waiting.pk])

    def test_empty_period_shows_unknown_rate_and_keeps_current_queue(self):
        data = self.service(data_inicio="2026-11-03", data_fim="2026-11-03").build()
        self.assertIsNone(data["metrics"]["rejection_rate"])
        self.assertEqual(data["metrics"]["median_release"], "Sem dados")
        self.assertFalse(data["daily"]["has_data"])
        self.assertEqual(data["metrics"]["pending"], 3)

    def test_day_bounds_use_local_timezone_and_inclusive_end(self):
        for dt in (self.dt(12), self.dt(13, 23, 59), self.dt(14)):
            self.request_record(data_solicitacao=dt)
        service = self.service()
        service.now = self.dt(15)
        self.assertEqual(service.build()["metrics"]["opened"], 4)

    def test_query_count_is_constant_as_queue_grows(self):
        service = self.service()
        with CaptureQueriesContext(connection) as before:
            service.build()
        for index in range(25):
            self.request_record(descricao_solicitacao=f"Volume {index}")
        with CaptureQueriesContext(connection) as after:
            service.build()
        self.assertEqual(len(before), 4)
        self.assertEqual(len(after), len(before))

    def test_queue_ordering(self):
        rows = self.service(ordem="etapa").detail_rows()
        self.assertEqual([r["id"] for r in rows], [self.waiting.pk, self.internal.pk, self.incomplete.pk])
        rows = self.service(ordem="idade").detail_rows()
        self.assertEqual([r["id"] for r in rows], [self.waiting.pk, self.incomplete.pk, self.internal.pk])

    def test_both_leader_groups_have_migrated_permission(self):
        for user in (self.lider_user, self.technical_leader):
            with self.subTest(user=user.username):
                self.assertTrue(user.has_perm("matrizaria.view_dashboard_matrizaria"))
                self.assertEqual(self.response(user).status_code, 200)
                self.assertEqual(self.response(user, details=True).status_code, 200)

    def test_staff_and_operational_profiles_do_not_get_implicit_dashboard_access(self):
        staff = User.objects.create_user(username="staff_dashboard", is_staff=True)
        for user in (staff, self.tecnico_matrizaria_1, self.solicitante_user, self.tv_user, self.tecnico_maint_user):
            with self.subTest(user=user.username):
                self.assertEqual(self.response(user).status_code, 403)
                self.assertEqual(self.response(user, details=True).status_code, 403)

    def test_explicit_permission_and_superuser_access(self):
        admin = User.objects.create_superuser(username="admin_dashboard", email="", password="test")
        for user in (self.reader, admin):
            self.assertEqual(self.response(user).status_code, 200)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_dashboard_permission_only_allows_reading_other_requests(self):
        response = self.response(self.reader)
        self.assertContains(response, "Dashboard da Matrizaria")
        detail = self.client.get(reverse("matrizaria:detalhe_servico", args=[self.incomplete.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.context["can_editar"])
        self.assertFalse(detail.context["can_executar"])
        self.assertFalse(detail.context["can_conferir"])
        self.assertFalse(detail.context["can_cancelar"])
        for action in ("editar_solicitacao", "iniciar_atendimento", "cancelar_servico", "conferir_servico"):
            response = self.client.post(reverse("matrizaria:" + action, args=[self.incomplete.pk]), {
                "versao": self.incomplete.versao, "destino": "MAQUINA", "prensa": self.prensa_01.pk,
                "tipo_servico": self.tipo_ajuste.pk, "prioridade": "URGENTE",
                "descricao_solicitacao": "Alteração indevida pelo leitor",
                "motivo_edicao": "Justificativa de teste de permissão", "aprovado": True,
                "motivo_cancelamento": "Tentativa de cancelamento pelo leitor",
            })
            self.assertEqual(response.status_code, 302)
        self.incomplete.refresh_from_db()
        self.assertEqual(self.incomplete.status, "SOLICITADO")
        self.assertEqual(self.incomplete.descricao_solicitacao, "Dashboard")
        self.assertEqual(self.incomplete.prioridade, "NORMAL")

    def test_explicit_vulcanization_reader_can_read_other_requests(self):
        self.solicitante_user.user_permissions.add(self.dashboard_perm)
        self.client.force_login(self.solicitante_user)
        response = self.client.get(reverse("matrizaria:detalhe_servico", args=[self.waiting.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_executar"])

    def test_multiple_profiles_keep_leadership_authorization(self):
        self.technical_leader.groups.add(self.grp_vulc)
        self.technical_leader.groups.add(self.grp_tv_matriz)
        self.assertEqual(self.response(self.technical_leader).status_code, 200)
        self.assertRedirects(self.client.get(reverse("home_redirect")), reverse("portal_select"))

    def test_portal_and_single_module_landing_open_dashboard(self):
        self.client.force_login(self.technical_leader)
        response = self.client.get(reverse("portal_select"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{self.url}"')
        self.assertEqual(response.context["matrizaria_url"], "matrizaria:dashboard")
        self.assertEqual(response.context["maintenance_url"], "technician_management")
        self.client.force_login(self.reader)
        self.assertRedirects(self.client.get(reverse("home_redirect")), self.url)
        self.assertRedirects(self.client.get(reverse("portal_select")), self.url)

    def test_navigation_visibility_and_general_maintenance_dashboard_remains_restricted(self):
        response = self.response(self.technical_leader)
        self.assertNotContains(response, f'href="{reverse("matrizaria:kanban")}"')
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.tecnico_matrizaria_1)
        self.assertNotContains(self.client.get(reverse("matrizaria:kanban")), f'href="{self.url}"')

    def test_provisioning_is_idempotent_and_preserves_existing_leader_permissions(self):
        group = Group.objects.get(name="Tecnicos_Lideres")
        extra = Permission.objects.get(codename="view_machine")
        group.permissions.add(extra)
        for _ in range(2):
            call_command("provisionar_grupos_matrizaria", stdout=StringIO())
        self.assertTrue(group.permissions.filter(pk=self.dashboard_perm.pk).exists())
        self.assertTrue(group.permissions.filter(pk=extra.pk).exists())
        self.assertFalse(self.grp_vulc.permissions.filter(pk=self.dashboard_perm.pk).exists())
        self.assertFalse(self.grp_matrizaria.permissions.filter(pk=self.dashboard_perm.pk).exists())

    def test_invalid_filters_display_errors_without_broadening_results(self):
        for params in ({"data_inicio": "invalida"}, {"data_fim": "2026-11-01"},
                       {"data_inicio": ""}, {"data_fim": "2028-11-13"},
                       {"prensa": "999999"}, {"matriz": "999999"}, {"prioridade": "hack"},
                       {"visao": "inexistente"}, {"dia": "2026-11-14"}):
            with self.subTest(params=params):
                response = self.response(**params)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertNotIn("metrics", response.context)
                self.assertContains(response, "Revise os filtros")

    def test_presets_cover_inclusive_7_30_and_current_month(self):
        for preset, days in (("7", 7), ("30", 30), ("mes", None)):
            form = DashboardFiltroForm({"periodo": preset})
            self.assertTrue(form.is_valid(), form.errors)
            if days:
                self.assertEqual((form.cleaned_data["data_fim"] - form.cleaned_data["data_inicio"]).days + 1, days)
            else:
                self.assertEqual(form.cleaned_data["data_inicio"].day, 1)

    def test_details_paginate_forward_beyond_second_page_without_repeated_parameters(self):
        for index in range(45):
            self.request_record(descricao_solicitacao=f"Página {index}")
        self.client.force_login(self.lider_user)
        url = self.detail_url + "?periodo=personalizado&data_inicio=2026-11-12&data_fim=2026-11-13&visao=fila&ordem=idade"
        for expected in range(1, 4):
            response = self.client.get(url)
            self.assertEqual(response.context["page_obj"].number, expected)
            if expected < 3:
                match = re.search(r'href="([^"]+)"[^>]*>Próxima</a>', response.content.decode())
                self.assertIsNotNone(match)
                link = unescape(match.group(1))
                self.assertEqual(parse_qs(urlsplit(link).query)["page"], [str(expected + 1)])
                url = self.detail_url + link

    def test_empty_detail_renders_explanation(self):
        response = self.response(details=True, visao="abertas", prioridade="URGENTE")
        self.assertContains(response, "Nenhuma solicitação encontrada")

    def test_chart_links_resolve_to_authorized_equivalent_details(self):
        data = self.service(prioridade="URGENTE").build()
        urls = [data["daily"]["days"][0]["opened_url"], data["pareto"]["items"][0]["url"],
                data["rework"][0]["url"], data["stages"][2]["url"]]
        self.client.force_login(self.technical_leader)
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["form"].errors)
                self.assertIn("prioridade=URGENTE", url)

    def test_dashboard_post_is_not_allowed(self):
        self.client.force_login(self.lider_user)
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

    def test_urgent_drilldown_intersects_existing_priority_filter(self):
        response = self.response(prioridade="NORMAL")
        self.assertEqual(response.context["metrics"]["urgent"], 0)
        target = response.context["links"]["urgent"]
        self.assertIn("prioridade=NORMAL", target)
        response = self.client.get(target)
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_historical_machine_outside_current_press_catalog_remains_filterable(self):
        self.prensa_01.nome = "Equipamento histórico"
        self.prensa_01.setor = Sector.objects.create(nome="Setor histórico")
        self.prensa_01.save()
        data = self.service(prensa=str(self.prensa_01.pk)).build()
        self.assertEqual(data["pareto"]["items"][0]["count"], 2)

    def test_legacy_missing_machine_has_separate_filter(self):
        legacy = self.request_record(prensa=None, matriz_fisica=None, status="EM_EXECUCAO")
        self.cycle(legacy, 1, self.dt(13, 10), self.dt(13, 11))
        data = self.service(prensa="__SEM_PRENSA__").build()
        self.assertEqual(data["pareto"]["items"][0]["label"], "Prensa não informada")
        self.assertEqual([r["id"] for r in self.service(visao="execucao", prensa="__SEM_PRENSA__").detail_rows()], [legacy.pk])

    def test_future_period_has_no_execution_or_conference_results(self):
        data = self.service(data_inicio="2026-11-14", data_fim="2026-11-15").build()
        self.assertEqual(data["pareto"]["items"], [])
        self.assertEqual(data["metrics"]["completed"], 0)
        self.assertEqual(self.service(visao="execucao", data_inicio="2026-11-14", data_fim="2026-11-15").detail_rows(), [])

    def test_median_and_p90_use_completed_sample_durations(self):
        for hours in (1, 3, 10):
            created = self.dt(13, 11) - timedelta(hours=hours)
            request = self.request_record(status="CONCLUIDO", data_solicitacao=created)
            self.event(request, "CONFERENCIA_APROVADA", "AGUARDANDO_CONFERENCIA", "CONCLUIDO", self.dt(13, 11))
        metrics = self.service().build()["metrics"]
        self.assertEqual(metrics["median_release"], "6h 30m")
        self.assertEqual(metrics["p90_release"], "1d 13h")
        self.assertEqual(metrics["release_samples"], 4)

    def test_untrusted_labels_are_escaped_in_chart_and_table(self):
        self.tipo_ajuste.nome = '<script>alert("x")</script>'
        self.tipo_ajuste.save()
        response = self.response()
        self.assertNotContains(response, self.tipo_ajuste.nome)
        self.assertContains(response, "&lt;script&gt;")
