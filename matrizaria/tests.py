from datetime import datetime, date, time, timedelta
from html import unescape
import re
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch
import openpyxl
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from django.db.models import ProtectedError
from maintenance.models import Sector, Machine
from production.models import ProductionMatrixCatalog
from matrizaria.models import (
    TipoServicoMatrizaria,
    MatrizFisica,
    SolicitacaoServicoMatrizaria,
    CicloExecucaoMatrizaria,
    HistoricoTransicaoServicoMatrizaria,
)
from matrizaria.services import MatrizariaService, AdminCascadeDeletionService
from matrizaria.views import sanitize_excel_cell

User = get_user_model()


class MatrizariaBaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 1. Setor e Máquina
        cls.sector_vulc = Sector.objects.create(nome="VULCANIZAÇÃO")
        cls.prensa_01 = Machine.objects.create(
            nome="PRENSA BOM 01",
            setor=cls.sector_vulc,
            criticidade="ALTA",
        )
        cls.prensa_02 = Machine.objects.create(
            nome="PRENSA BOM 02",
            setor=cls.sector_vulc,
            criticidade="MEDIA",
        )

        # 2. Catálogo Canônico de Matrizes
        cls.cat_hopper, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=1,
            defaults={
                "nome_scada": "HOPPER 90/90-18",
                "nome_exibicao": "HOPPER 90/90-18",
                "ativo": True,
            },
        )

        # 3. Exemplar Físico de Matriz
        cls.matriz_fisica_01 = MatrizFisica.objects.create(
            modelo=cls.cat_hopper,
            identificador_estavel="MF-HOPPER-001",
            numero_sequencial=1,
            ativo=True,
        )

        # 4. Tipos de Serviço
        cls.tipo_troca = TipoServicoMatrizaria.objects.create(
            nome="Troca de Matriz Programada",
            descricao="Troca preventiva do ferramental",
            exige_matriz_fisica=True,
            ativo=True,
            ordem_exibicao=1,
        )
        cls.tipo_ajuste = TipoServicoMatrizaria.objects.create(
            nome="Ajuste Mecânico de Prensa",
            descricao="Alinhamento sem troca de matriz",
            exige_matriz_fisica=False,
            ativo=True,
            ordem_exibicao=2,
        )

        # 5. Grupos de Usuários
        cls.grp_matrizaria, _ = Group.objects.get_or_create(name="Matrizaria")
        cls.grp_vulc, _ = Group.objects.get_or_create(name="Operadores Vulcanização")
        cls.grp_lider, _ = Group.objects.get_or_create(name="Liderança de Produção")
        cls.grp_maint, _ = Group.objects.get_or_create(name="Tecnicos")
        cls.grp_tv_matriz, _ = Group.objects.get_or_create(name="Visualizador Matrizaria")

        # 6. Usuários
        cls.solicitante_user = User.objects.create_user(
            username="op_vulc", password="password123", first_name="Operador", last_name="Vulcanizador"
        )
        cls.solicitante_user.groups.add(cls.grp_vulc)

        cls.tecnico_matrizaria_1 = User.objects.create_user(
            username="tec_matriz_1", password="password123", first_name="Carlos", last_name="Matrizaria"
        )
        cls.tecnico_matrizaria_1.groups.add(cls.grp_matrizaria)

        cls.tecnico_matrizaria_2 = User.objects.create_user(
            username="tec_matriz_2", password="password123", first_name="Roberto", last_name="Ferramenteiro"
        )
        cls.tecnico_matrizaria_2.groups.add(cls.grp_matrizaria)

        cls.lider_user = User.objects.create_user(
            username="lider_prod", password="password123", first_name="Marcos", last_name="Líder"
        )
        cls.lider_user.groups.add(cls.grp_lider)
        perm_view = Permission.objects.get(
            codename="view_solicitacaoservicomatrizaria",
            content_type__app_label="matrizaria",
        )
        cls.lider_user.user_permissions.add(perm_view)

        cls.tecnico_maint_user = User.objects.create_user(
            username="tec_maint", password="password123", first_name="Pedro", last_name="Mecânico"
        )
        cls.tecnico_maint_user.groups.add(cls.grp_maint)

        cls.tv_user = User.objects.create_user(
            username="tv_matrizaria", password="password123"
        )
        cls.tv_user.groups.add(cls.grp_tv_matriz)


class MatrizariaModelAndSnapshotTestCase(MatrizariaBaseTestCase):
    def test_matriz_fisica_string_and_formatting(self):
        expected_name = f"{self.cat_hopper.nome_exibicao} #001"
        self.assertEqual(self.matriz_fisica_01.numero_sequencial_str, "001")
        self.assertEqual(self.matriz_fisica_01.nome_exibicao, expected_name)
        self.assertEqual(str(self.matriz_fisica_01), expected_name)

    def test_matriz_fisica_unique_constraints(self):
        # Mesma matriz e número sequencial duplicado deve falhar
        with self.assertRaises(Exception):
            MatrizFisica.objects.create(
                modelo=self.cat_hopper,
                identificador_estavel="MF-HOPPER-DUPLICADO",
                numero_sequencial=1,
            )

    def test_solicitacao_snapshots_preserve_history_when_catalogs_change(self):
        expected_matriz_name = f"{self.cat_hopper.nome_exibicao} #001"
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_troca,
            descricao_solicitacao="Trocar matriz com desgaste",
            solicitado_por=self.solicitante_user,
            matriz_fisica=self.matriz_fisica_01,
        )

        self.assertEqual(sol.prensa_nome_snapshot, "PRENSA BOM 01")
        self.assertEqual(sol.tipo_servico_nome_snapshot, "Troca de Matriz Programada")
        self.assertEqual(sol.solicitado_por_nome, "Operador Vulcanizador")
        self.assertEqual(sol.matriz_identificador_snapshot, expected_matriz_name)
        self.assertTrue(sol.exige_matriz_fisica_snapshot)

        # Alteração posterior no cadastro da máquina ou tipo não deve alterar o snapshot
        self.prensa_01.nome = "PRENSA BOM 01 RENOMEADA"
        self.prensa_01.save()

        self.tipo_troca.nome = "Tipo de Serviço Renomeado"
        self.tipo_troca.exige_matriz_fisica = False
        self.tipo_troca.save()

        sol.refresh_from_db()
        self.assertEqual(sol.prensa_nome_snapshot, "PRENSA BOM 01")
        self.assertEqual(sol.tipo_servico_nome_snapshot, "Troca de Matriz Programada")
        self.assertTrue(sol.exige_matriz_fisica_snapshot)


class MatrizariaWorkflowAndCyclesTestCase(MatrizariaBaseTestCase):
    def test_complete_lifecycle_including_rework_and_cycles(self):
        # 1. Abertura
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_troca,
            descricao_solicitacao="Troca de molde",
            solicitado_por=self.solicitante_user,
            prioridade="NORMAL",
        )
        self.assertEqual(sol.status, "SOLICITADO")
        self.assertEqual(sol.versao, 1)
        self.assertEqual(sol.ciclos_execucao.count(), 0)

        # 2. Início do Atendimento (Abre Ciclo 1)
        sol = MatrizariaService.iniciar_atendimento(
            solicitacao_id=sol.id,
            usuario=self.tecnico_matrizaria_1,
            versao_esperada=sol.versao,
        )
        self.assertEqual(sol.status, "EM_EXECUCAO")
        self.assertEqual(sol.responsavel_atribuido, self.tecnico_matrizaria_1)
        self.assertEqual(sol.ciclos_execucao.count(), 1)
        c1 = sol.ciclos_execucao.first()
        self.assertEqual(c1.numero_ciclo, 1)
        self.assertEqual(c1.usuario_inicio, self.tecnico_matrizaria_1)
        self.assertEqual(c1.forma_encerramento, "EM_ANDAMENTO")

        # 3. Finalização sem informar matriz quando exigida deve falhar
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.finalizar_execucao(
                solicitacao_id=sol.id,
                usuario=self.tecnico_matrizaria_1,
                descricao_servico_realizado="Instalada matriz",
                matriz_fisica=None,
                versao_esperada=sol.versao,
            )
        self.assertIn("exige a identificação da Matriz Física", str(ctx.exception))

        # 4. Finalização válida (Encerra Ciclo 1 com FINALIZADO_TECNICO)
        sol = MatrizariaService.finalizar_execucao(
            solicitacao_id=sol.id,
            usuario=self.tecnico_matrizaria_1,
            descricao_servico_realizado="Matriz instalada com alinhamento e vapor conectado",
            matriz_fisica=self.matriz_fisica_01,
            versao_esperada=sol.versao,
        )
        self.assertEqual(sol.status, "AGUARDANDO_CONFERENCIA")
        c1.refresh_from_db()
        self.assertEqual(c1.forma_encerramento, "FINALIZADO_TECNICO")
        self.assertEqual(c1.usuario_fim, self.tecnico_matrizaria_1)
        self.assertIsNotNone(c1.data_fim)

        # 5. Conferência: Reprovação para Retrabalho por Líder
        sol = MatrizariaService.conferir_solicitacao(
            solicitacao_id=sol.id,
            usuario_conferente=self.lider_user,
            aprovado=False,
            versao_esperada=sol.versao,
            observacao="Vazamento de vapor detectado na conexão traseira",
        )
        self.assertEqual(sol.status, "AGUARDANDO_RETRABALHO")
        self.assertEqual(sol.quantidade_retrabalhos, 1)

        # 6. Início do Retrabalho (Abre Ciclo 2, preservando Ciclo 1)
        sol = MatrizariaService.iniciar_atendimento(
            solicitacao_id=sol.id,
            usuario=self.tecnico_matrizaria_2,
            versao_esperada=sol.versao,
        )
        self.assertEqual(sol.status, "EM_EXECUCAO")
        self.assertEqual(sol.ciclos_execucao.count(), 2)

        ciclos = list(sol.ciclos_execucao.order_by("numero_ciclo"))
        self.assertEqual(ciclos[0].numero_ciclo, 1)
        self.assertEqual(ciclos[0].forma_encerramento, "FINALIZADO_TECNICO")
        self.assertEqual(ciclos[1].numero_ciclo, 2)
        self.assertEqual(ciclos[1].usuario_inicio, self.tecnico_matrizaria_2)
        self.assertEqual(ciclos[1].forma_encerramento, "EM_ANDAMENTO")

        # 7. Finalização do Retrabalho
        sol = MatrizariaService.finalizar_execucao(
            solicitacao_id=sol.id,
            usuario=self.tecnico_matrizaria_2,
            descricao_servico_realizado="Substituída vedação de vapor e reapertada flange",
            matriz_fisica=self.matriz_fisica_01,
            versao_esperada=sol.versao,
        )
        self.assertEqual(sol.status, "AGUARDANDO_CONFERENCIA")

        # 8. Aprovação Final por Líder
        sol = MatrizariaService.conferir_solicitacao(
            solicitacao_id=sol.id,
            usuario_conferente=self.lider_user,
            aprovado=True,
            versao_esperada=sol.versao,
            observacao="Aprovado sem vazamentos, prensa liberada para produção",
        )
        self.assertEqual(sol.status, "CONCLUIDO")
        self.assertEqual(sol.conferido_por, self.lider_user)

        # Transição adicional após concluído deve ser bloqueada
        with self.assertRaises(ValidationError):
            MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, sol.versao)

    def test_cancellation_during_execution_interrupts_active_cycle(self):
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_02,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Ajuste na prensa 02",
            solicitado_por=self.solicitante_user,
        )
        sol = MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, sol.versao)

        # Cancelamento durante execução técnica
        sol = MatrizariaService.cancelar_solicitacao(
            solicitacao_id=sol.id,
            usuario=self.lider_user,
            versao_esperada=sol.versao,
            motivo_cancelamento="Ordem de produção suspensa pela diretoria",
        )
        self.assertEqual(sol.status, "CANCELADO")
        c = sol.ciclos_execucao.first()
        self.assertEqual(c.forma_encerramento, "INTERROMPIDO_CANCELAMENTO")
        self.assertIn("Interrompido por cancelamento", c.descricao_servico_executado)
        self.assertIsNotNone(c.data_fim)


class MatrizariaSecurityAndAntiSelfInspectionTestCase(MatrizariaBaseTestCase):
    def test_anti_self_inspection_blocks_execution_participants(self):
        # Técnico que executou não pode aprovar
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Ajuste teste",
            solicitado_por=self.solicitante_user,
        )
        sol = MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, sol.versao)
        sol = MatrizariaService.finalizar_execucao(
            solicitacao_id=sol.id,
            usuario=self.tecnico_matrizaria_1,
            descricao_servico_executado="Ajuste técnico concluído com sucesso",
            matriz_fisica=None,
            versao_esperada=sol.versao,
        )

        # Técnico tenta aprovar o próprio serviço
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.conferir_solicitacao(
                solicitacao_id=sol.id,
                usuario_conferente=self.tecnico_matrizaria_1,
                aprovado=True,
                versao_esperada=sol.versao,
            )
        self.assertIn("Regra de Segregação de Funções", str(ctx.exception))

    def test_transfer_of_responsibility_audited(self):
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Troca de turno",
            solicitado_por=self.solicitante_user,
        )
        sol = MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, sol.versao)

        # Transfere para técnico 2
        sol = MatrizariaService.transferir_responsabilidade(
            solicitacao_id=sol.id,
            usuario_origem=self.tecnico_matrizaria_1,
            novo_responsavel=self.tecnico_matrizaria_2,
            motivo="Fim de turno técnico 1",
            versao_esperada=sol.versao,
        )
        self.assertEqual(sol.responsavel_atribuido, self.tecnico_matrizaria_2)
        # O autor do início original continua sendo o técnico 1
        self.assertEqual(sol.iniciado_por, self.tecnico_matrizaria_1)

        # Histórico gravado
        h = sol.historico_transicoes.filter(tipo_evento="TRANSFERENCIA").first()
        self.assertIsNotNone(h)
        self.assertIn("Transferência de responsabilidade", h.observacao)


class MatrizariaConcurrencyTestCase(MatrizariaBaseTestCase):
    def test_stale_version_triggers_concurrency_error(self):
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Teste concorrencia",
            solicitado_por=self.solicitante_user,
        )
        versao_antiga = sol.versao

        # Primeiro usuário inicia com sucesso
        MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, versao_antiga)

        # Segundo usuário tenta agir com a versão antiga (stale)
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_2, versao_antiga)
        self.assertIn("Conflito de concorrência", str(ctx.exception))


class MatrizariaReportingAndTemporalTestCase(MatrizariaBaseTestCase):
    def test_temporal_scenario_execution_crossing_dates(self):
        """
        Cenário Temporal:
        - Abertura no dia 10
        - Execução no dia 11
        - Conferência no dia 12
        - Relatório de execução (COM_EXECUCAO) do dia 11 deve encontrar o chamado.
        - Relatório de execução do dia 10 NÃO deve encontrar (pois dia 10 teve apenas espera).
        """
        d10 = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
        d11_ini = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
        d11_fim = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
        d12 = datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)

        sol = SolicitacaoServicoMatrizaria.objects.create(
            prensa=self.prensa_01,
            prensa_nome_snapshot=self.prensa_01.nome,
            tipo_servico=self.tipo_ajuste,
            tipo_servico_nome_snapshot=self.tipo_ajuste.nome,
            descricao_solicitacao="Teste temporal",
            solicitado_por=self.solicitante_user,
            solicitado_por_nome="Solicitante",
            data_solicitacao=d10,
            status="CONCLUIDO",
            conferido_por=self.lider_user,
            data_conferencia=d12,
            data_inicio_execucao=d11_ini,
            data_fim_execucao=d11_fim,
        )

        CicloExecucaoMatrizaria.objects.create(
            solicitacao=sol,
            numero_ciclo=1,
            usuario_inicio=self.tecnico_matrizaria_1,
            usuario_inicio_nome="Tecnico 1",
            data_inicio=d11_ini,
            usuario_fim=self.tecnico_matrizaria_1,
            usuario_fim_nome="Tecnico 1",
            data_fim=d11_fim,
            forma_encerramento="FINALIZADO_TECNICO",
            descricao_servico_executado="Servico executado dia 11",
        )

        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=sol,
            status_anterior="SOLICITADO",
            status_novo="EM_EXECUCAO",
            tipo_evento="INICIO",
            data_evento=d11_ini,
        )
        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=sol,
            status_anterior="EM_EXECUCAO",
            status_novo="CONCLUIDO",
            tipo_evento="CONFERENCIA_APROVADA",
            data_evento=d12,
        )

        # Consulta COM_EXECUCAO para o dia 11 (deve encontrar)
        res_dia11 = MatrizariaService.consultar_relatorio(
            criterio_temporal="COM_EXECUCAO",
            data_inicio=date(2026, 9, 11),
            data_fim=date(2026, 9, 11),
        )
        ids_dia11 = [r["id"] for r in res_dia11]
        self.assertIn(sol.id, ids_dia11)

        # Consulta COM_EXECUCAO para o dia 10 (apenas espera, não teve execução)
        res_dia10 = MatrizariaService.consultar_relatorio(
            criterio_temporal="COM_EXECUCAO",
            data_inicio=date(2026, 9, 10),
            data_fim=date(2026, 9, 10),
        )
        ids_dia10 = [r["id"] for r in res_dia10]
        self.assertNotIn(sol.id, ids_dia10)

        # Reconstituição do status histórico no fim do dia 11:
        item_dia11 = [r for r in res_dia11 if r["id"] == sol.id][0]
        self.assertEqual(item_dia11["status_atual"], "CONCLUIDO")
        self.assertEqual(item_dia11["status_fim_periodo"], "EM_EXECUCAO")


class MatrizariaReportPaginationTestCase(MatrizariaBaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        now = timezone.now()
        SolicitacaoServicoMatrizaria.objects.bulk_create([
            SolicitacaoServicoMatrizaria(
                prensa=cls.prensa_01,
                tipo_servico=cls.tipo_ajuste,
                solicitado_por=cls.solicitante_user,
                descricao_solicitacao=f"Paginação {i}",
                status="EM_EXECUCAO",
                data_solicitacao=now - timedelta(minutes=i + 2),
            )
            for i in range(161)
        ])
        cls.report_ids = set(SolicitacaoServicoMatrizaria.objects.values_list("id", flat=True))
        CicloExecucaoMatrizaria.objects.bulk_create([
            CicloExecucaoMatrizaria(
                solicitacao_id=pk,
                numero_ciclo=1,
                usuario_inicio=cls.tecnico_matrizaria_1,
                data_inicio=now - timedelta(minutes=1),
            )
            for pk in cls.report_ids
        ])

    def setUp(self):
        self.client.force_login(self.lider_user)
        self.url = reverse("matrizaria:relatorios")

    def _pagination_link(self, response, label, page, filters):
        match = re.search(
            rf'href="([^"]+)"[^>]*>\s*{label}</a>',
            response.content.decode(),
        )
        self.assertIsNotNone(match, f"Link {label} não encontrado")
        link = unescape(match.group(1))
        params = parse_qs(urlsplit(link).query, keep_blank_values=True)
        self.assertEqual(params.pop("page"), [str(page)])
        self.assertEqual(params, filters)
        return link

    def _visit_all_pages(self, filters):
        expected_filters = parse_qs(urlencode(filters), keep_blank_values=True)
        response = self.client.get(self.url, filters)
        seen_ids = []
        for number in range(1, 10):
            self.assertEqual(response.status_code, 200)
            page = response.context["page_obj"]
            self.assertEqual(page.number, number)
            self.assertEqual(page.paginator.num_pages, 9)
            seen_ids.extend(item["id"] for item in page)
            if number < 9:
                link = self._pagination_link(response, "Próxima", number + 1, expected_filters)
                response = self.client.get(self.url + link)
        self.assertEqual(len(seen_ids), 161)
        self.assertEqual(set(seen_ids), self.report_ids)
        self.assertNotContains(response, ">Próxima</a>")
        return response, expected_filters

    def test_navigate_nine_pages_without_filters(self):
        self._visit_all_pages({})

    def test_navigate_nine_pages_forward_and_backward_preserving_all_filters(self):
        today = timezone.localdate()
        filters = {
            "criterio_temporal": "COM_EXECUCAO",
            "data_inicio": (today - timedelta(days=7)).isoformat(),
            "data_fim": today.isoformat(),
            "prensa": str(self.prensa_01.pk),
            "tipo_servico": str(self.tipo_ajuste.pk),
            "status": "EM_EXECUCAO",
            "solicitante": str(self.solicitante_user.pk),
            "executante": str(self.tecnico_matrizaria_1.pk),
        }
        response, expected_filters = self._visit_all_pages(filters)
        for number in range(8, 0, -1):
            link = self._pagination_link(response, "Anterior", number, expected_filters)
            response = self.client.get(self.url + link)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["page_obj"].number, number)
        self.assertNotContains(response, ">Anterior</a>")

    def test_existing_duplicate_page_parameters_are_not_propagated(self):
        response = self.client.get(self.url + "?page=3&page=2&status=EM_EXECUCAO")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)
        filters = {"status": ["EM_EXECUCAO"]}
        self._pagination_link(response, "Anterior", 1, filters)
        self._pagination_link(response, "Próxima", 3, filters)

    def test_invalid_page_numbers_keep_paginator_fallback(self):
        for value, expected in [("invalida", 1), ("0", 9), ("999", 9)]:
            with self.subTest(page=value):
                response = self.client.get(self.url, {"page": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].number, expected)


class MatrizariaExcelAndExportTestCase(MatrizariaBaseTestCase):
    def test_excel_export_creates_two_sheets_and_sanitizes_formulas(self):
        client = Client()
        client.force_login(self.lider_user)

        # Cria solicitação com texto iniciando em sinal de fórmula
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="=1+1 perigo de formula",
            solicitado_por=self.solicitante_user,
        )

        res = client.get(reverse("matrizaria:exportar_excel"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # Reabre a planilha para validação rigorosa
        import io
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        self.assertIn("Serviços", wb.sheetnames)
        self.assertIn("Histórico", wb.sheetnames)

        # Sanitização de fórmula
        self.assertEqual(sanitize_excel_cell("=1+1"), "'=1+1")
        self.assertEqual(sanitize_excel_cell("+5511"), "'+5511")
        self.assertEqual(sanitize_excel_cell("-100"), "'-100")
        self.assertEqual(sanitize_excel_cell("@usuario"), "'@usuario")
        self.assertEqual(sanitize_excel_cell("Texto Normal"), "Texto Normal")


class MatrizariaTVAndIsolationTestCase(MatrizariaBaseTestCase):
    def test_tv_view_and_scada_resilience(self):
        client = Client()
        client.force_login(self.tv_user)

        # Rota de TV carrega 200 OK
        res = client.get(reverse("matrizaria:tv"))
        self.assertEqual(res.status_code, 200)

        # API JSON da TV
        res_api = client.get(reverse("matrizaria:api_tv_data"))
        self.assertEqual(res_api.status_code, 200)
        data = res_api.json()
        self.assertIn("servicos", data)
        self.assertIn("bladder_alerts", data)

        # Falha de telemetria SCADA isolada
        with patch("production.services.BladderTrackingService.get_active_bladders_context", side_effect=Exception("Timeout no SCADA")):
            ctx = MatrizariaService.get_tv_dashboard_context()
            self.assertEqual(ctx["scada_status"], "OFFLINE")
            self.assertIn("Timeout no SCADA", ctx["scada_mensagem"])
            # Serviços continuam funcionando normalmente!
            self.assertIn("servicos", ctx)


class MatrizariaRouterAndMultiContextTestCase(MatrizariaBaseTestCase):
    def test_routing_and_portal_redirects(self):
        client = Client()

        # 1. Usuário exclusivo da TV Matrizaria -> /matrizaria/tv/
        client.force_login(self.tv_user)
        res_tv = client.get(reverse("home_redirect"))
        self.assertRedirects(res_tv, reverse("matrizaria:tv"))

        # 2. Usuário com 1 módulo (solicitante_user: vulcanização exclusiva -> minhas_solicitacoes)
        client.force_login(self.solicitante_user)
        res_single = client.get(reverse("home_redirect"))
        self.assertRedirects(res_single, reverse("matrizaria:minhas_solicitacoes"))

        # 2.1 Usuário da oficina (tecnico_matrizaria_1: apenas matrizaria -> kanban)
        client.force_login(self.tecnico_matrizaria_1)
        res_tech = client.get(reverse("home_redirect"))
        self.assertRedirects(res_tech, reverse("matrizaria:kanban"))

        # 3. Usuário com múltiplos módulos (lider_user -> tem produção e matrizaria)
        client.force_login(self.lider_user)
        res_multi = client.get(reverse("home_redirect"))
        self.assertRedirects(res_multi, reverse("portal_select"))


class MatrizariaFixesTestCase(MatrizariaBaseTestCase):
    """
    Testes específicos para validar as três correções solicitadas:
    1. Exclusão de CHECK-LIST e simplificação dos rótulos de prensas (sem criticidade entre parênteses).
    2. Rejeição de CHECK-LIST via formulário, serviço e modelo.
    3. Assinatura do desenvolvedor Paulo Sérgio nos templates compartilhados.
    """

    def test_prensa_label_and_checklist_exclusion(self):
        from matrizaria.forms import get_prensas_queryset, format_prensa_label, is_checklist_machine, SolicitacaoServicoForm

        # Cria registros de teste de CHECK-LIST
        chk_1 = Machine.objects.create(nome="CHECK-LIST", setor=self.sector_vulc, criticidade="BAIXA")
        chk_2 = Machine.objects.create(nome="check list", setor=self.sector_vulc, criticidade="BAIXA")
        chk_3 = Machine.objects.create(nome="Checklist", setor=self.sector_vulc, criticidade="BAIXA")

        # Verifica helper
        self.assertTrue(is_checklist_machine(chk_1))
        self.assertTrue(is_checklist_machine(chk_2))
        self.assertTrue(is_checklist_machine(chk_3))
        self.assertFalse(is_checklist_machine(self.prensa_01))

        # QuerySet de prensas não deve conter nenhum CHECK-LIST
        prensas_qs = get_prensas_queryset()
        self.assertNotIn(chk_1, prensas_qs)
        self.assertNotIn(chk_2, prensas_qs)
        self.assertNotIn(chk_3, prensas_qs)
        self.assertIn(self.prensa_01, prensas_qs)

        # Rótulo simplificado não deve conter parênteses residuais
        label_01 = format_prensa_label(self.prensa_01)
        self.assertEqual(label_01, "PRENSA BOM 01")
        self.assertNotIn("(", label_01)
        self.assertNotIn(")", label_01)

        # Máquina com hífen e nome composto
        prensa_robot = Machine.objects.create(nome="PRENSA BOM - ROBOT", setor=self.sector_vulc, criticidade="ALTA")
        label_robot = format_prensa_label(prensa_robot)
        self.assertEqual(label_robot, "PRENSA BOM - ROBOT")

        # Rejeição via formulário de nova solicitação
        form_data = {
            "prensa": chk_1.id,
            "tipo_servico": self.tipo_troca.id,
            "descricao_solicitacao": "Teste de tentativa de abertura com CHECK-LIST",
            "prioridade": "NORMAL",
        }
        form = SolicitacaoServicoForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("prensa", form.errors)

        # Rejeição via serviço
        with self.assertRaises(ValidationError):
            MatrizariaService.criar_solicitacao(
                prensa=chk_1,
                tipo_servico=self.tipo_troca,
                descricao_solicitacao="Tentativa de serviço",
                solicitado_por=self.solicitante_user,
            )

        # Rejeição via Model.clean()
        sol_invalid = SolicitacaoServicoMatrizaria(
            prensa=chk_1,
            tipo_servico=self.tipo_troca,
            descricao_solicitacao="Tentativa direta no model",
            solicitado_por=self.solicitante_user,
        )
        with self.assertRaises(ValidationError):
            sol_invalid.clean()

    def test_developer_footer_presence_across_templates(self):
        from django.template.loader import render_to_string

        templates_to_test = [
            ("maintenance/login.html", {}),
            ("maintenance/portal_select.html", {"accessible_modules": ["matrizaria"], "can_access_matrizaria": True}),
            ("maintenance/base.html", {}),
            ("production/base_production.html", {}),
            ("matrizaria/base_matrizaria.html", {}),
            ("matrizaria/kanban.html", {"fila_solicitados": [], "fila_execucao": [], "fila_conferencia": [], "fila_concluidos": []}),
            ("matrizaria/form_solicitacao.html", {}),
            ("matrizaria/relatorios.html", {"page_obj": []}),
            ("matrizaria/tv.html", MatrizariaService.get_tv_dashboard_context()),
            ("maintenance/tv_dashboard.html", {"technicians": []}),
            ("admin/base_site.html", {}),
        ]

        for template_name, ctx in templates_to_test:
            ctx["user"] = self.lider_user
            rendered = render_to_string(template_name, ctx)
            self.assertIn("Desenvolvido por", rendered, f"Assinatura ausente em {template_name}")
            self.assertIn("Paulo Sérgio", rendered, f"Nome do desenvolvedor ausente em {template_name}")
            # Garante que não foi duplicado
            self.assertEqual(rendered.count("Paulo Sérgio"), 1, f"Assinatura duplicada em {template_name}")


class MatrizariaCincoAjustesTestCase(MatrizariaBaseTestCase):
    """
    Testes automatizados cobrindo os 5 novos ajustes implementados:
    1. TV: renderização completa do HTML das colunas no polling, inclusão de retrabalhos em solicitados, fuso horário local.
    2. Cancelados: critério CANCELADAS filtrando por data de cancelamento, compatibilidade com histórico/execução, exportação Excel.
    3. Sessão e TV: middleware de inatividade humana (5 min), isenção para conta de TV exclusiva, endpoints keep-alive e status.
    4. Edição de Solicitação: apenas quando SOLICITADO e sem ciclos iniciados, verificação de concorrência, auditoria de diff.
    5. Transferência: listagem restrita a matrizeiros habilitados (grupo Matrizaria ativo, excluindo atual e contas TV).
    """

    def test_item1_tv_api_renders_column_html_and_local_timezone(self):
        # 1. Cria duas solicitações
        sol_1 = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_troca,
            descricao_solicitacao="Troca de matriz urgente para BOM 01",
            solicitado_por=self.solicitante_user,
            prioridade="URGENTE",
        )
        sol_2 = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_02,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Ajuste operacional para BOM 02",
            solicitado_por=self.solicitante_user,
            prioridade="NORMAL",
        )

        client = Client()
        client.force_login(self.tv_user)

        # 2. Chama endpoint de API que alimenta a TV
        res = client.get(reverse("matrizaria:api_tv_data"))
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Verifica contadores
        self.assertEqual(data["servicos"]["total_solicitados"], 2)

        # Verifica que o HTML das colunas é gerado e retornado
        self.assertIn("html_solicitados", data)
        self.assertIn("html_execucao", data)
        self.assertIn("html_conferencia", data)
        self.assertIn("html_bladders", data)

        # Ambos os chamados devem estar presentes no HTML da coluna solicitados
        self.assertIn("Troca de matriz urgente para BOM 01", data["html_solicitados"])
        self.assertIn("Ajuste operacional para BOM 02", data["html_solicitados"])
        self.assertIn("PRENSA BOM 01", data["html_solicitados"])
        self.assertIn("PRENSA BOM 02", data["html_solicitados"])

        # 3. Verifica consistência de timezone no contexto da TV
        ctx = MatrizariaService.get_tv_dashboard_context()
        now_local = timezone.localtime(timezone.now())
        self.assertEqual(ctx["hora_atual"], now_local.strftime("%H:%M"))

    def test_item2_chamados_cancelados_relatorio_e_excel(self):
        # 1. Chamado cancelado ANTES de qualquer início
        sol_pre = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Cancelado antes do inicio",
            solicitado_por=self.solicitante_user,
        )
        sol_pre = MatrizariaService.cancelar_solicitacao(
            solicitacao_id=sol_pre.id,
            usuario=self.lider_user,
            versao_esperada=sol_pre.versao,
            motivo_cancelamento="Planejamento cancelou ordem da prensa 01",
        )

        # 2. Chamado cancelado DEPOIS de iniciado
        sol_exec = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_02,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Cancelado durante execucao",
            solicitado_por=self.solicitante_user,
        )
        sol_exec = MatrizariaService.iniciar_atendimento(sol_exec.id, self.tecnico_matrizaria_1, sol_exec.versao)
        sol_exec = MatrizariaService.cancelar_solicitacao(
            solicitacao_id=sol_exec.id,
            usuario=self.lider_user,
            versao_esperada=sol_exec.versao,
            motivo_cancelamento="Prensa apresentou falha eletrica externa",
        )

        # 3. Consulta de relatório por 'CANCELADAS'
        hoje = timezone.localdate()
        rel = MatrizariaService.consultar_relatorio(
            criterio_temporal="CANCELADAS",
            data_inicio=hoje,
            data_fim=hoje,
        )
        ids_rel = [r["id"] for r in rel]
        self.assertIn(sol_pre.id, ids_rel)
        self.assertIn(sol_exec.id, ids_rel)

        # Verifica dados de cancelamento retornados no relatório
        item_pre = [r for r in rel if r["id"] == sol_pre.id][0]
        self.assertEqual(item_pre["cancelado_por_nome"], "Marcos Líder")
        self.assertEqual(item_pre["motivo_cancelamento"], "Planejamento cancelou ordem da prensa 01")
        self.assertIsNotNone(item_pre["data_cancelamento"])

        item_exec = [r for r in rel if r["id"] == sol_exec.id][0]
        self.assertEqual(item_exec["cancelado_por_nome"], "Marcos Líder")
        self.assertEqual(item_exec["motivo_cancelamento"], "Prensa apresentou falha eletrica externa")
        # Ciclo interrompido sem inventar término fictício de execução com sucesso
        ciclo_cancelado = sol_exec.ciclos_execucao.first()
        self.assertEqual(ciclo_cancelado.forma_encerramento, "INTERROMPIDO_CANCELAMENTO")

        # 4. Exportação Excel para chamados cancelados
        client = Client()
        client.force_login(self.lider_user)
        res_excel = client.get(reverse("matrizaria:exportar_excel") + "?criterio_temporal=CANCELADAS")
        self.assertEqual(res_excel.status_code, 200)
        self.assertEqual(
            res_excel["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_item3_logout_inatividade_middleware_e_perfil_tv(self):
        from maintenance.middleware import is_dedicated_tv_account

        # 1. Conta TV exclusiva é reconhecida
        self.assertTrue(is_dedicated_tv_account(self.tv_user))

        # 2. Usuário com grupo TV mas também grupo operacional NÃO é isento
        self.tv_user.groups.add(self.grp_matrizaria)
        self.assertFalse(is_dedicated_tv_account(self.tv_user))
        self.tv_user.groups.remove(self.grp_matrizaria)

        # 3. Superusuário ou Staff NÃO é conta TV exclusiva
        admin_tv = User.objects.create_superuser(username="admin_tv", password="password123", email="")
        admin_tv.groups.add(self.grp_tv_matriz)
        self.assertFalse(is_dedicated_tv_account(admin_tv))

        # 4. Endpoints de sessão
        client = Client()
        client.force_login(self.solicitante_user)

        # Status para usuário humano
        res_status = client.get(reverse("api_session_status"))
        self.assertEqual(res_status.status_code, 200)
        data_status = res_status.json()
        self.assertTrue(data_status["is_authenticated"])
        self.assertFalse(data_status["is_tv"])
        self.assertIn("remaining_seconds", data_status)
        self.assertEqual(data_status["timeout_seconds"], 300)

        # Keep-alive via POST
        res_alive = client.post(reverse("api_session_keep_alive"))
        self.assertEqual(res_alive.status_code, 200)
        self.assertEqual(res_alive.json()["status"], "ok")

        # Status para conta TV dedicada
        client.force_login(self.tv_user)
        res_tv_status = client.get(reverse("api_session_status"))
        self.assertEqual(res_tv_status.status_code, 200)
        self.assertTrue(res_tv_status.json()["is_tv"])

    def test_item4_editar_solicitacao_antes_do_primeiro_inicio(self):
        # 1. Cria solicitação pendente
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Descricao original antes de editar",
            solicitado_por=self.solicitante_user,
            prioridade="BAIXA",
        )
        self.assertEqual(sol.status, "SOLICITADO")
        self.assertEqual(sol.versao, 1)

        # 2. Solicitante edita a solicitação com sucesso
        sol_editada = MatrizariaService.editar_solicitacao(
            solicitacao_id=sol.id,
            usuario=self.solicitante_user,
            prensa=self.prensa_02,
            tipo_servico=self.tipo_troca,
            matriz_fisica=self.matriz_fisica_01,
            prioridade="ALTA",
            descricao_solicitacao="Descricao corrigida pelo solicitante",
            motivo_edicao="Prensa e matriz corrigidas conforme necessidade real",
            versao_esperada=sol.versao,
        )
        self.assertEqual(sol_editada.prensa, self.prensa_02)
        self.assertEqual(sol_editada.prensa.nome, "PRENSA BOM 02")
        self.assertEqual(sol_editada.prensa_nome_snapshot, "PRENSA BOM 01")  # Preserva evidência da abertura
        self.assertEqual(sol_editada.tipo_servico, self.tipo_troca)
        self.assertEqual(sol_editada.matriz_fisica, self.matriz_fisica_01)
        self.assertEqual(sol_editada.prioridade, "ALTA")
        self.assertEqual(sol_editada.descricao_solicitacao, "Descricao corrigida pelo solicitante")
        self.assertEqual(sol_editada.versao, 2)

        # Verifica histórico de auditoria
        h = sol_editada.historico_transicoes.filter(tipo_evento="ALTERACAO_DADO").first()
        self.assertIsNotNone(h)
        self.assertIn("Prensa e matriz corrigidas", h.observacao)
        self.assertIn("PRENSA BOM 01", h.dados_modificados)
        self.assertIn("PRENSA BOM 02", h.dados_modificados)

        # 3. Usuário sem permissão (técnico de manutenção comum) não pode editar
        with self.assertRaises(PermissionDenied):
            MatrizariaService.editar_solicitacao(
                solicitacao_id=sol_editada.id,
                usuario=self.tecnico_maint_user,
                prensa=self.prensa_01,
                tipo_servico=self.tipo_ajuste,
                matriz_fisica=None,
                prioridade="NORMAL",
                descricao_solicitacao="Tentativa indevida",
                motivo_edicao="Sem permissao",
                versao_esperada=sol_editada.versao,
            )

        # 4. Versão desatualizada (conflito de concorrência)
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.editar_solicitacao(
                solicitacao_id=sol_editada.id,
                usuario=self.solicitante_user,
                prensa=self.prensa_01,
                tipo_servico=self.tipo_ajuste,
                matriz_fisica=None,
                prioridade="NORMAL",
                descricao_solicitacao="Tentativa de edicao desatualizada",
                motivo_edicao="Versao antiga",
                versao_esperada=1,  # versão agora é 2
            )
        self.assertIn("Conflito de concorrência", str(ctx.exception))

        # 5. Se o atendimento já foi iniciado, a edição é bloqueada
        sol_iniciada = MatrizariaService.iniciar_atendimento(
            solicitacao_id=sol_editada.id,
            usuario=self.tecnico_matrizaria_1,
            versao_esperada=sol_editada.versao,
        )
        with self.assertRaises(ValidationError) as ctx2:
            MatrizariaService.editar_solicitacao(
                solicitacao_id=sol_iniciada.id,
                usuario=self.solicitante_user,
                prensa=self.prensa_01,
                tipo_servico=self.tipo_ajuste,
                matriz_fisica=None,
                prioridade="NORMAL",
                descricao_solicitacao="Tentativa durante execucao",
                motivo_edicao="Tarde demais",
                versao_esperada=sol_iniciada.versao,
            )
        self.assertIn("Apenas solicitações com status 'SOLICITADO' podem ser editadas", str(ctx2.exception))

    def test_item5_transferencia_somente_matrizeiros_habilitados(self):
        # 1. Cria chamado e inicia com o tecnico 1
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Servico para teste de transferencia",
            solicitado_por=self.solicitante_user,
        )
        sol = MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, sol.versao)

        # 2. Verifica elegibilidade de matrizeiros
        candidatos = MatrizariaService.get_matrizeiros_habilitados(solicitacao=sol)
        # Deve conter tecnico_matrizaria_2
        self.assertIn(self.tecnico_matrizaria_2, candidatos)
        # NÃO deve conter o responsável atual (tecnico_matrizaria_1)
        self.assertNotIn(self.tecnico_matrizaria_1, candidatos)
        # NÃO deve conter solicitante, manutenção mecânica ou TV
        self.assertNotIn(self.solicitante_user, candidatos)
        self.assertNotIn(self.tecnico_maint_user, candidatos)
        self.assertNotIn(self.tv_user, candidatos)

        # 3. Líder com grupo Matrizaria também se torna habilitado
        self.lider_user.groups.add(self.grp_matrizaria)
        candidatos_com_lider = MatrizariaService.get_matrizeiros_habilitados(solicitacao=sol)
        self.assertIn(self.lider_user, candidatos_com_lider)
        self.lider_user.groups.remove(self.grp_matrizaria)

        # 4. Tentativa de transferir para usuário não habilitado é rejeitada
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.transferir_responsabilidade(
                solicitacao_id=sol.id,
                usuario_origem=self.tecnico_matrizaria_1,
                novo_responsavel=self.tecnico_maint_user,
                motivo="Tentativa para mecanico de manutencao",
                versao_esperada=sol.versao,
            )
        self.assertIn("não está habilitado para receber serviços da Matrizaria", str(ctx.exception))

        # 5. Transferência válida para tecnico 2
        sol_transf = MatrizariaService.transferir_responsabilidade(
            solicitacao_id=sol.id,
            usuario_origem=self.tecnico_matrizaria_1,
            novo_responsavel=self.tecnico_matrizaria_2,
            motivo="Transferencia por rendicao de turno",
            versao_esperada=sol.versao,
        )
        self.assertEqual(sol_transf.responsavel_atribuido, self.tecnico_matrizaria_2)


class MatrizariaSpec1AdjustsTestCase(MatrizariaBaseTestCase):
    """
    Testes automatizados cobrindo os requisitos da SPEC 1:
    1. Criação com prensa;
    2. Criação escolhendo Matrizaria (serviço interno);
    3. Máquina obrigatória quando destino exigir máquina;
    4. Relatórios suportam serviço interno;
    5. Excel suporta serviço interno;
    6. Edição existente suporta alteração de destino;
    7. Exclusão operacional funciona conforme permissão;
    8. Usuário comum não recebe privilégio de exclusão administrativa;
    9. Superuser consegue excluir registro relacionado usando fluxo administrativo especial;
    10. Registros protegidos continuam protegidos fora do fluxo do superuser;
    11. Nenhuma escrita em scada.
    """

    def setUp(self):
        super().setUp()
        self.superuser = User.objects.create_superuser(
            username="admin_supremo",
            email="admin@example.com",
            password="adminpassword123",
        )
        self.client = Client()

    def test_item1_criacao_com_prensa(self):
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Ajuste normal em prensa",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )
        self.assertEqual(sol.destino, "MAQUINA")
        self.assertEqual(sol.prensa, self.prensa_01)
        self.assertEqual(sol.prensa_nome_snapshot, "PRENSA BOM 01")
        self.assertIn("PRENSA BOM 01", str(sol))

    def test_item2_criacao_escolhendo_matrizaria_sem_maquina(self):
        sol = MatrizariaService.criar_solicitacao(
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Manutenção interna de bancada e gabarito",
            solicitado_por=self.solicitante_user,
            destino="MATRIZARIA",
        )
        self.assertEqual(sol.destino, "MATRIZARIA")
        self.assertIsNone(sol.prensa)
        self.assertEqual(sol.prensa_nome_snapshot, "Matrizaria")
        self.assertIn("Matrizaria", str(sol))

    def test_item3_maquina_obrigatoria_quando_destino_maquina(self):
        # 1. MatrizariaService.criar_solicitacao sem prensa quando destino é MAQUINA
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.criar_solicitacao(
                prensa=None,
                tipo_servico=self.tipo_ajuste,
                descricao_solicitacao="Tentativa inválida sem máquina",
                solicitado_por=self.solicitante_user,
                destino="MAQUINA",
            )
        self.assertIn("A prensa é obrigatória", str(ctx.exception))

        # 2. Model clean() rejeita destino=MAQUINA com prensa=None
        sol_invalida_1 = SolicitacaoServicoMatrizaria(
            destino="MAQUINA",
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Teste model",
            solicitado_por=self.solicitante_user,
        )
        with self.assertRaises(ValidationError):
            sol_invalida_1.full_clean()

        # 3. Model clean() rejeita destino=MATRIZARIA com prensa associada
        sol_invalida_2 = SolicitacaoServicoMatrizaria(
            destino="MATRIZARIA",
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Teste model",
            solicitado_por=self.solicitante_user,
        )
        with self.assertRaises(ValidationError):
            sol_invalida_2.full_clean()

    def test_item4_relatorios_suportam_servico_interno(self):
        sol_int = MatrizariaService.criar_solicitacao(
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Serviço interno para relatório",
            solicitado_por=self.solicitante_user,
            destino="MATRIZARIA",
        )
        sol_maq = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Serviço máquina para relatório",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )

        hoje = timezone.localdate()
        # Filtro com destino=MATRIZARIA
        res_matriz = MatrizariaService.consultar_relatorio(
            criterio_temporal="ABERTAS",
            data_inicio=hoje,
            data_fim=hoje,
            destino="MATRIZARIA",
        )
        ids_matriz = [r["id"] for r in res_matriz]
        self.assertIn(sol_int.id, ids_matriz)
        self.assertNotIn(sol_maq.id, ids_matriz)

        item = next(r for r in res_matriz if r["id"] == sol_int.id)
        self.assertEqual(item["prensa_nome"], "Matrizaria")

    def test_item5_excel_suporta_servico_interno(self):
        sol_int = MatrizariaService.criar_solicitacao(
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Serviço interno para Excel",
            solicitado_por=self.solicitante_user,
            destino="MATRIZARIA",
        )
        self.client.force_login(self.superuser)
        url = reverse("matrizaria:exportar_excel") + "?criterio_temporal=ABERTAS&prensa=__MATRIZARIA__"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        import io
        wb = openpyxl.load_workbook(io.BytesIO(response.content))
        ws_servicos = wb["Serviços"]
        # Encontra a linha da solicitação interna
        linhas = list(ws_servicos.iter_rows(values_only=True))
        self.assertGreater(len(linhas), 1)
        header = linhas[0]
        col_prensa = header.index("Prensa")
        col_prot = header.index("Protocolo")
        
        achou = False
        for row in linhas[1:]:
            if row[col_prot] == f"SM #{sol_int.id}":
                self.assertEqual(row[col_prensa], "Matrizaria")
                achou = True
                break
        self.assertTrue(achou, "Solicitação interna não encontrada na planilha gerada")

    def test_item6_edicao_existente_suporta_mudanca_de_destino(self):
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Criado com máquina por engano",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )
        sol_editada = MatrizariaService.editar_solicitacao(
            solicitacao_id=sol.id,
            usuario=self.solicitante_user,
            versao_esperada=sol.versao,
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            matriz_fisica=None,
            prioridade="NORMAL",
            descricao_solicitacao="Corrigido para serviço interno da Matrizaria",
            motivo_edicao="Não é serviço de prensa, é na bancada",
            destino="MATRIZARIA",
        )
        self.assertEqual(sol_editada.destino, "MATRIZARIA")
        self.assertIsNone(sol_editada.prensa)

        h = sol_editada.historico_transicoes.filter(tipo_evento="ALTERACAO_DADO").first()
        self.assertIsNotNone(h)
        self.assertIn("Destino", h.dados_modificados)

    def test_item7_exclusao_operacional_sucesso_e_restricoes(self):
        # 1. Cria chamado pendente
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado para teste de exclusão",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )
        sol_id = sol.id

        # 2. Usuário sem permissão (técnico de manutenção) tenta excluir
        with self.assertRaises(PermissionDenied):
            MatrizariaService.excluir_solicitacao_operacional(sol_id, self.tecnico_maint_user)

        # 3. Solicitante próprio exclui com sucesso
        MatrizariaService.excluir_solicitacao_operacional(sol_id, self.solicitante_user)
        self.assertFalse(SolicitacaoServicoMatrizaria.objects.filter(id=sol_id).exists())
        self.assertFalse(HistoricoTransicaoServicoMatrizaria.objects.filter(solicitacao_id=sol_id).exists())

        # 4. Chamado já iniciado NÃO pode ser excluído operacionalmente
        sol_iniciado = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado iniciado",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )
        MatrizariaService.iniciar_atendimento(sol_iniciado.id, self.tecnico_matrizaria_1, sol_iniciado.versao)
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.excluir_solicitacao_operacional(sol_iniciado.id, self.solicitante_user)
        self.assertIn("Apenas chamados pendentes podem ser excluídos", str(ctx.exception))

        # Se forçado para status SOLICITADO mas ainda com ciclo existente
        sol_iniciado.status = "SOLICITADO"
        sol_iniciado.save()
        with self.assertRaises(ValidationError) as ctx:
            MatrizariaService.excluir_solicitacao_operacional(sol_iniciado.id, self.solicitante_user)
        self.assertIn("atendimento técnico já foi iniciado", str(ctx.exception))

    def test_item8_usuario_comum_nao_tem_privilegio_exclusao_administrativa(self):
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Teste privilégio superuser",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )
        # Operador
        with self.assertRaises(PermissionDenied):
            AdminCascadeDeletionService.excluir_objeto(sol, self.solicitante_user)
        # Líder
        with self.assertRaises(PermissionDenied):
            AdminCascadeDeletionService.excluir_objeto(sol, self.lider_user)

    def test_item9_superuser_exclusao_administrativa_forcada_com_dependentes(self):
        # 1. Cria chamado, inicia atendimento (gerando Ciclo e Históricos)
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado com dependentes",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )
        sol = MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, sol.versao)
        self.assertGreater(sol.ciclos_execucao.count(), 0)
        self.assertGreater(sol.historico_transicoes.count(), 0)

        # 2. Preview de dependentes
        preview = AdminCascadeDeletionService.coletar_dependentes([sol])
        self.assertEqual(len(preview), 1)
        self.assertGreater(len(preview[0]["dependentes"]), 0)

        # 3. Exclusão forçada por superusuário
        sol_id = sol.id
        resultado = AdminCascadeDeletionService.excluir_objeto(sol, self.superuser)
        self.assertGreaterEqual(resultado["total_deletados"], 3)
        self.assertFalse(SolicitacaoServicoMatrizaria.objects.filter(id=sol_id).exists())
        self.assertFalse(CicloExecucaoMatrizaria.objects.filter(solicitacao_id=sol_id).exists())
        self.assertFalse(HistoricoTransicaoServicoMatrizaria.objects.filter(solicitacao_id=sol_id).exists())

    def test_item10_registros_protegidos_continuam_protegidos_fora_fluxo_superuser(self):
        # Cria chamado e ciclo
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado com PROTECT ativo",
            solicitado_por=self.solicitante_user,
            destino="MAQUINA",
        )
        sol = MatrizariaService.iniciar_atendimento(sol.id, self.tecnico_matrizaria_1, sol.versao)
        
        # Tentar chamar delete() do Django diretamente no model DEVE falhar com ProtectedError
        with self.assertRaises(ProtectedError):
            sol.delete()

    def test_item11_nenhuma_escrita_em_scada(self):
        # Garante que os modelos residem no banco default
        sol = MatrizariaService.criar_solicitacao(
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Verificação de banco",
            solicitado_por=self.solicitante_user,
            destino="MATRIZARIA",
        )
        self.assertEqual(sol._state.db, "default")

    def test_botao_excluir_aparece_exclusivamente_para_superuser(self):
        """
        Valida que o botão 'Excluir Solicitação' é exibido no HTML exclusivamente
        quando o usuário logado é SuperUser (is_superuser=True).
        Operadores, técnicos e líderes não visualizam o botão de exclusão.
        """
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Teste de visibilidade de botões",
            solicitado_por=self.lider_user,
            destino="MAQUINA",
        )
        url = reverse("matrizaria:detalhe_servico", kwargs={"pk": sol.id})

        # 1. Líder autorizado acessa a tela de detalhes
        self.client.force_login(self.lider_user)
        res_user = self.client.get(url)
        self.assertEqual(res_user.status_code, 200)
        self.assertFalse(res_user.context["can_excluir"])
        self.assertNotContains(res_user, "Excluir Solicitação")
        self.assertContains(res_user, "Editar Solicitação")
        self.assertContains(res_user, "Cancelar Solicitação")
        self.assertContains(res_user, "bootstrap.bundle.min.js")
        self.assertContains(res_user, "openModalDirect")

        # 2. Usuário não-superuser tenta postar para exclusão -> Bloqueado
        res_delete_denied = self.client.post(reverse("matrizaria:excluir_solicitacao", kwargs={"pk": sol.id}))
        self.assertEqual(res_delete_denied.status_code, 302)
        self.assertTrue(SolicitacaoServicoMatrizaria.objects.filter(id=sol.id).exists())

        # 3. SuperUser acessa a tela de detalhes -> Botão Excluir presente
        self.client.force_login(self.superuser)
        res_super = self.client.get(url)
        self.assertEqual(res_super.status_code, 200)
        self.assertTrue(res_super.context["can_excluir"])
        self.assertContains(res_super, "Excluir Solicitação")
        self.assertContains(res_super, "Editar Solicitação")
        self.assertContains(res_super, "Cancelar Solicitação")

        # 4. SuperUser posta exclusão -> Excluído com sucesso
        res_delete_ok = self.client.post(reverse("matrizaria:excluir_solicitacao", kwargs={"pk": sol.id}))
        self.assertEqual(res_delete_ok.status_code, 302)
        self.assertFalse(SolicitacaoServicoMatrizaria.objects.filter(id=sol.id).exists())

    def test_abrir_chamado_matrizaria_via_post_sucesso(self):
        """
        1. Abrir chamado selecionando MATRIZARIA via POST:
           - HTTP esperado (302 -> redireciona para detalhe);
           - registro criado com prensa=None;
           - destino identificado como MATRIZARIA;
           - prensa_nome_snapshot preenchido como 'Matrizaria'.
        """
        self.client.force_login(self.lider_user)
        url = reverse("matrizaria:solicitar_servico")
        payload = {
            "prensa": "__MATRIZARIA__",
            "tipo_servico": self.tipo_ajuste.id,
            "descricao_solicitacao": "Serviço interno na bancada da Matrizaria",
            "prioridade": "NORMAL",
            "idempotency_key": "test-key-matrizaria-01",
        }
        res = self.client.post(url, data=payload)
        self.assertEqual(res.status_code, 302)

        sol = SolicitacaoServicoMatrizaria.objects.filter(descricao_solicitacao="Serviço interno na bancada da Matrizaria").first()
        self.assertIsNotNone(sol)
        self.assertRedirects(res, reverse("matrizaria:detalhe_servico", kwargs={"pk": sol.id}))
        self.assertEqual(sol.destino, "MATRIZARIA")
        self.assertIsNone(sol.prensa)
        self.assertEqual(sol.prensa_nome_snapshot, "Matrizaria")
        self.assertEqual(sol.equipamento_display, "Matrizaria")

    def test_abrir_chamado_prensa_real_via_post_sucesso(self):
        """
        2. Abrir chamado selecionando uma prensa real via POST:
           - registro criado;
           - prensa corretamente vinculada;
           - destino identificado como MAQUINA.
        """
        self.client.force_login(self.lider_user)
        url = reverse("matrizaria:solicitar_servico")
        payload = {
            "prensa": self.prensa_01.id,
            "tipo_servico": self.tipo_ajuste.id,
            "descricao_solicitacao": "Ajuste na prensa 01",
            "prioridade": "URGENTE",
            "idempotency_key": "test-key-prensa-01",
        }
        res = self.client.post(url, data=payload)
        self.assertEqual(res.status_code, 302)

        sol = SolicitacaoServicoMatrizaria.objects.filter(descricao_solicitacao="Ajuste na prensa 01").first()
        self.assertIsNotNone(sol)
        self.assertRedirects(res, reverse("matrizaria:detalhe_servico", kwargs={"pk": sol.id}))
        self.assertEqual(sol.destino, "MAQUINA")
        self.assertEqual(sol.prensa, self.prensa_01)
        self.assertEqual(sol.prensa_nome_snapshot, "PRENSA BOM 01")
        self.assertEqual(sol.equipamento_display, "PRENSA BOM 01")

    def test_abrir_chamado_sem_selecionar_destino_invalido(self):
        """
        3. Informar destino de máquina sem selecionar uma máquina (ou deixar campo vazio):
           - formulário inválido;
           - mensagem amigável;
           - nenhum registro criado.
        """
        self.client.force_login(self.solicitante_user)
        url = reverse("matrizaria:solicitar_servico")
        payload = {
            "prensa": "",
            "tipo_servico": self.tipo_ajuste.id,
            "descricao_solicitacao": "Tentativa sem selecionar destino",
            "prioridade": "NORMAL",
            "idempotency_key": "test-key-vazio",
        }
        res = self.client.post(url, data=payload)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Selecione o Destino do Serviço (Matrizaria ou uma Prensa / Máquina).")
        self.assertFalse(SolicitacaoServicoMatrizaria.objects.filter(descricao_solicitacao="Tentativa sem selecionar destino").exists())

    def test_servico_interno_no_kanban_exibe_matrizaria_sem_null(self):
        """
        4. Serviço interno aparece corretamente no Kanban:
           - exibe 'Matrizaria';
           - não exibe None, NULL, —, vazio ou erro de template.
        """
        sol = MatrizariaService.criar_solicitacao(
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado para validar Kanban visual",
            solicitado_por=self.lider_user,
            destino="MATRIZARIA",
        )
        self.client.force_login(self.tecnico_matrizaria_1)
        res = self.client.get(reverse("matrizaria:kanban"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Matrizaria")
        self.assertNotContains(res, "None")
        self.assertNotContains(res, "NULL")

    def test_servico_interno_nao_aparece_na_linha_do_tempo_de_nenhuma_prensa(self):
        """
        5. Serviço interno não aparece na linha do tempo de nenhuma prensa.
        """
        sol_int = MatrizariaService.criar_solicitacao(
            prensa=None,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado interno de bancada",
            solicitado_por=self.lider_user,
            destino="MATRIZARIA",
        )
        self.assertEqual(self.prensa_01.solicitacoes_matrizaria.count(), 0)
        self.assertEqual(self.prensa_02.solicitacoes_matrizaria.count(), 0)

        # Agora cria um chamado para a prensa 01
        sol_maq = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado para a prensa 01",
            solicitado_por=self.lider_user,
            destino="MAQUINA",
        )
        self.assertEqual(self.prensa_01.solicitacoes_matrizaria.count(), 1)
        self.assertIn(sol_maq, self.prensa_01.solicitacoes_matrizaria.all())
        self.assertNotIn(sol_int, self.prensa_01.solicitacoes_matrizaria.all())
        self.assertEqual(self.prensa_02.solicitacoes_matrizaria.count(), 0)

    def test_edicao_alternando_entre_maquina_e_matrizaria_via_post(self):
        """
        Testa edição via formulário / POST mudando de Máquina para Matrizaria e vice-versa.
        """
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Ajuste inicial em máquina",
            solicitado_por=self.lider_user,
            destino="MAQUINA",
        )
        self.assertEqual(sol.prensa_nome_snapshot, "PRENSA BOM 01")

        self.client.force_login(self.lider_user)
        # Edita para Matrizaria
        res_edit_1 = self.client.post(
            reverse("matrizaria:editar_solicitacao", kwargs={"pk": sol.id}),
            data={
                "versao": sol.versao,
                "prensa": "__MATRIZARIA__",
                "tipo_servico": self.tipo_ajuste.id,
                "prioridade": "NORMAL",
                "descricao_solicitacao": "Corrigido para bancada Matrizaria",
                "motivo_edicao": "Não era problema na prensa, e sim bancada",
            },
        )
        self.assertEqual(res_edit_1.status_code, 302)
        sol.refresh_from_db()
        self.assertEqual(sol.destino, "MATRIZARIA")
        self.assertIsNone(sol.prensa)
        self.assertEqual(sol.prensa_nome_snapshot, "PRENSA BOM 01")  # Preserva snapshot da abertura
        self.assertEqual(sol.equipamento_display, "Matrizaria")

        # Edita de volta para Prensa 02
        res_edit_2 = self.client.post(
            reverse("matrizaria:editar_solicitacao", kwargs={"pk": sol.id}),
            data={
                "versao": sol.versao,
                "prensa": self.prensa_02.id,
                "tipo_servico": self.tipo_ajuste.id,
                "prioridade": "NORMAL",
                "descricao_solicitacao": "Corrigido agora para prensa 02",
                "motivo_edicao": "Confirmado que é na prensa 02",
            },
        )
        self.assertEqual(res_edit_2.status_code, 302)
        sol.refresh_from_db()
        self.assertEqual(sol.destino, "MAQUINA")
        self.assertEqual(sol.prensa, self.prensa_02)
        self.assertEqual(sol.prensa_nome_snapshot, "PRENSA BOM 01")  # Preserva snapshot da abertura
        self.assertEqual(sol.equipamento_display, "PRENSA BOM 02")


class OperadorVulcanizacaoSpecTestCase(MatrizariaBaseTestCase):
    """
    Suíte completa de 25 cenários obrigatórios validando o Perfil de Operador da Vulcanização
    conforme a SPEC aprovada pelo Subagente Arquiteto.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from django.core.management import call_command
        # Garantir provisionamento idempotente do grupo e permissões no banco de testes
        call_command("provisionar_grupos_matrizaria", database="default")

        # Operador de vulcanização exclusivo dedicado
        cls.op_vulc_1 = User.objects.create_user(
            username="op_vulc_exclusivo_1", password="password123", first_name="Operador", last_name="Vulc 1"
        )
        cls.op_vulc_1.groups.add(cls.grp_vulc)

        # Segundo operador para testes de isolamento de chamados
        cls.op_vulc_2 = User.objects.create_user(
            username="op_vulc_exclusivo_2", password="password123", first_name="Operador", last_name="Vulc 2"
        )
        cls.op_vulc_2.groups.add(cls.grp_vulc)

    # ---------------------------------------------------------
    # Grupo A: Autenticação e Permissões (01 a 05)
    # ---------------------------------------------------------
    def test_01_grupo_operadores_vulcanizacao_provisionado(self):
        """01. Valida que o grupo 'Operadores Vulcanização' é criado no banco default via migration/command."""
        grupo = Group.objects.filter(name="Operadores Vulcanização").first()
        self.assertIsNotNone(grupo)

    def test_02_grupo_possui_permissoes_estritas_solicitacao(self):
        """02. Valida presença exclusiva de view e add em solicitacaoservicomatrizaria."""
        grupo = Group.objects.get(name="Operadores Vulcanização")
        sol_perms = set(
            grupo.permissions.filter(content_type__model="solicitacaoservicomatrizaria").values_list("codename", flat=True)
        )
        self.assertEqual(sol_perms, {"view_solicitacaoservicomatrizaria", "add_solicitacaoservicomatrizaria"})

    def test_03_grupo_possui_permissoes_leitura_matriz_e_tipo(self):
        """03. Valida presença de view_matrizfisica e view_tiposervicomatrizaria."""
        grupo = Group.objects.get(name="Operadores Vulcanização")
        codenames = set(grupo.permissions.values_list("codename", flat=True))
        self.assertIn("view_matrizfisica", codenames)
        self.assertIn("view_tiposervicomatrizaria", codenames)

    def test_04_grupo_nao_possui_permissoes_privilegiadas(self):
        """04. Valida que o grupo NÃO possui change/delete em solicitações nem permissões em ciclos."""
        grupo = Group.objects.get(name="Operadores Vulcanização")
        codenames = set(grupo.permissions.values_list("codename", flat=True))
        self.assertNotIn("change_solicitacaoservicomatrizaria", codenames)
        self.assertNotIn("delete_solicitacaoservicomatrizaria", codenames)
        ciclo_perms = grupo.permissions.filter(content_type__model="cicloexecucaomatrizaria")
        self.assertEqual(ciclo_perms.count(), 0)

    def test_05_helper_user_is_operador_vulcanizacao(self):
        """05. Testa que o helper retorna True para membros do grupo e False para outros."""
        from matrizaria.decorators import _user_is_operador_vulcanizacao
        self.assertTrue(_user_is_operador_vulcanizacao(self.op_vulc_1))
        self.assertTrue(_user_is_operador_vulcanizacao(self.solicitante_user))
        self.assertFalse(_user_is_operador_vulcanizacao(self.tecnico_matrizaria_1))
        self.assertFalse(_user_is_operador_vulcanizacao(self.lider_user))
        self.assertFalse(_user_is_operador_vulcanizacao(None))

    # ---------------------------------------------------------
    # Grupo B: Roteamento e Login (06 a 09)
    # ---------------------------------------------------------
    def test_06_helper_user_can_access_matrizaria_kanban_bloqueia_vulcanizacao(self):
        """06. Testa que _user_can_access_matrizaria_kanban retorna False para operador exclusivo e True para técnicos/líderes."""
        from matrizaria.decorators import _user_can_access_matrizaria_kanban
        self.assertFalse(_user_can_access_matrizaria_kanban(self.op_vulc_1))
        self.assertTrue(_user_can_access_matrizaria_kanban(self.tecnico_matrizaria_1))
        self.assertTrue(_user_can_access_matrizaria_kanban(self.lider_user))

    def test_07_home_redirect_operador_vulcanizacao_vai_para_minhas_solicitacoes(self):
        """07. Usuário exclusivo de vulcanização é redirecionado por home_redirect para /matrizaria/minhas-solicitacoes/."""
        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("home_redirect"))
        self.assertRedirects(res, reverse("matrizaria:minhas_solicitacoes"))

    def test_08_portal_select_operador_vulcanizacao_redireciona_direto(self):
        """08. Acesso a portal_select por operador de vulcanização exclusivo redireciona direto para minhas-solicitacoes."""
        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("portal_select"))
        self.assertRedirects(res, reverse("matrizaria:minhas_solicitacoes"))

    def test_09_portal_select_dual_access_card_aponta_minhas_solicitacoes(self):
        """09. Usuário com dual access (Vulcanização + Produção) recebe matrizaria_url apontando para minhas_solicitacoes."""
        dual_user = User.objects.create_user(username="dual_user_spec", password="password123")
        dual_user.groups.add(self.grp_vulc)
        # Permissão de produção sem atribuir grupo privilegiado da oficina
        perm_prod = Permission.objects.get(codename="view_productiontarget", content_type__app_label="production")
        dual_user.user_permissions.add(perm_prod)

        self.client.force_login(dual_user)
        res = self.client.get(reverse("portal_select"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["matrizaria_url"], "matrizaria:minhas_solicitacoes")
        self.assertContains(res, reverse("matrizaria:minhas_solicitacoes"))

    # ---------------------------------------------------------
    # Grupo C: Abertura de Chamados (10 a 13)
    # ---------------------------------------------------------
    def test_10_operador_vulcanizacao_acessa_formulario_solicitar_sucesso(self):
        """10. GET em /matrizaria/solicitar/ retorna HTTP 200 para operador de vulcanização."""
        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("matrizaria:solicitar_servico"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Abrir Chamado de Matrizaria")

    def test_11_abertura_solicitacao_define_solicitado_por_automatico(self):
        """11. POST de criação salva a solicitação com solicitado_por == request.user."""
        self.client.force_login(self.op_vulc_1)
        res = self.client.post(
            reverse("matrizaria:solicitar_servico"),
            data={
                "prensa": self.prensa_01.id,
                "tipo_servico": self.tipo_ajuste.id,
                "descricao_solicitacao": "Ordem de serviço aberta pelo operador 1",
                "prioridade": "NORMAL",
                "idempotency_key": "spec-test-11",
            },
        )
        sol = SolicitacaoServicoMatrizaria.objects.filter(descricao_solicitacao="Ordem de serviço aberta pelo operador 1").first()
        self.assertIsNotNone(sol)
        self.assertEqual(sol.solicitado_por, self.op_vulc_1)

    def test_12_abertura_solicitacao_ignora_injecao_outro_solicitante(self):
        """12. Tentativa de enviar outro ID no payload POST não altera o solicitante real."""
        self.client.force_login(self.op_vulc_1)
        res = self.client.post(
            reverse("matrizaria:solicitar_servico"),
            data={
                "prensa": self.prensa_01.id,
                "tipo_servico": self.tipo_ajuste.id,
                "descricao_solicitacao": "Tentativa forjar autoria",
                "prioridade": "NORMAL",
                "solicitado_por": self.lider_user.id,
                "idempotency_key": "spec-test-12",
            },
        )
        sol = SolicitacaoServicoMatrizaria.objects.filter(descricao_solicitacao="Tentativa forjar autoria").first()
        self.assertIsNotNone(sol)
        self.assertEqual(sol.solicitado_por, self.op_vulc_1)

    def test_13_abertura_solicitacao_redireciona_com_sucesso(self):
        """13. Abertura com sucesso redireciona para matrizaria:minhas_solicitacoes com mensagem de sucesso."""
        self.client.force_login(self.op_vulc_1)
        res = self.client.post(
            reverse("matrizaria:solicitar_servico"),
            data={
                "prensa": self.prensa_01.id,
                "tipo_servico": self.tipo_ajuste.id,
                "descricao_solicitacao": "Redirecionamento para minhas solicitacoes",
                "prioridade": "NORMAL",
                "idempotency_key": "spec-test-13",
            },
        )
        self.assertRedirects(res, reverse("matrizaria:minhas_solicitacoes"))

    # ---------------------------------------------------------
    # Grupo D: Interface Restrita e Isolamento (14 a 17)
    # ---------------------------------------------------------
    def test_14_operador_acessa_minhas_solicitacoes_sucesso(self):
        """14. GET em /matrizaria/minhas-solicitacoes/ retorna HTTP 200 e lista solicitações próprias."""
        MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Ordem própria para listagem",
            solicitado_por=self.op_vulc_1,
        )
        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("matrizaria:minhas_solicitacoes"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Ordem própria para listagem")

    def test_15_minhas_solicitacoes_isola_solicitacoes_de_terceiros(self):
        """15. Solicitações de outros operadores NÃO aparecem na tela do operador."""
        sol_op1 = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado do operador 1",
            solicitado_por=self.op_vulc_1,
        )
        sol_op2 = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_02,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado secreto do operador 2",
            solicitado_por=self.op_vulc_2,
        )

        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("matrizaria:minhas_solicitacoes"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Chamado do operador 1")
        self.assertNotContains(res, "Chamado secreto do operador 2")
        ids_no_context = [s.id for s in res.context["solicitacoes"]]
        self.assertIn(sol_op1.id, ids_no_context)
        self.assertNotIn(sol_op2.id, ids_no_context)

    def test_16_detalhe_propria_solicitacao_somente_leitura(self):
        """16. Detalhe de solicitação própria carrega em HTTP 200 com todas as flags de ação desativadas."""
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Inspecionar chamado próprio",
            solicitado_por=self.op_vulc_1,
        )
        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("matrizaria:detalhe_servico", kwargs={"pk": sol.id}))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context["can_executar"])
        self.assertFalse(res.context["can_conferir"])
        self.assertFalse(res.context["can_cancelar"])
        self.assertFalse(res.context["can_editar"])
        self.assertFalse(res.context["can_excluir"])
        self.assertTrue(res.context["is_operador_vulcanizacao"])

    def test_17_detalhe_solicitacao_terceiros_bloqueado(self):
        """17. Operador tentando acessar detalhe de chamado de terceiro recebe bloqueio (redirecionamento com erro)."""
        sol_terceiro = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_02,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Chamado alheio",
            solicitado_por=self.op_vulc_2,
        )
        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("matrizaria:detalhe_servico", kwargs={"pk": sol_terceiro.id}))
        self.assertRedirects(res, reverse("matrizaria:minhas_solicitacoes"))

    # ---------------------------------------------------------
    # Grupo E: Bloqueio de Ações Técnicas (18 a 21)
    # ---------------------------------------------------------
    def test_18_kanban_geral_bloqueado_para_operador_vulcanizacao(self):
        """18. Operador tentando acessar /matrizaria/ é redirecionado para /matrizaria/minhas-solicitacoes/."""
        self.client.force_login(self.op_vulc_1)
        res = self.client.get(reverse("matrizaria:kanban"))
        self.assertRedirects(res, reverse("matrizaria:minhas_solicitacoes"))

    def test_19_iniciar_atendimento_bloqueado_para_operador_vulcanizacao(self):
        """19. POST em /servicos/<pk>/iniciar/ por operador de vulcanização é bloqueado."""
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Tentativa de iniciar",
            solicitado_por=self.op_vulc_1,
        )
        self.client.force_login(self.op_vulc_1)
        res = self.client.post(
            reverse("matrizaria:iniciar_atendimento", kwargs={"pk": sol.id}),
            data={"versao": sol.versao},
        )
        self.assertRedirects(res, reverse("matrizaria:minhas_solicitacoes"))
        sol.refresh_from_db()
        self.assertEqual(sol.status, "SOLICITADO")

    def test_20_transferir_e_finalizar_bloqueados_para_operador_vulcanizacao(self):
        """20. POSTs em /transferir/ e /finalizar/ são bloqueados."""
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Tentativa de finalizar e transferir",
            solicitado_por=self.op_vulc_1,
        )
        self.client.force_login(self.op_vulc_1)
        res_trans = self.client.post(
            reverse("matrizaria:transferir_responsabilidade", kwargs={"pk": sol.id}),
            data={"versao": sol.versao},
        )
        self.assertRedirects(res_trans, reverse("matrizaria:minhas_solicitacoes"))

        res_fin = self.client.post(
            reverse("matrizaria:finalizar_execucao", kwargs={"pk": sol.id}),
            data={"versao": sol.versao},
        )
        self.assertRedirects(res_fin, reverse("matrizaria:minhas_solicitacoes"))

    def test_21_conferir_aprovacao_bloqueado_para_operador_vulcanizacao(self):
        """21. POST em /servicos/<pk>/conferir/ é bloqueado com erro de permissão."""
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Tentativa de conferir",
            solicitado_por=self.op_vulc_1,
        )
        self.client.force_login(self.op_vulc_1)
        res = self.client.post(
            reverse("matrizaria:conferir_servico", kwargs={"pk": sol.id}),
            data={"versao": sol.versao, "acao": "APROVAR"},
        )
        self.assertRedirects(res, reverse("matrizaria:minhas_solicitacoes"))

    # ---------------------------------------------------------
    # Grupo F: Bloqueio de Gestão e Outros Módulos (22 a 25)
    # ---------------------------------------------------------
    def test_22_editar_e_cancelar_bloqueados_para_operador_vulcanizacao(self):
        """22. POSTs em /editar/ e /cancelar/ são bloqueados para o operador."""
        sol = MatrizariaService.criar_solicitacao(
            prensa=self.prensa_01,
            tipo_servico=self.tipo_ajuste,
            descricao_solicitacao="Tentativa de editar/cancelar",
            solicitado_por=self.op_vulc_1,
        )
        self.client.force_login(self.op_vulc_1)
        res_edit = self.client.post(
            reverse("matrizaria:editar_solicitacao", kwargs={"pk": sol.id}),
            data={
                "versao": sol.versao,
                "prensa": self.prensa_01.id,
                "tipo_servico": self.tipo_ajuste.id,
                "descricao_solicitacao": "Editada ilegalmente",
                "prioridade": "NORMAL",
                "motivo_edicao": "Teste",
            },
        )
        self.assertRedirects(res_edit, reverse("matrizaria:minhas_solicitacoes"))

        res_canc = self.client.post(
            reverse("matrizaria:cancelar_servico", kwargs={"pk": sol.id}),
            data={"versao": sol.versao, "motivo_cancelamento": "Teste cancelamento"},
        )
        self.assertRedirects(res_canc, reverse("matrizaria:minhas_solicitacoes"))

    def test_23_relatorios_matrizaria_bloqueados_para_operador_vulcanizacao(self):
        """23. GET em /relatorios/ e /relatorios/exportar-excel/ são bloqueados."""
        self.client.force_login(self.op_vulc_1)
        res_rel = self.client.get(reverse("matrizaria:relatorios"))
        self.assertRedirects(res_rel, reverse("matrizaria:minhas_solicitacoes"))

        res_exp = self.client.get(reverse("matrizaria:exportar_excel"))
        self.assertRedirects(res_exp, reverse("matrizaria:minhas_solicitacoes"))

    def test_24_painel_tv_matrizaria_bloqueado_para_operador_vulcanizacao(self):
        """24. GET em /tv/ e /api/tv-data/ são bloqueados."""
        self.client.force_login(self.op_vulc_1)
        res_tv = self.client.get(reverse("matrizaria:tv"))
        self.assertRedirects(res_tv, reverse("matrizaria:minhas_solicitacoes"))

        res_api = self.client.get(reverse("matrizaria:api_tv_data"))
        self.assertRedirects(res_api, reverse("matrizaria:minhas_solicitacoes"))

    def test_25_modulos_manutencao_producao_bladder_bloqueados(self):
        """25. Operador de vulcanização tentando acessar /management/, /producao/ e /bladder/ recebe acesso negado."""
        self.client.force_login(self.op_vulc_1)
        res_maint = self.client.get(reverse("technician_management"))
        self.assertEqual(res_maint.status_code, 302)

        res_prod = self.client.get(reverse("production:dashboard"))
        self.assertEqual(res_prod.status_code, 302)

        res_blad = self.client.get(reverse("bladder:dashboard"))
        self.assertEqual(res_blad.status_code, 302)

