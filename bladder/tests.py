import datetime
import io
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.urls import reverse

from maintenance.models import Machine, Sector
from production.models import ProductionBladder
from bladder.models import (
    ProcessoBladder,
    ConfiguracaoEscalaBladder,
    AjusteEscalaExcepcionalBladder,
    FuncionarioApoioBladder,
    PerfilOperacionalBladder,
    ProdutoBladder,
    RecursoBladder,
    OrdemProducaoBladder,
    SaldoPendenteBladder,
    ApontamentoTurnoBladder,
    CategoriaDesvioBladder,
    HistoricoApontamentoBladder,
    HistoricoProgramacaoBladder,
    MensagemPassagemTurnoBladder,
    AcaoMensagemTurnoBladder,
)
from bladder.services import (
    calcular_turma_do_dia,
    obter_configuracao_escala_ativa,
    verificar_usuario_apoio_no_dia,
    criar_ordem_producao_com_saldos,
    encerrar_op_parcial_ou_total,
    reprogramar_ordem_producao,
    cancelar_ordem_producao,
    registrar_ou_atualizar_apontamento,
    corrigir_apontamento_operador_ou_lider,
    obter_saldos_pendentes_produto,
    executar_fechamento_turno,
    calcular_proximo_turno_operacional,
    criar_mensagem_passagem_turno,
    registrar_ciencia_mensagem_turno,
    resolver_mensagem_acompanhamento,
    repassar_mensagem_acompanhamento,
    obter_mensagens_recebidas_turno,
)
from maintenance.views import _user_can_access_bladder, _user_get_accessible_modules
from bladder.forms import OrdemProducaoBladderForm, MensagemPassagemTurnoForm


class BladderBaseTestCase(TestCase):
    def setUp(self):
        self.grupo_lider, _ = Group.objects.get_or_create(name="Liderança Bladder")
        self.grupo_op, _ = Group.objects.get_or_create(name="Operadores Bladder")

        # Usuários de teste
        self.lider = User.objects.create_user(username="lider_bladder", password="password123", first_name="Líder Bladder")
        self.lider.groups.add(self.grupo_lider)

        self.operador1 = User.objects.create_user(username="op_turma_a", password="password123", first_name="Operador A")
        self.operador1.groups.add(self.grupo_op)
        self.perfil_op1 = PerfilOperacionalBladder.objects.create(
            usuario=self.operador1,
            turma="TURMA_A",
            ativo=True
        )

        self.operador2 = User.objects.create_user(username="op_turma_b", password="password123", first_name="Operador B")
        self.operador2.groups.add(self.grupo_op)
        self.perfil_op2 = PerfilOperacionalBladder.objects.create(
            usuario=self.operador2,
            turma="TURMA_B",
            ativo=True
        )

        self.apoio_user = User.objects.create_user(username="op_apoio", password="password123", first_name="Operador Apoio")
        self.apoio_user.groups.add(self.grupo_op)

        self.sem_acesso = User.objects.create_user(username="sem_acesso", password="password123")

        # Configuração de Escala 12x36
        self.config_escala = ConfiguracaoEscalaBladder.objects.create(
            data_referencia=datetime.date(2026, 1, 1),
            turma_referencia="TURMA_A",
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        # Processo e Produto padrão
        self.setor = Sector.objects.create(nome="BLADDER")
        self.maquina = Machine.objects.create(nome="PRENSA DE BLADER 01", setor=self.setor, criticidade="MEDIA")

        self.processo = ProcessoBladder.objects.create(
            codigo="01",
            nome="Prensa de Vulcanização 01",
            tipo="PRENSA",
            maquina=self.maquina,
            ordem_exibicao=1,
            ativo=True
        )

        self.produto_bla1 = ProdutoBladder.objects.create(
            codigo="BLA001",
            descricao="Bladder 18/19-210",
            matriz_extrusao="MAT04",
            peso_tarugo_kg=Decimal("2.500"),
            peso_vulcanizado_kg=Decimal("2.250"),
            ativo=True
        )

        self.produto_bla2 = ProdutoBladder.objects.create(
            codigo="BLA002",
            descricao="Bladder 17/18-140",
            matriz_extrusao="MAT04",
            peso_tarugo_kg=Decimal("2.000"),
            peso_vulcanizado_kg=Decimal("1.825"),
            ativo=True
        )


class BladderEscalaTestCase(BladderBaseTestCase):
    def test_alternancia_dias_12x36(self):
        """Valida que Turma A e Turma B alternam diariamente de forma determinística."""
        # Data de ref: 2026-01-01 -> Turma A
        t1, is_ajuste, _ = calcular_turma_do_dia(datetime.date(2026, 1, 1))
        self.assertEqual(t1, "TURMA_A")
        self.assertFalse(is_ajuste)

        # Dia seguinte: 2026-01-02 -> Turma B
        t2, is_ajuste, _ = calcular_turma_do_dia(datetime.date(2026, 1, 2))
        self.assertEqual(t2, "TURMA_B")

        # Dia 3: 2026-01-03 -> Turma A
        t3, is_ajuste, _ = calcular_turma_do_dia(datetime.date(2026, 1, 3))
        self.assertEqual(t3, "TURMA_A")

        # Dia 4: 2026-01-04 -> Turma B
        t4, is_ajuste, _ = calcular_turma_do_dia(datetime.date(2026, 1, 4))
        self.assertEqual(t4, "TURMA_B")

    def test_mudanca_data_referencia_admin(self):
        """Ao alterar a data de referência no Admin, o cálculo acompanha imediatamente sem mexer em código."""
        self.config_escala.data_referencia = datetime.date(2026, 1, 2)
        self.config_escala.turma_referencia = "TURMA_A"
        self.config_escala.save()

        # Agora 2026-01-02 é Turma A
        turma, _, _ = calcular_turma_do_dia(datetime.date(2026, 1, 2))
        self.assertEqual(turma, "TURMA_A")

        # E 2026-01-03 torna-se Turma B
        turma, _, _ = calcular_turma_do_dia(datetime.date(2026, 1, 3))
        self.assertEqual(turma, "TURMA_B")

    def test_ajuste_escala_excepcional_sobreposicao(self):
        """Ajuste excepcional sobrepõe a alternância padrão para a data específica."""
        data_troca = datetime.date(2026, 1, 2)  # Normalmente seria Turma B
        AjusteEscalaExcepcionalBladder.objects.create(
            data=data_troca,
            turma_designada="TURMA_A",
            motivo="Troca excepcional acordada entre líderes",
            criado_por=self.lider
        )

        turma, is_ajuste, motivo = calcular_turma_do_dia(data_troca)
        self.assertEqual(turma, "TURMA_A")
        self.assertTrue(is_ajuste)
        self.assertEqual(motivo, "Troca excepcional acordada entre líderes")

    def test_funcionario_apoio_escala_flexivel(self):
        """Funcionário de apoio atua nos dias configurados sem alterar a Turma do dia."""
        FuncionarioApoioBladder.objects.create(
            usuario=self.apoio_user,
            papel="Apoio de Sexta e Sábado",
            tipo_escala="DIAS_SEMANA",
            dias_semana="4,5",  # 4=Sexta, 5=Sábado
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        sexta = datetime.date(2026, 1, 2)  # 2026-01-02 foi uma sexta-feira
        is_apoio, apoio_obj = verificar_usuario_apoio_no_dia(self.apoio_user, sexta)
        self.assertTrue(is_apoio)
        self.assertEqual(apoio_obj.papel, "Apoio de Sexta e Sábado")

        domingo = datetime.date(2026, 1, 4)
        is_apoio, _ = verificar_usuario_apoio_no_dia(self.apoio_user, domingo)
        self.assertFalse(is_apoio)

        # Outro usuário não é apoio
        is_apoio, _ = verificar_usuario_apoio_no_dia(self.operador1, sexta)
        self.assertFalse(is_apoio)

    def test_calculo_dinamico_atraso_as_18h(self):
        """Valida que atraso ocorre dinamicamente quando turno encerra (18:00)."""
        ontem = timezone.localdate() - datetime.timedelta(days=1)
        op_passada = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-TESTE-ONTEM",
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=ontem,
            turma_prevista="TURMA_A",
            quantidade_nova=50,
            quantidade_planejada=50,
            status="PENDENTE",
            criado_por=self.lider
        )
        self.assertTrue(op_passada.esta_atrasada())

        op_concluida = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-TESTE-CONCLUIDA",
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=ontem,
            turma_prevista="TURMA_A",
            quantidade_nova=50,
            quantidade_planejada=50,
            quantidade_realizada=50,
            status="CONCLUIDA",
            criado_por=self.lider
        )
        self.assertFalse(op_concluida.esta_atrasada())


class BladderSaldoLedgerTestCase(BladderBaseTestCase):
    def test_regra_saldo_parcial_e_incorporacao_automatica(self):
        """
        Cenário canônico obrigatório:
        OP 001: Demanda nova = 120, Realizado = 80 -> Encerra PARCIAL -> Saldo 40 vira Ledger.
        OP 002: Mesmo produto, Demanda nova = 100 -> Incorpora 40 -> Total a produzir = 140.
        """
        hoje = timezone.localdate()

        # 1. Cria OP 001
        op1 = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=hoje,
            quantidade_nova=120,
            usuario=self.lider
        )
        self.assertEqual(op1.quantidade_nova, 120)
        self.assertEqual(op1.saldo_anterior_incorporado, 0)
        self.assertEqual(op1.quantidade_planejada, 120)
        self.assertEqual(op1.status, "PENDENTE")

        # 2. Operador aponta 80 unidades
        registrar_ou_atualizar_apontamento(
            ordem_id=op1.pk,
            operador=self.operador1,
            quantidade=80,
            situacao="PARCIAL",
            motivo_desvio="Fim de turno atingido antes da meta"
        )
        op1.refresh_from_db()
        self.assertEqual(op1.quantidade_realizada, 80)
        self.assertEqual(op1.saldo_remanescente, 40)

        # 3. Líder encerra o turno da OP 001 como PARCIAL
        encerrar_op_parcial_ou_total(op1.pk, self.lider, "Fechamento do turno da Turma A")
        op1.refresh_from_db()
        self.assertEqual(op1.status, "PARCIAL")

        # 4. Verifica geração de saldo no Ledger
        saldos_pendentes = obter_saldos_pendentes_produto(self.produto_bla1.pk)
        self.assertEqual(saldos_pendentes.count(), 1)
        saldo_ledger = saldos_pendentes.first()
        self.assertEqual(saldo_ledger.op_origem, op1)
        self.assertEqual(saldo_ledger.produto, self.produto_bla1)
        self.assertEqual(saldo_ledger.quantidade, 40)
        self.assertEqual(saldo_ledger.status, "PENDENTE")

        # 5. Líder cria a PRÓXIMA OP para o MESMO produto (demanda nova = 100) e decide INCORPORAR a pendência
        amanha = hoje + datetime.timedelta(days=1)
        op2 = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=amanha,
            quantidade_nova=100,
            saldos_selecionados_ids=[saldo_ledger.id],
            usuario=self.lider
        )

        # 6. Validação dos saldos na OP 002
        self.assertEqual(op2.quantidade_nova, 100)
        self.assertEqual(op2.saldo_anterior_incorporado, 40)
        self.assertEqual(op2.quantidade_planejada, 140)  # 100 + 40 = 140

        # 7. Verifica atualização do Ledger
        saldo_ledger.refresh_from_db()
        self.assertEqual(saldo_ledger.status, "INCORPORADO")
        self.assertEqual(saldo_ledger.op_destino, op2)
        self.assertIsNotNone(saldo_ledger.data_incorporacao)

        # 8. Não resta mais saldo pendente disponível para o produto
        self.assertEqual(obter_saldos_pendentes_produto(self.produto_bla1.pk).count(), 0)

        # 9. A OP 001 permanece PARCIAL preservada
        op1.refresh_from_db()
        self.assertEqual(op1.status, "PARCIAL")
        self.assertEqual(op1.quantidade_planejada, 120)
        self.assertEqual(op1.quantidade_realizada, 80)

    def test_incorporacao_multiplos_saldos_fifo(self):
        """Se o líder decidir incorporar múltiplos saldos pendentes do mesmo produto, todos são vinculados."""
        hoje = timezone.localdate()

        # 1. Cria OP A e OP B em paralelo no mesmo dia (ex: dois turnos ou dois processos)
        op_a = criar_ordem_producao_com_saldos(self.processo, self.produto_bla2, hoje, 50, usuario=self.lider)
        op_b = criar_ordem_producao_com_saldos(self.processo, self.produto_bla2, hoje, 40, usuario=self.lider)

        # 2. Executa ambas com fechamento parcial
        registrar_ou_atualizar_apontamento(op_a.pk, self.operador1, 35, "PARCIAL")
        encerrar_op_parcial_ou_total(op_a.pk, self.lider, "Parcial A (resta 15)")

        registrar_ou_atualizar_apontamento(op_b.pk, self.operador1, 15, "PARCIAL")
        encerrar_op_parcial_ou_total(op_b.pk, self.lider, "Parcial B (resta 25)")

        # 3. Saldo pendente total acumulado = 15 + 25 = 40
        saldos = obter_saldos_pendentes_produto(self.produto_bla2.pk)
        self.assertEqual(saldos.count(), 2)

        # Próxima OP com demanda 60, líder decide incorporar ambos os saldos
        saldos_ids = list(saldos.values_list('id', flat=True))
        op_c = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla2, hoje, 60,
            saldos_selecionados_ids=saldos_ids,
            usuario=self.lider
        )
        self.assertEqual(op_c.quantidade_nova, 60)
        self.assertEqual(op_c.saldo_anterior_incorporado, 40)
        self.assertEqual(op_c.quantidade_planejada, 100)

        # Todos incorporados
        self.assertEqual(obter_saldos_pendentes_produto(self.produto_bla2.pk).count(), 0)

    def test_cancelamento_op_com_saldo_reabre_ledger(self):
        """Ao cancelar uma OP que incorporou saldo, os saldos anteriores não podem ser perdidos (voltam a PENDENTE)."""
        hoje = timezone.localdate()
        op1 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, hoje, 50, usuario=self.lider)
        registrar_ou_atualizar_apontamento(op1.pk, self.operador1, 30, "PARCIAL")
        encerrar_op_parcial_ou_total(op1.pk, self.lider)
        saldo_op1 = SaldoPendenteBladder.objects.get(op_origem=op1)

        # OP2 incorpora os 20 por decisão explícita
        op2 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, hoje, 80,
            saldos_selecionados_ids=[saldo_op1.id],
            usuario=self.lider
        )
        self.assertEqual(op2.saldo_anterior_incorporado, 20)

        # Cancela OP2
        cancelar_ordem_producao(op2.pk, "Cancelamento por mudança de demanda", self.lider)
        op2.refresh_from_db()
        self.assertEqual(op2.status, "CANCELADA")

        # Os 20 voltam para PENDENTE no Ledger
        saldos = obter_saldos_pendentes_produto(self.produto_bla1.pk)
        self.assertEqual(saldos.count(), 1)
        self.assertEqual(saldos.first().quantidade, 20)

    def test_reprogramacao_mesma_op_preserva_historico(self):
        """A reprogramação atualiza a data na MESMA OP e grava a data anterior no histórico de auditoria."""
        hoje = timezone.localdate()
        amanha = hoje + datetime.timedelta(days=1)
        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, hoje, 70, usuario=self.lider)

        reprogramar_ordem_producao(op.pk, amanha, "Adiada para aguardar composto de borracha", self.lider)
        op.refresh_from_db()

        self.assertEqual(op.data_programada, amanha)
        hist = op.historicos_programacao.filter(tipo_evento="REPROGRAMACAO").first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.data_anterior, hoje)
        self.assertEqual(hist.data_nova, amanha)
        self.assertIn("aguardar composto", hist.motivo)


class BladderPermissoesTestCase(BladderBaseTestCase):
    def test_operador_bloqueado_em_rotas_de_lideranca(self):
        """Operador comum não pode acessar rotas de criação, reprogramação ou cancelamento."""
        client = Client()
        client.force_login(self.operador1)

        # Criar OP
        res = client.get(reverse("bladder:ordem_nova"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/operador/", res.url)

        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, timezone.localdate(), 50, usuario=self.lider)

        # Reprogramar
        res_rep = client.post(reverse("bladder:ordem_reprogramar", args=[op.pk]), {"nova_data": "2026-01-10", "motivo": "Teste"})
        self.assertEqual(res_rep.status_code, 302)
        self.assertIn("/operador/", res_rep.url)

        # Cancelar
        res_canc = client.post(reverse("bladder:ordem_cancelar", args=[op.pk]), {"motivo": "Teste"})
        self.assertEqual(res_canc.status_code, 302)
        self.assertIn("/operador/", res_canc.url)

    def test_correcao_apontamento_mesmo_turno(self):
        """Operador pode corrigir lançamento próprio no mesmo turno do dia."""
        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, timezone.localdate(), 100, usuario=self.lider)
        ap = registrar_ou_atualizar_apontamento(op.pk, self.operador1, 20, "CONCLUIDA")

        # Correção
        corrigir_apontamento_operador_ou_lider(ap.pk, 25, "Erro de contagem manual", self.operador1)
        ap.refresh_from_db()
        op.refresh_from_db()

        self.assertEqual(ap.quantidade_realizada, 25)
        self.assertEqual(op.quantidade_realizada, 25)

        # Histórico de auditoria gravado
        hist = HistoricoApontamentoBladder.objects.filter(apontamento=ap).first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.quantidade_anterior, 20)
        self.assertEqual(hist.quantidade_nova, 25)
        self.assertEqual(hist.usuario, self.operador1)

    def test_portal_redirecionamento_operador(self):
        """Usuário apenas com permissão de Operador de Bladder é direcionado direto a /bladder/operador/."""
        self.assertTrue(_user_can_access_bladder(self.operador1))
        accessible = _user_get_accessible_modules(self.operador1)
        self.assertEqual(accessible, ["bladder"])

        client = Client()
        client.force_login(self.operador1)
        res = client.get(reverse("portal_select"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/bladder/operador/", res.url)


class BladderMateriaPrimaTeoricaTestCase(BladderBaseTestCase):
    def test_calculo_teorico_tarugo_bladder(self):
        """Regra 1 Tarugo = 1 Bladder multiplica pela massa padrão do modelo."""
        # 140 peças de BLA001 (tarugo: 2.500 kg)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-TARUGO-TEST",
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=timezone.localdate(),
            turma_prevista="TURMA_A",
            quantidade_nova=140,
            quantidade_planejada=140,
            quantidade_realizada=80,
            criado_por=self.lider
        )

        # Planejado: 140 * 2.500 = 350.000 kg
        self.assertEqual(op.consumo_teorico_planejado_kg, 350.0)
        # Realizado: 80 * 2.500 = 200.000 kg
        self.assertEqual(op.consumo_teorico_realizado_kg, 200.0)


class BladderViewsEndToEndTestCase(BladderBaseTestCase):
    def setUp(self):
        super().setUp()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

        self.client_op = Client()
        self.client_op.force_login(self.operador1)

    def test_dashboard_view_200(self):
        """Dashboard carrega com HTTP 200 e dados do dia."""
        res = self.client_lider.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Dashboard Operacional do Setor de Bladder")
        self.assertContains(res, "Motivos das Pendências")

    def test_operador_turno_view_200(self):
        """Tela de chão de fábrica do operador carrega com HTTP 200."""
        res = self.client_op.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "CHÃO DE FÁBRICA")

    def test_cronograma_calendario_view_200(self):
        """Calendário mensal carrega com HTTP 200 para líder."""
        res = self.client_lider.get(reverse("bladder:cronograma"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Cronograma Mensal de Produção")

    def test_ordens_lista_view_200(self):
        """Listagem de ordens carrega com HTTP 200."""
        res = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Ordens de Produção (OPs)")

    def test_criar_op_via_post_com_saldo(self):
        """Líder cria OP via POST no formulário com decisão explícita de INCORPORAR pendência."""
        # Cria saldo pendente prévio de 30 un
        op_ant = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, timezone.localdate(), 50, usuario=self.lider)
        registrar_ou_atualizar_apontamento(op_ant.pk, self.operador1, 20, "PARCIAL")
        encerrar_op_parcial_ou_total(op_ant.pk, self.lider)

        # Saldo de 30 está pendente; líder decide explicitamente INCORPORAR
        post_data = {
            "processo": self.processo.pk,
            "produto": self.produto_bla1.pk,
            "data_programada": timezone.localdate().strftime("%Y-%m-%d"),
            "quantidade_nova": 70,
            "prioridade": "NORMAL",
            "decisao_pendencias": "INCORPORAR",
            "recursos_observacoes": "Tarugo aquecido",
            "observacoes": "Observação de teste",
        }
        res = self.client_lider.post(reverse("bladder:ordem_nova"), post_data)
        self.assertEqual(res.status_code, 302)

        # Nova OP deve ter total planejado = 70 + 30 = 100
        nova_op = OrdemProducaoBladder.objects.order_by("-id").first()
        self.assertEqual(nova_op.quantidade_nova, 70)
        self.assertEqual(nova_op.saldo_anterior_incorporado, 30)
        self.assertEqual(nova_op.quantidade_planejada, 100)

    def test_fluxo_operador_iniciar_e_apontar(self):
        """Operador inicia e conclui apontamento via POST."""
        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, timezone.localdate(), 50, usuario=self.lider)

        # 1. Iniciar
        res_ini = self.client_op.post(reverse("bladder:operador_iniciar", args=[op.pk]))
        self.assertEqual(res_ini.status_code, 302)
        op.refresh_from_db()
        self.assertEqual(op.status, "EM_EXECUCAO")

        # 2. Apontar 50 un (conclusão total)
        res_apo = self.client_op.post(reverse("bladder:operador_apontar", args=[op.pk]), {
            "quantidade_realizada": 50,
            "situacao": "CONCLUIDA",
            "motivo_desvio": "",
            "observacoes": "Turno normal",
        })
        self.assertEqual(res_apo.status_code, 302)
        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, 50)
        self.assertEqual(op.status, "CONCLUIDA")

    def test_api_saldo_produto(self):
        """API JSON de saldo do produto retorna contagem correta."""
        res = self.client_lider.get(reverse("bladder:api_saldo_produto", args=[self.produto_bla1.pk]))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_saldo_pendente", data)

    def test_relatorios_exportar_excel_200(self):
        """Exportação Excel gera planilha .xlsx com cabeçalhos sanitizados."""
        res = self.client_lider.get(reverse("bladder:relatorios_exportar_excel"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        self.assertIn("Fechamento_Bladder_", res["Content-Disposition"])


class BladderComplementarPermissoesPerfisTestCase(BladderBaseTestCase):
    def setUp(self):
        super().setUp()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

        self.client_op2 = Client()
        self.client_op2.force_login(self.operador2)

        self.apoio_user = User.objects.create_user(
            username="op_apoio_perm", password="password123", first_name="Operador Apoio Perm"
        )
        self.apoio_user.groups.add(self.grupo_op)
        self.apoio_obj = FuncionarioApoioBladder.objects.create(
            usuario=self.apoio_user,
            papel="Apoio Geral Bladder",
            tipo_escala="DIAS_SEMANA",
            dias_semana="0,1,2,3,4,5,6",
            ativo=True
        )
        self.client_apoio = Client()
        self.client_apoio.force_login(self.apoio_user)

        self.superuser = User.objects.create_superuser(
            username="admin_super", password="password123", email="admin@freedom.com"
        )
        self.client_super = Client()
        self.client_super.force_login(self.superuser)

        # Usuário Staff genérico (SEM grupos do Bladder)
        self.user_staff = User.objects.create_user(
            username="staff_generico", password="password123", is_staff=True
        )

        # Usuários de outros módulos
        # 1. Manutenção (grupo Tecnicos)
        grp_maint, _ = Group.objects.get_or_create(name="Tecnicos")
        self.user_maint = User.objects.create_user(username="maint_user", password="password123")
        self.user_maint.groups.add(grp_maint)

        # 2. Produção (grupo Liderança de Produção)
        grp_prod, _ = Group.objects.get_or_create(name="Liderança de Produção")
        self.user_prod = User.objects.create_user(username="prod_user", password="password123")
        self.user_prod.groups.add(grp_prod)

        # 3. Matrizaria (grupo Matrizaria)
        grp_matriz, _ = Group.objects.get_or_create(name="Matrizaria")
        self.user_matriz = User.objects.create_user(username="matriz_user", password="password123")
        self.user_matriz.groups.add(grp_matriz)

        # OP de teste
        self.op_teste = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 50, usuario=self.lider
        )

    def test_01_lider_acessa_dashboard_bladder(self):
        """1. Líder acessa dashboard Bladder (/bladder/)."""
        res = self.client_lider.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Dashboard Operacional do Setor de Bladder")

    def test_02_lider_acessa_criacao_op(self):
        """2. Líder acessa criação de OP (/bladder/ordens/nova/)."""
        res = self.client_lider.get(reverse("bladder:ordem_nova"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Nova Programação de Bladder")

    def test_03_lider_acessa_relatorios(self):
        """3. Líder acessa relatórios (/bladder/relatorios/)."""
        res = self.client_lider.get(reverse("bladder:relatorios"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Fechamento Mensal e Relatórios Operacionais")

    def test_04_operador_acessa_operador_turno(self):
        """4. Operador acessa /bladder/operador/ com HTTP 200."""
        res = self.client_op1.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "CHÃO DE FÁBRICA")

    def test_05_operador_nao_acessa_criacao_op(self):
        """5. Operador NÃO acessa criação de OP (redirecionado seguro para /bladder/operador/)."""
        res = self.client_op1.get(reverse("bladder:ordem_nova"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/bladder/operador/", res.url)

    def test_06_operador_nao_acessa_reprogramacao(self):
        """6. Operador NÃO acessa reprogramação (redirecionado seguro)."""
        res = self.client_op1.post(
            reverse("bladder:ordem_reprogramar", args=[self.op_teste.pk]),
            {"nova_data": "2026-02-01", "motivo": "Tentativa indevida"}
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/bladder/operador/", res.url)

    def test_07_operador_nao_acessa_cancelamento(self):
        """7. Operador NÃO acessa cancelamento (redirecionado seguro)."""
        res = self.client_op1.post(
            reverse("bladder:ordem_cancelar", args=[self.op_teste.pk]),
            {"motivo": "Tentativa indevida"}
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/bladder/operador/", res.url)
        self.op_teste.refresh_from_db()
        self.assertNotEqual(self.op_teste.status, "CANCELADA")

    def test_08_operador_nao_acessa_relatorios(self):
        """8. Operador NÃO acessa relatórios gerenciais nem exportação Excel."""
        res = self.client_op1.get(reverse("bladder:relatorios"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/bladder/operador/", res.url)

        res_excel = self.client_op1.get(reverse("bladder:relatorios_exportar_excel"))
        self.assertEqual(res_excel.status_code, 302)
        self.assertIn("/bladder/operador/", res_excel.url)

    def test_09_operador_turma_a_possui_perfil_correto(self):
        """9. Operador Turma A possui perfil correto vinculado e ativo."""
        perfil = self.operador1.perfil_operacional_bladder
        self.assertEqual(perfil.turma, "TURMA_A")
        self.assertTrue(perfil.ativo)
        self.assertIn("Turma A", str(perfil))

    def test_10_operador_turma_b_possui_perfil_correto(self):
        """10. Operador Turma B possui perfil correto vinculado e ativo."""
        perfil = self.operador2.perfil_operacional_bladder
        self.assertEqual(perfil.turma, "TURMA_B")
        self.assertTrue(perfil.ativo)
        self.assertIn("Turma B", str(perfil))

    def test_11_apoio_consegue_operar_quando_autorizado(self):
        """11. Apoio consegue operar quando autorizado em FuncionarioApoioBladder."""
        self.assertTrue(_user_can_access_bladder(self.apoio_user))
        res = self.client_apoio.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)

        # Inicia e registra apontamento
        res_ini = self.client_apoio.post(reverse("bladder:operador_iniciar", args=[self.op_teste.pk]))
        self.assertEqual(res_ini.status_code, 302)
        self.op_teste.refresh_from_db()
        self.assertEqual(self.op_teste.status, "EM_EXECUCAO")

    def test_12_apoio_nao_e_convertido_em_turma_a_b(self):
        """12. Apoio não é convertido artificialmente em Turma A/B fixa."""
        self.assertFalse(PerfilOperacionalBladder.objects.filter(usuario=self.apoio_user).exists())
        ap = registrar_ou_atualizar_apontamento(
            self.op_teste.pk, self.apoio_user, 15, "EM_ANDAMENTO"
        )
        self.assertEqual(ap.turma, "APOIO")

    def test_13_usuario_maintenance_sem_grupo_bladder_nao_acessa(self):
        """13. Usuário Maintenance sem grupo Bladder não acessa Bladder."""
        self.assertFalse(_user_can_access_bladder(self.user_maint))
        client = Client()
        client.force_login(self.user_maint)
        res = client.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/portal/", res.url)

    def test_14_usuario_production_sem_grupo_bladder_nao_acessa(self):
        """14. Usuário Production sem grupo Bladder não acessa Bladder."""
        self.assertFalse(_user_can_access_bladder(self.user_prod))
        client = Client()
        client.force_login(self.user_prod)
        res = client.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/portal/", res.url)

    def test_15_usuario_matrizaria_sem_grupo_bladder_nao_acessa(self):
        """15. Usuário Matrizaria sem grupo Bladder não acessa Bladder."""
        self.assertFalse(_user_can_access_bladder(self.user_matriz))
        client = Client()
        client.force_login(self.user_matriz)
        res = client.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/portal/", res.url)

    def test_16_staff_generico_sem_grupo_bladder_nao_acessa(self):
        """16. staff=True genérico sem grupo Bladder NÃO concede acesso."""
        self.assertFalse(_user_can_access_bladder(self.user_staff))
        client = Client()
        client.force_login(self.user_staff)
        res_dash = client.get(reverse("bladder:dashboard"))
        self.assertEqual(res_dash.status_code, 302)
        self.assertIn("/portal/", res_dash.url)

        res_op = client.get(reverse("bladder:operador"))
        self.assertEqual(res_op.status_code, 302)
        self.assertIn("/portal/", res_op.url)

    def test_17_superuser_mantem_acesso(self):
        """17. Superuser mantém acesso como exceção administrativa em todas as telas."""
        self.assertTrue(_user_can_access_bladder(self.superuser))
        res_dash = self.client_super.get(reverse("bladder:dashboard"))
        self.assertEqual(res_dash.status_code, 200)

        res_op = self.client_super.get(reverse("bladder:operador"))
        self.assertEqual(res_op.status_code, 200)

        res_rel = self.client_super.get(reverse("bladder:relatorios"))
        self.assertEqual(res_rel.status_code, 200)

    def test_18_url_digitada_diretamente_continua_protegida(self):
        """18. URL digitada diretamente por usuário anônimo redireciona para login."""
        client_anon = Client()
        for url_name in ["bladder:dashboard", "bladder:operador", "bladder:ordem_nova", "bladder:relatorios"]:
            res = client_anon.get(reverse(url_name))
            self.assertEqual(res.status_code, 302)
            self.assertIn("/login/", res.url)

    def test_19_portal_mostra_card_apenas_para_autorizados(self):
        """19. Portal mostra card 'Setor de Bladder' apenas para usuários autorizados."""
        self.assertTrue(_user_can_access_bladder(self.lider))
        self.assertTrue(_user_can_access_bladder(self.operador1))
        self.assertTrue(_user_can_access_bladder(self.apoio_user))
        self.assertTrue(_user_can_access_bladder(self.superuser))

        self.assertFalse(_user_can_access_bladder(self.user_maint))
        self.assertFalse(_user_can_access_bladder(self.user_prod))
        self.assertFalse(_user_can_access_bladder(self.user_matriz))
        self.assertFalse(_user_can_access_bladder(self.user_staff))
        self.assertFalse(_user_can_access_bladder(self.sem_acesso))

    def test_20_redirecionamento_pos_login_respeita_perfil(self):
        """20. Redirecionamento pós-login (home_redirect): Líder -> /bladder/, Operador -> /bladder/operador/."""
        # 1. Líder
        res_lider = self.client_lider.get(reverse("home_redirect"))
        self.assertEqual(res_lider.status_code, 302)
        self.assertIn("/bladder/", res_lider.url)
        self.assertNotIn("/operador/", res_lider.url)

        # 2. Operador
        res_op = self.client_op1.get(reverse("home_redirect"))
        self.assertEqual(res_op.status_code, 302)
        self.assertIn("/bladder/operador/", res_op.url)

        # 3. Apoio
        res_apoio = self.client_apoio.get(reverse("home_redirect"))
        self.assertEqual(res_apoio.status_code, 302)
        self.assertIn("/bladder/operador/", res_apoio.url)

        # 4. Usuário com múltiplos acessos (ex: Bladder + Produção) -> portal_select
        grp_prod = Group.objects.get(name="Liderança de Produção")
        self.lider.groups.add(grp_prod)
        res_multi = self.client_lider.get(reverse("home_redirect"))
        self.assertEqual(res_multi.status_code, 302)
        self.assertIn("/portal/", res_multi.url)

    def test_21_perfil_operacional_inativo_bloqueia_acesso(self):
        """21. Perfil operacional inativo (ativo=False) bloqueia operação normal."""
        self.perfil_op1.ativo = False
        self.perfil_op1.save()

        self.assertFalse(_user_can_access_bladder(self.operador1))
        res = self.client_op1.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/portal/", res.url)

    def test_22_operador_acessa_dashboard_redireciona_operador(self):
        """22. Operador tentando acessar /bladder/ diretamente é redirecionado para /bladder/operador/."""
        res = self.client_op1.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn("/bladder/operador/", res.url)


class BladderEtapa1OrdensListaTestCase(BladderBaseTestCase):
    def setUp(self):
        super().setUp()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

    def test_ordens_lista_exibe_colunas_completas(self):
        """Valida que a listagem de ordens renderiza todas as colunas estruturais solicitadas."""
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 40, usuario=self.lider
        )
        res = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, op.numero_ordem)
        self.assertContains(res, "Processo / Equipamento")
        self.assertContains(res, "Saldo Gerado")
        self.assertContains(res, self.processo.nome)
        self.assertContains(res, self.produto_bla1.codigo)

    def test_ordens_lista_op_parcial_exibe_bloco_pendencia_completo(self):
        """Valida que OP parcial exibe claramente o saldo pendente, motivo, turma e data de fechamento."""
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 50, usuario=self.lider
        )
        # Operador aponta 35 un e encerra parcial com motivo
        registrar_ou_atualizar_apontamento(
            op.pk, self.operador1, 35, "PARCIAL", motivo_desvio="Queda de pressão na prensa"
        )
        encerrar_op_parcial_ou_total(op.pk, self.lider, motivo_encerramento="Queda de pressão na prensa")

        op.refresh_from_db()
        self.assertEqual(op.status, "PARCIAL")
        self.assertEqual(op.saldo_gerado, 15)

        res = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "PENDÊNCIA REGISTRADA")
        self.assertContains(res, "15 un")
        self.assertContains(res, "Queda de pressão na prensa")
        self.assertContains(res, op.turma_responsavel_fechamento)


class BladderEtapa2PendenciasTestCase(BladderBaseTestCase):
    """
    Testes da ETAPA 2: Decisão explícita de incorporação de pendências.
    Valida remoção do automatismo FIFO, manutenção do saldo como PENDENTE quando ignorado,
    incorporação explícita total/parcial, anti-duplo consumo, cancelamento de OP destino e API.
    """
    def setUp(self):
        super().setUp()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

    def test_criar_op_sem_pendencias_anteriores(self):
        """Criação de OP quando não há pendências não incorpora nada."""
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 30, usuario=self.lider
        )
        self.assertEqual(op.quantidade_nova, 30)
        self.assertEqual(op.saldo_anterior_incorporado, 0)
        self.assertEqual(op.quantidade_planejada, 30)
        self.assertEqual(SaldoPendenteBladder.objects.filter(produto=self.produto_bla1).count(), 0)

    def test_criar_op_com_pendencia_decisao_ignorar(self):
        """Quando o líder escolhe IGNORAR, o saldo continua PENDENTE e nova OP tem apenas a demanda nova."""
        # 1. OP Origem com saldo de 3 un
        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 30, usuario=self.lider
        )
        registrar_ou_atualizar_apontamento(op1.pk, self.operador1, 27, "PARCIAL", motivo_desvio="Problema no equipamento")
        encerrar_op_parcial_ou_total(op1.pk, self.lider, motivo_encerramento="Problema no equipamento")

        saldo = SaldoPendenteBladder.objects.get(op_origem=op1)
        self.assertEqual(saldo.quantidade, 3)
        self.assertEqual(saldo.status, "PENDENTE")

        # 2. Líder cria nova OP com 20 un e escolhe IGNORAR
        post_data = {
            "processo": self.processo.pk,
            "produto": self.produto_bla1.pk,
            "data_programada": timezone.localdate().strftime("%Y-%m-%d"),
            "quantidade_nova": 20,
            "prioridade": "NORMAL",
            "decisao_pendencias": "IGNORAR",
        }
        res = self.client_lider.post(reverse("bladder:ordem_nova"), post_data)
        self.assertEqual(res.status_code, 302)

        op2 = OrdemProducaoBladder.objects.order_by("-id").first()
        self.assertEqual(op2.quantidade_nova, 20)
        self.assertEqual(op2.saldo_anterior_incorporado, 0)
        self.assertEqual(op2.quantidade_planejada, 20)

        # Saldo continua PENDENTE e livre
        saldo.refresh_from_db()
        self.assertEqual(saldo.status, "PENDENTE")
        self.assertIsNone(saldo.op_destino)

    def test_criar_op_com_pendencia_decisao_incorporar(self):
        """Quando o líder escolhe INCORPORAR, o saldo é incorporado e vinculado à nova OP destino."""
        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 30, usuario=self.lider
        )
        registrar_ou_atualizar_apontamento(op1.pk, self.operador1, 27, "PARCIAL", motivo_desvio="Problema no equipamento")
        encerrar_op_parcial_ou_total(op1.pk, self.lider, motivo_encerramento="Problema no equipamento")
        saldo = SaldoPendenteBladder.objects.get(op_origem=op1)

        post_data = {
            "processo": self.processo.pk,
            "produto": self.produto_bla1.pk,
            "data_programada": timezone.localdate().strftime("%Y-%m-%d"),
            "quantidade_nova": 20,
            "prioridade": "NORMAL",
            "decisao_pendencias": "INCORPORAR",
            "saldos_selecionados": [saldo.id],
        }
        res = self.client_lider.post(reverse("bladder:ordem_nova"), post_data)
        self.assertEqual(res.status_code, 302)

        op2 = OrdemProducaoBladder.objects.order_by("-id").first()
        self.assertEqual(op2.quantidade_nova, 20)
        self.assertEqual(op2.saldo_anterior_incorporado, 3)
        self.assertEqual(op2.quantidade_planejada, 23)

        saldo.refresh_from_db()
        self.assertEqual(saldo.status, "INCORPORADO")
        self.assertEqual(saldo.op_destino, op2)
        self.assertIsNotNone(saldo.data_incorporacao)

    def test_evitar_consumo_duplo_apos_incorporacao(self):
        """Saldo já incorporado não pode ser consumido em uma terceira OP."""
        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 30, usuario=self.lider
        )
        registrar_ou_atualizar_apontamento(op1.pk, self.operador1, 27, "PARCIAL")
        encerrar_op_parcial_ou_total(op1.pk, self.lider)
        saldo = SaldoPendenteBladder.objects.get(op_origem=op1)

        # Incorpora na OP 2
        op2 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 20,
            saldos_selecionados_ids=[saldo.id], usuario=self.lider
        )
        self.assertEqual(op2.saldo_anterior_incorporado, 3)

        # Tenta incorporar na OP 3 passando o mesmo ID de saldo
        op3 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 15,
            saldos_selecionados_ids=[saldo.id], usuario=self.lider
        )
        # Não deve incorporar pois já não está PENDENTE
        self.assertEqual(op3.saldo_anterior_incorporado, 0)
        self.assertEqual(op3.quantidade_planejada, 15)

    def test_multiplas_pendencias_incorporacao_seletiva(self):
        """Permite selecionar apenas uma das pendências quando houver várias."""
        # Cria 2 OPs parciais gerando 2 saldos: 4 un e 6 un
        op1 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, timezone.localdate(), 10, usuario=self.lider)
        registrar_ou_atualizar_apontamento(op1.pk, self.operador1, 6, "PARCIAL")
        encerrar_op_parcial_ou_total(op1.pk, self.lider)
        saldo1 = SaldoPendenteBladder.objects.get(op_origem=op1)  # 4 un

        op2 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, timezone.localdate(), 10, usuario=self.lider)
        registrar_ou_atualizar_apontamento(op2.pk, self.operador1, 4, "PARCIAL")
        encerrar_op_parcial_ou_total(op2.pk, self.lider)
        saldo2 = SaldoPendenteBladder.objects.get(op_origem=op2)  # 6 un

        # Seleciona apenas saldo1 (4 un)
        op3 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 25,
            saldos_selecionados_ids=[saldo1.id], usuario=self.lider
        )
        self.assertEqual(op3.quantidade_nova, 25)
        self.assertEqual(op3.saldo_anterior_incorporado, 4)
        self.assertEqual(op3.quantidade_planejada, 29)

        saldo1.refresh_from_db()
        saldo2.refresh_from_db()
        self.assertEqual(saldo1.status, "INCORPORADO")
        self.assertEqual(saldo2.status, "PENDENTE")

    def test_cancelamento_op_destino_reabre_saldo(self):
        """Ao cancelar uma OP que incorporou saldo, o saldo volta para PENDENTE."""
        from .services import cancelar_ordem_producao

        op1 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, timezone.localdate(), 30, usuario=self.lider)
        registrar_ou_atualizar_apontamento(op1.pk, self.operador1, 25, "PARCIAL")
        encerrar_op_parcial_ou_total(op1.pk, self.lider)
        saldo = SaldoPendenteBladder.objects.get(op_origem=op1)

        op2 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 20,
            saldos_selecionados_ids=[saldo.id], usuario=self.lider
        )
        saldo.refresh_from_db()
        self.assertEqual(saldo.status, "INCORPORADO")

        # Cancela OP 2
        cancelar_ordem_producao(op2.pk, "Cancelamento para teste de reabertura", self.lider)

        saldo.refresh_from_db()
        self.assertEqual(saldo.status, "PENDENTE")
        self.assertIsNone(saldo.op_destino)
        self.assertIsNone(saldo.data_incorporacao)

    def test_api_saldo_produto_retorna_pendencias_detalhadas(self):
        """API retorna lista rica de pendências para exibição do card de aviso."""
        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 30, usuario=self.lider
        )
        registrar_ou_atualizar_apontamento(op1.pk, self.operador1, 27, "PARCIAL", motivo_desvio="Problema na prensa")
        encerrar_op_parcial_ou_total(op1.pk, self.lider, motivo_encerramento="Problema na prensa")

        res = self.client_lider.get(reverse("bladder:api_saldo_produto", args=[self.produto_bla1.pk]))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_saldo_pendente"], 3)
        self.assertEqual(data["quantidade_registros"], 1)
        self.assertEqual(len(data["pendencias"]), 1)

        p = data["pendencias"][0]
        self.assertEqual(p["op_origem_numero"], op1.numero_ordem)
        self.assertEqual(p["modelo"], self.produto_bla1.codigo)
        self.assertEqual(p["saldo"], 3)
        self.assertEqual(p["quantidade_programada"], 30)
        self.assertEqual(p["quantidade_realizada"], 27)
        self.assertIn("Problema na prensa", p["motivo"])


class BladderEtapa3OperadorBoardTestCase(BladderBaseTestCase):
    """
    Testes da ETAPA 3: Quadro Operacional do Turno para Tablet / Chão de Fábrica.
    Valida remoção do fluxo contínuo de apontamento/iniciar, exibição de cards compactos,
    detalhes técnicos ET.029 reais e isolamento rigoroso de permissões.
    """
    def setUp(self):
        super().setUp()
        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

    def test_operador_visualiza_quadro_operacional_do_turno(self):
        """Operador acessa o quadro operacional e visualiza as atividades programadas para o turno."""
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 40, prioridade="ALTA", usuario=self.lider
        )
        res = self.client_op1.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "QUADRO OPERACIONAL")
        self.assertContains(res, op.numero_ordem)
        self.assertContains(res, self.produto_bla1.codigo)
        self.assertContains(res, "40")
        self.assertContains(res, "Ver Detalhes Técnicos")

    def test_operador_quadro_nao_contem_iniciar_nem_meus_apontamentos(self):
        """O quadro operacional NÃO contém mais botão de Iniciar Produção nem tabela de Meus Apontamentos."""
        criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 30, usuario=self.lider
        )
        res = self.client_op1.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "INICIAR PRODUÇÃO")
        self.assertNotContains(res, "Meus Apontamentos Registrados Hoje")
        self.assertNotContains(res, "Corrigir quantidade lançada")

    def test_detalhes_tecnicos_modal_exibe_parametros_et029_reais(self):
        """Modal de detalhes técnicos exibe especificações ET.029 reais existentes no banco."""
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, timezone.localdate(), 25, usuario=self.lider
        )
        res = self.client_op1.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Ficha Técnica")
        self.assertContains(res, "Especificações Técnicas do Modelo (ET.029)")
        if self.produto_bla1.matriz_extrusao:
            self.assertContains(res, self.produto_bla1.matriz_extrusao)
        # Decimal localizado pelo Django (ex: '2,500' em pt-br ou '2.500' em en)
        html = res.content.decode("utf-8")
        self.assertTrue("2,500" in html or "2.500" in html)

    def test_operador_continua_estritamente_sem_acesso_gerencial(self):
        """Operador não pode acessar dashboard gerencial, ordens, nova OP, relatórios ou calendário."""
        # Dashboard redireciona para operador
        res_dash = self.client_op1.get(reverse("bladder:dashboard"))
        self.assertEqual(res_dash.status_code, 302)
        self.assertIn("/bladder/operador/", res_dash.url)

        # Gestão, nova OP, relatórios e calendário redirecionam operador para /bladder/operador/
        for rota in ["bladder:ordens_lista", "bladder:ordem_nova", "bladder:relatorios", "bladder:cronograma"]:
            res = self.client_op1.get(reverse(rota))
            self.assertEqual(res.status_code, 302, f"Operador não deveria acessar {rota} diretamente")
            self.assertIn("/bladder/operador/", res.url)

        # Requisição AJAX bloqueia estritamente com 403
        for rota in ["bladder:ordens_lista", "bladder:ordem_nova", "bladder:relatorios", "bladder:cronograma"]:
            res_ajax = self.client_op1.get(reverse(rota), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(res_ajax.status_code, 403)


class BladderEtapa4FechamentoTurnoTestCase(BladderBaseTestCase):
    """
    Testes da ETAPA 4: Fechamento Único de Turno auditável pelo Operador.
    Valida encerramento total, parcial, não realizado, motivos obrigatórios,
    bloqueio de sobreprodução silenciosa, proteção contra fechamento duplicado,
    verificação de escala/turma, e geração do ledger de saldos.
    """
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.config_escala.data_referencia = self.hoje
        self.config_escala.turma_referencia = "TURMA_A"
        self.config_escala.save()
        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

    def test_fechamento_tudo_concluido(self):
        """Todas as OPs cumpridas integralmente: gera fechamento, OPs concluídas e zero saldos no ledger."""
        from .services import executar_fechamento_turno
        from .models import FechamentoTurnoBladder

        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider
        )
        fechamento = executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 30,
                'motivo': '',
                'motivo_outro': '',
                'observacao': 'Tudo ok'
            }]
        )
        self.assertEqual(fechamento.status, "CONCLUIDO")
        op.refresh_from_db()
        self.assertEqual(op.status, "CONCLUIDA")
        self.assertEqual(op.quantidade_realizada, 30)
        self.assertEqual(SaldoPendenteBladder.objects.filter(fechamento=fechamento).count(), 0)

    def test_fechamento_uma_parcial_gera_saldo_e_motivo(self):
        """Fechamento parcial: OP fica PARCIAL, gera SaldoPendenteBladder e exige motivo."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider
        )
        fechamento = executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Prensa oscilou pressão'
            }]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, "PARCIAL")
        self.assertEqual(op.quantidade_realizada, 27)

        # Ledger de saldo
        saldo = SaldoPendenteBladder.objects.get(fechamento=fechamento)
        self.assertEqual(saldo.quantidade, 3)
        self.assertEqual(saldo.status, "PENDENTE")
        self.assertEqual(saldo.op_origem, op)

    def test_fechamento_nao_realizada(self):
        """OP com zero peças produzidas: gera saldo integral no ledger com justificativa."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 20, usuario=self.lider
        )
        fechamento = executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 0,
                'motivo': 'FALTA_MATERIA_PRIMA',
                'motivo_outro': '',
                'observacao': 'Sem tarugo composto'
            }]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, "PARCIAL")
        self.assertEqual(op.quantidade_realizada, 0)

        saldo = SaldoPendenteBladder.objects.get(fechamento=fechamento)
        self.assertEqual(saldo.quantidade, 20)

    def test_fechamento_varias_ops(self):
        """Fechamento consolidado contendo múltiplas OPs do turno simultaneamente."""
        from .services import executar_fechamento_turno

        op1 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 25, usuario=self.lider)
        op2 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla2, self.hoje, 35, usuario=self.lider)

        fechamento = executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[
                {'ordem_id': op1.id, 'quantidade_realizada': 25, 'motivo': '', 'motivo_outro': '', 'observacao': ''},
                {'ordem_id': op2.id, 'quantidade_realizada': 30, 'motivo': 'PROBLEMA_OPERACIONAL', 'motivo_outro': '', 'observacao': 'Falha operacional no ciclo'},
            ]
        )
        self.assertEqual(fechamento.itens.count(), 2)
        op1.refresh_from_db()
        op2.refresh_from_db()
        self.assertEqual(op1.status, "CONCLUIDA")
        self.assertEqual(op2.status, "PARCIAL")
        self.assertEqual(SaldoPendenteBladder.objects.filter(fechamento=fechamento).count(), 1)
        self.assertEqual(SaldoPendenteBladder.objects.get(fechamento=fechamento).quantidade, 5)

    def test_fechamento_motivo_obrigatorio_quando_saldo_positivo(self):
        """Falha se OP não foi cumprida integralmente e o motivo não foi fornecido."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        with self.assertRaises(ValueError) as cm:
            executar_fechamento_turno(
                data_turno=self.hoje,
                operador=self.operador1,
                itens_dados=[{
                    'ordem_id': op.id,
                    'quantidade_realizada': 20,
                    'motivo': '',
                    'motivo_outro': '',
                    'observacao': ''
                }]
            )
        self.assertIn("o motivo do não cumprimento integral é obrigatório", str(cm.exception))

    def test_fechamento_outro_motivo_exige_descricao(self):
        """Se o motivo for 'OUTRO', a descrição textual é mandatória."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        with self.assertRaises(ValueError) as cm:
            executar_fechamento_turno(
                data_turno=self.hoje,
                operador=self.operador1,
                itens_dados=[{
                    'ordem_id': op.id,
                    'quantidade_realizada': 25,
                    'motivo': 'OUTRO',
                    'motivo_outro': '',
                    'observacao': ''
                }]
            )
        self.assertIn("a descrição do ocorrido ('O que aconteceu?') é obrigatória", str(cm.exception))

    def test_fechamento_permite_sobreproducao_com_excedente(self):
        """Permite quantidade realizada superior à meta programada, marcando CONCLUIDA com excedente."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        fechamento = executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 35,
                'motivo': '',
                'motivo_outro': '',
                'observacao': ''
            }]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, "CONCLUIDA")
        self.assertEqual(op.quantidade_realizada, 35)
        self.assertEqual(op.excedente, 5)
        self.assertEqual(op.saldo_gerado, 0)
        self.assertEqual(SaldoPendenteBladder.objects.filter(fechamento=fechamento).count(), 0)

    def test_fechamento_idempotencia_duplo_submit(self):
        """Tentativa de fechar um mesmo turno mais de uma vez é impedida com erro claro."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 30, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
        )
        with self.assertRaises(ValueError) as cm:
            executar_fechamento_turno(
                data_turno=self.hoje,
                operador=self.operador1,
                itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 30, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
            )
        self.assertIn("já foi encerrado", str(cm.exception))

    def test_fechamento_turma_errada_bloqueada(self):
        """Operador da Turma B não pode fechar turno da Turma A."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        # self.operador2 é da Turma B, mas a escala de hoje (1/1/2026 em diante) é Turma A
        with self.assertRaises(PermissionError) as cm:
            executar_fechamento_turno(
                data_turno=self.hoje,
                operador=self.operador2,
                itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 30, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
            )
        self.assertIn("pertence à Turma B, mas a escala de hoje é Turma A", str(cm.exception))

    def test_fechamento_lider_nao_realiza_fechamento_operacional_normal(self):
        """O líder não realiza o fechamento operacional normal do turno (função do operador)."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        with self.assertRaises(PermissionError) as cm:
            executar_fechamento_turno(
                data_turno=self.hoje,
                operador=self.lider,
                itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 30, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
            )
        self.assertIn("deve ser realizado pelo operador de máquina", str(cm.exception))

    def test_fechamento_sem_ops_bloqueado(self):
        """Não é possível fechar turno se não houver OPs programadas para a data."""
        from .services import executar_fechamento_turno

        with self.assertRaises(ValueError) as cm:
            executar_fechamento_turno(
                data_turno=self.hoje,
                operador=self.operador1,
                itens_dados=[]
            )
        self.assertIn("Não existem ordens de produção programadas", str(cm.exception))

    def test_fechamento_fluxo_web_post(self):
        """Operador acessa a tela de fechamento via GET e submete o formulário via POST com sucesso."""
        op = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)

        # GET carrega tela
        res_get = self.client_op1.get(reverse("bladder:fechamento_turno"))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "FECHAMENTO DO TURNO")
        self.assertContains(res_get, op.numero_ordem)

        # POST realiza fechamento com 28 un (parcial com saldo 2)
        post_data = {
            f"qtd_realizada_{op.id}": 28,
            f"motivo_{op.id}": "ALTERACAO_PROGRAMACAO",
            f"motivo_outro_{op.id}": "",
            f"obs_{op.id}": "Alteração orientada",
            "observacoes_gerais": "Fechamento regular do turno",
        }
        res_post = self.client_op1.post(reverse("bladder:fechamento_turno"), post_data)
        self.assertEqual(res_post.status_code, 302)

        op.refresh_from_db()
        self.assertEqual(op.status, "PARCIAL")
        self.assertEqual(op.quantidade_realizada, 28)
        self.assertEqual(SaldoPendenteBladder.objects.filter(op_origem=op).count(), 1)
        self.assertEqual(SaldoPendenteBladder.objects.get(op_origem=op).quantidade, 2)


class BladderEtapa5DashboardTestCase(BladderBaseTestCase):
    """
    Testes da ETAPA 5 — DASHBOARD DO LÍDER:
    - Simplificação do painel executivo (remoção de tabelas de consumo de matéria-prima e estoque teórico)
    - Indicadores principais: Programadas, Concluídas, Parciais, Pendências no Ledger, Atrasadas
    - Seção Motivos das Pendências com quantidade de peças e ocorrências por causa-raiz
    - Cálculo dinâmico de atraso via ConfiguracaoEscalaBladder.hora_fim (sem hardcode de 18:00)
    - OP concluída ou parcial não é atrasada após fechamento
    - Operador continua bloqueado de acessar o Dashboard gerencial
    """

    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.ontem = self.hoje - datetime.timedelta(days=1)
        self.config_escala.data_referencia = self.hoje
        self.config_escala.turma_referencia = "TURMA_A"
        self.config_escala.hora_fim = datetime.time(18, 0)
        self.config_escala.save()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)
        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

    def test_dashboard_indicadores_principais_e_simplificacao(self):
        """Dashboard exibe os indicadores principais e não contém mais tabelas de tarugos teóricos."""
        # Cria OPs para hoje
        op1 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        op2 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla2, self.hoje, 20, usuario=self.lider)

        res = self.client_lider.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 200)

        # Indicadores presentes
        self.assertContains(res, "Programadas Hoje")
        self.assertContains(res, "Realizado Hoje")
        self.assertContains(res, "Concluídas")
        self.assertContains(res, "Parciais")
        self.assertContains(res, "Pendências (Ledger)")
        self.assertContains(res, "Atrasadas")

        # Verifica que Previsão de Matéria-Prima (Tarugos) foi removida do dashboard principal
        self.assertNotContains(res, "Previsão de Matéria-Prima (Tarugos)")
        self.assertNotContains(res, "Consumo Teórico Calculado")

    def test_dashboard_motivos_das_pendencias(self):
        """Dashboard agrupa e exibe as quantidades por motivo de pendência com base nos saldos abertos."""
        from .services import executar_fechamento_turno

        # Cria OP e fecha parcialmente com motivo EQUIPAMENTO
        op1 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider)
        # Cria segunda OP e fecha com motivo QUALIDADE
        op2 = criar_ordem_producao_com_saldos(self.processo, self.produto_bla2, self.hoje, 25, usuario=self.lider)

        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[
                {
                    'ordem_id': op1.id,
                    'quantidade_realizada': 20,
                    'motivo': 'PROBLEMA_EQUIPAMENTO',
                    'motivo_outro': '',
                    'observacao': 'Falha hidráulica'
                },
                {
                    'ordem_id': op2.id,
                    'quantidade_realizada': 22,
                    'motivo': 'PROBLEMA_QUALIDADE',
                    'motivo_outro': '',
                    'observacao': 'Bolha na borracha'
                }
            ]
        )

        res = self.client_lider.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 200)

        # Verifica seção Motivos das Pendências
        self.assertContains(res, "Motivos das Pendências")
        self.assertContains(res, "Problema de equipamento")
        self.assertContains(res, "10 un")
        self.assertContains(res, "Problema de qualidade")
        self.assertContains(res, "3 un")
        self.assertContains(res, "13 un pendentes")

    def test_calculo_dinamico_atraso_escala_sem_hardcode(self):
        """Verifica que o atraso respeita ConfiguracaoEscalaBladder.hora_fim dinamicamente."""
        # 1. OP do passado está atrasada se pendente
        op_ontem = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-ATRASADA-ONTEM",
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=self.ontem,
            turma_prevista="TURMA_A",
            quantidade_nova=20,
            quantidade_planejada=20,
            status="PENDENTE",
            criado_por=self.lider
        )
        self.assertTrue(op_ontem.esta_atrasada())

        # 2. Se a OP de ontem for concluída ou parcial, NÃO está atrasada
        op_ontem.status = "CONCLUIDA"
        op_ontem.save()
        self.assertFalse(op_ontem.esta_atrasada())

        # 3. OP de hoje com hora_fim configurada no futuro (23:59:59) -> NÃO está atrasada
        self.config_escala.hora_fim = datetime.time(23, 59, 59)
        self.config_escala.save()

        op_hoje = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-HOJE-FUTURA",
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=self.hoje,
            turma_prevista="TURMA_A",
            quantidade_nova=15,
            quantidade_planejada=15,
            status="PENDENTE",
            criado_por=self.lider
        )
        self.assertFalse(op_hoje.esta_atrasada())

        # 4. OP de hoje com hora_fim configurada no passado (00:00:01) -> ESTÁ atrasada
        self.config_escala.hora_fim = datetime.time(0, 0, 1)
        self.config_escala.save()
        self.assertTrue(op_hoje.esta_atrasada())

        # 5. Fechou turno com parcial -> reflete fechamento e NÃO está atrasada
        op_hoje.status = "PARCIAL"
        op_hoje.save()
        self.assertFalse(op_hoje.esta_atrasada())

    def test_operador_bloqueado_de_acessar_dashboard(self):
        """Operador que tenta acessar o dashboard é redirecionado para o modo Chão de Fábrica."""
        res = self.client_op1.get(reverse("bladder:dashboard"))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("bladder:operador"), res.url)


class BladderEtapa6RelatoriosTestCase(BladderBaseTestCase):
    """
    Testes da ETAPA 6 — RELATÓRIOS:
    - Revisão integral de fórmulas e fontes de dados: a fonte de realizada é o Fechamento do Turno.
    - Fórmula de cumprimento: realizado / programado * 100 com precisão decimal (59/113 = 52,21%).
    - Não divisão por zero quando programado = 0.
    - Evitar dupla contagem em pendências incorporadas em OPs posteriores.
    - Produção por turma: Turma A, Turma B e Total.
    - Produção por modelo com código, descrição, programado, realizado, saldo e atingimento.
    - Exportação Excel usando a mesma lógica com sanitização contra injeção de fórmulas.
    """

    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.config_escala.data_referencia = self.hoje
        self.config_escala.turma_referencia = "TURMA_A"
        self.config_escala.save()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)
        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

    def test_formula_matematica_e_formatacao_percentuais(self):
        """Valida que formatar_percentual atende aos exemplos canônicos da SPEC."""
        from .views import formatar_percentual

        # 40 / 40 = 100%
        self.assertEqual(formatar_percentual(100.0), "100%")
        # 27 / 30 = 90%
        self.assertEqual(formatar_percentual(90.0), "90%")
        # 59 / 113 ≈ 52,21% (NÃO apresentar 59%)
        pct_59_113 = (59 / 113) * 100
        self.assertEqual(formatar_percentual(pct_59_113), "52,21%")
        # Zero divisão / programado 0
        self.assertEqual(formatar_percentual(0.0), "0%")
        self.assertEqual(formatar_percentual(None), "-")

    def test_relatorio_mensal_e_producao_por_fechamento(self):
        """Relatório reflete a produção realizada através dos fechamentos de turno."""
        from .services import executar_fechamento_turno

        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider
        )

        # Operador fecha turno realizando 27 un (saldo 3)
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Falha na prensa'
            }]
        )

        res = self.client_lider.get(
            reverse("bladder:relatorios"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res.status_code, 200)

        # Verifica totais no contexto
        self.assertEqual(res.context['total_programado'], 30)
        self.assertEqual(res.context['total_realizado'], 27)
        self.assertEqual(res.context['saldo_pendente_total'], 3)
        self.assertEqual(res.context['percentual_geral_display'], "90%")

        # Verifica que o HTML renderiza os dados
        self.assertContains(res, "30 <span class=\"fs-6 text-muted\">un</span>")
        self.assertContains(res, "27 <span class=\"fs-6 text-muted\">un</span>")
        self.assertContains(res, "90%")
        self.assertContains(res, "Turma A")
        self.assertContains(res, "27 un")

    def test_relatorio_sem_dupla_contagem_na_incorporacao(self):
        """
        OP 1: programado 30, realizado 27 -> saldo 3.
        OP 2: nova demanda 20, incorpora 3 -> total 23, realizado 23.
        Total realizado deve ser 27 + 23 = 50 (sem dupla contagem).
        """
        from .services import executar_fechamento_turno

        # 1. Encontra dois dias consecutivos garantidos dentro do mesmo mês
        if self.hoje.day > 1:
            data_op1 = self.hoje.replace(day=self.hoje.day - 1)
            data_op2 = self.hoje
        else:
            data_op1 = self.hoje
            data_op2 = self.hoje.replace(day=2)

        from .services import calcular_turma_do_dia
        turma1, _, _ = calcular_turma_do_dia(data_op1)
        op_fechamento1 = self.operador1 if turma1 == 'TURMA_A' else self.operador2
        op_fechamento2 = self.operador2 if turma1 == 'TURMA_A' else self.operador1

        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, data_op1, 30, usuario=self.lider
        )
        executar_fechamento_turno(
            data_turno=data_op1,
            operador=op_fechamento1,
            itens_dados=[{
                'ordem_id': op1.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Falha'
            }]
        )

        # 2. OP 2 no dia seguinte (mesmo mês)
        saldo_aberto = SaldoPendenteBladder.objects.get(status='PENDENTE', op_origem=op1)
        op2 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, data_op2, 20,
            saldos_selecionados_ids=[saldo_aberto.id],
            usuario=self.lider
        )
        self.assertEqual(op2.quantidade_planejada, 23)

        # Executa fechamento da OP 2 com operador do dia 2
        executar_fechamento_turno(
            data_turno=data_op2,
            operador=op_fechamento2,
            itens_dados=[{
                'ordem_id': op2.id,
                'quantidade_realizada': 23,
                'motivo': '',
                'motivo_outro': '',
                'observacao': 'Meta cumprida'
            }]
        )

        res = self.client_lider.get(
            reverse("bladder:relatorios"),
            {'mes': data_op1.month, 'ano': data_op1.year}
        )
        self.assertEqual(res.status_code, 200)

        # Total realizado deve ser exatamente 50 (27 + 23)
        self.assertEqual(res.context['total_realizado'], 50)
        # Total programado deve ser 30 + 23 = 53
        self.assertEqual(res.context['total_programado'], 53)
        # Produção por turma respeita quem operou cada dia (27 e 23)
        prod_esperado_a = 27 if turma1 == 'TURMA_A' else 23
        prod_esperado_b = 23 if turma1 == 'TURMA_A' else 27
        self.assertEqual(res.context['prod_turma_a'], prod_esperado_a)
        self.assertEqual(res.context['prod_turma_b'], prod_esperado_b)
        # Total turmas: 50
        self.assertEqual(res.context['prod_total_turmas'], 50)

    def test_relatorio_exportar_excel(self):
        """Exportação Excel é gerada com sucesso contendo as abas e cabeçalhos corretos."""
        import openpyxl

        criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider
        )

        res = self.client_lider.get(
            reverse("bladder:relatorios_exportar_excel"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", res['Content-Type'])

        wb = openpyxl.load_workbook(filename=io.BytesIO(res.content))
        self.assertIn(f"Ordens {self.hoje.month:02d}-{self.hoje.year}", wb.sheetnames)
        self.assertIn("Por Modelo", wb.sheetnames)
        self.assertIn("Resumo e Turmas", wb.sheetnames)


class BladderEtapa7CalendarioTestCase(BladderBaseTestCase):
    """
    Testes da ETAPA 7 — CALENDÁRIO:
    - Exibe programações com datas e turmas calculadas corretamente.
    - Líder pode clicar na OP para abrir detalhes.
    - Pendência NÃO é apresentada automaticamente como nova OP fantasma.
    - OP futura com pendência incorporada exibe indicador discreto (+X).
    - Reprogramação move a OP de data refletindo no calendário.
    - Operador continua sem acesso ao calendário (apontamento apenas no Chão de Fábrica).
    """

    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.config_escala.data_referencia = self.hoje
        self.config_escala.turma_referencia = "TURMA_A"
        self.config_escala.save()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)
        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

    def test_calendario_integracao_e_exibicao_ops(self):
        """Calendário exibe programações da data com turma calculada e link para a OP."""
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider
        )

        res = self.client_lider.get(
            reverse("bladder:cronograma"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, op.produto.codigo)
        self.assertContains(res, "Turma A")
        self.assertContains(res, reverse("bladder:ordem_detalhe", kwargs={'pk': op.pk}))

    def test_calendario_indicador_discreto_saldo_incorporado(self):
        """OP com saldo anterior incorporado exibe badge discreto no calendário."""
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-CAL-INC",
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=self.hoje,
            turma_prevista="TURMA_A",
            quantidade_nova=25,
            saldo_anterior_incorporado=5,
            quantidade_planejada=30,
            status="PENDENTE",
            criado_por=self.lider
        )

        res = self.client_lider.get(
            reverse("bladder:cronograma"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "+5")
        self.assertContains(res, "Saldo incorporado: +5 un")

    def test_calendario_pendencia_nao_gera_op_fantasma(self):
        """Saldo pendente no Ledger não deve aparecer como uma OP avulsa no calendário."""
        op_origem = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider
        )
        SaldoPendenteBladder.objects.create(
            op_origem=op_origem,
            produto=self.produto_bla1,
            quantidade=7,
            status='PENDENTE'
        )

        res = self.client_lider.get(
            reverse("bladder:cronograma"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res.status_code, 200)
        # Confirma que o número de OPs no banco continua sendo exatamente 1
        self.assertEqual(OrdemProducaoBladder.objects.count(), 1)

    def test_calendario_reprogramacao_move_op(self):
        """Reprogramar uma OP altera sua data de exibição no calendário."""
        from .services import reprogramar_ordem_producao

        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla1, self.hoje, 30, usuario=self.lider
        )
        nova_data = self.hoje + datetime.timedelta(days=2)
        reprogramar_ordem_producao(op.id, nova_data, "Manutenção preventiva na prensa", self.lider)

        res = self.client_lider.get(
            reverse("bladder:cronograma"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res.status_code, 200)
        op.refresh_from_db()
        self.assertEqual(op.data_programada, nova_data)

    def test_operador_bloqueado_de_acessar_calendario(self):
        """Operador não tem acesso ao calendário (redirecionado para o Chão de Fábrica)."""
        res = self.client_op1.get(reverse("bladder:cronograma"))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("bladder:operador"), res.url)


class BladderEtapa8FluxoCompletoTestCase(BladderBaseTestCase):
    """
    Testes de Integração do Fluxo Real (ETAPA 8):
    - CENÁRIO A: Tudo cumprido (Meta 30 -> Fechamento 30 -> Concluída -> Relatório 30 -> Sem saldo)
    - CENÁRIO B: Parcial (Meta 30 -> Fechamento 27 com motivo -> Parcial -> Ledger 3 -> Dashboard -> Relatório 90%)
    - CENÁRIO C: Líder ignora pendência (Existe pendência de 3 -> Líder cria OP com 20 ignorando -> OP 20 -> Saldo 3 continua PENDENTE)
    - CENÁRIO D: Líder incorpora pendência (Existe pendência 3 -> Cria 20 incorporando 3 -> Total 23 -> Fecha 23 -> Sem pendência)
    - CENÁRIO E: Parcial novamente (OP 23 -> Realiza 21 -> Novo saldo 2 -> Histórico do saldo 3 preservado como incorporado)
    - CENÁRIO F: Atraso dinâmico (Turno encerra sem fechamento -> Atrasada -> Fechamento realizado -> Reflete status final e não é mais atrasada)
    """

    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.config_escala.data_referencia = self.hoje
        self.config_escala.turma_referencia = "TURMA_A"
        self.config_escala.save()
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)
        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

        self.produto_bla6, _ = ProdutoBladder.objects.get_or_create(
            codigo="BLA006",
            defaults={
                'descricao': "Bladder 16/17-180",
                'matriz_extrusao': "MAT06",
                'peso_tarugo_kg': Decimal("3.200"),
                'peso_vulcanizado_kg': Decimal("2.850"),
                'ativo': True,
            }
        )

    def test_cenario_a_tudo_cumprido(self):
        """Cenário A: Líder cria OP BLA006=30 -> Chão de fábrica visualiza -> Fechamento 30 -> Concluída -> Relatório 30."""
        from .services import executar_fechamento_turno

        # 1. Líder cria OP BLA006 = 30
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, self.hoje, 30, usuario=self.lider
        )
        self.assertEqual(op.quantidade_planejada, 30)
        self.assertEqual(op.status, "PENDENTE")

        # 2. OP aparece no tablet (Chão de Fábrica)
        res_tablet = self.client_op1.get(reverse("bladder:operador"))
        self.assertEqual(res_tablet.status_code, 200)
        self.assertContains(res_tablet, op.numero_ordem)
        self.assertContains(res_tablet, "BLA006")
        self.assertContains(res_tablet, "30")

        # 3. Operador apenas consulta, sem apontamentos contínuos

        # 4. No final do turno abre Fechamento
        res_fech_get = self.client_op1.get(reverse("bladder:fechamento_turno"))
        self.assertEqual(res_fech_get.status_code, 200)
        self.assertContains(res_fech_get, op.numero_ordem)

        # 5. Informa realizado = 30 e fecha
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 30,
                'motivo': '',
                'motivo_outro': '',
                'observacao': 'Produção normal 100%'
            }]
        )

        # 7. OP = concluída
        op.refresh_from_db()
        self.assertEqual(op.status, "CONCLUIDA")
        self.assertEqual(op.quantidade_realizada, 30)

        # 8. Relatório recebe 30
        res_rel = self.client_lider.get(
            reverse("bladder:relatorios"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res_rel.status_code, 200)
        self.assertEqual(res_rel.context['total_realizado'], 30)
        self.assertEqual(res_rel.context['saldo_pendente_total'], 0)
        self.assertEqual(res_rel.context['percentual_geral_display'], "100%")

        # 9. Nenhuma pendência criada no Ledger
        self.assertEqual(SaldoPendenteBladder.objects.filter(op_origem=op).count(), 0)

    def test_cenario_b_parcial(self):
        """Cenário B: BLA006=30 -> Fechamento 27 (problema de equipamento) -> Parcial -> Ledger cria pendência 3 -> Dashboard e Relatório."""
        from .services import executar_fechamento_turno

        # 1. Líder cria BLA006 = 30
        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, self.hoje, 30, usuario=self.lider
        )

        # 2. Operador fecha turno com realizado = 27 e motivo problema de equipamento
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Pressão da prensa oscilou'
            }]
        )

        # 4. OP fica parcial
        op.refresh_from_db()
        self.assertEqual(op.status, "PARCIAL")
        self.assertEqual(op.quantidade_realizada, 27)

        # 5. Ledger cria pendência = 3
        saldos = SaldoPendenteBladder.objects.filter(op_origem=op, status='PENDENTE')
        self.assertEqual(saldos.count(), 1)
        saldo = saldos.first()
        self.assertEqual(saldo.quantidade, 3)

        # 6. Dashboard mostra a ocorrência e motivo
        res_dash = self.client_lider.get(reverse("bladder:dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertEqual(res_dash.context['parciais_dia'], 1)
        self.assertEqual(res_dash.context['total_saldos_pendentes_un'], 3)
        self.assertContains(res_dash, "Problema de equipamento")

        # 7. Relatório registra: programado 30, realizado 27, saldo 3, atingimento 90%
        res_rel = self.client_lider.get(
            reverse("bladder:relatorios"),
            {'mes': self.hoje.month, 'ano': self.hoje.year}
        )
        self.assertEqual(res_rel.context['total_programado'], 30)
        self.assertEqual(res_rel.context['total_realizado'], 27)
        self.assertEqual(res_rel.context['saldo_pendente_total'], 3)
        self.assertEqual(res_rel.context['percentual_geral_display'], "90%")

    def test_cenario_c_lider_ignora_pendencia(self):
        """Cenário C: Existe pendência de 3 BLA006 -> Líder cria OP=20 e ignora pendência -> OP criada com 20 -> Saldo 3 continua aberto."""
        from .services import executar_fechamento_turno

        # 1. Gera pendência de 3 BLA006
        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, self.hoje, 30, usuario=self.lider
        )
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op1.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Falha'
            }]
        )
        saldo_3 = SaldoPendenteBladder.objects.get(op_origem=op1, status='PENDENTE')
        self.assertEqual(saldo_3.quantidade, 3)

        # 2. Líder consulta API de pendências e o sistema avisa pendência de 3
        res_api = self.client_lider.get(
            reverse("bladder:api_saldo_produto", kwargs={'produto_id': self.produto_bla6.id})
        )
        self.assertEqual(res_api.status_code, 200)
        dados_api = res_api.json()
        self.assertEqual(dados_api['total_saldo_pendente'], 3)
        self.assertEqual(len(dados_api['pendencias']), 1)
        self.assertEqual(dados_api['pendencias'][0]['saldo'], 3)

        # 3. Líder cria nova programação BLA006 = 20 e seleciona IGNORAR POR ENQUANTO (lista vazia)
        amanha = self.hoje + datetime.timedelta(days=1)
        op2 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, amanha, 20,
            saldos_selecionados_ids=[],
            usuario=self.lider
        )

        # 5. OP criada com 20
        self.assertEqual(op2.quantidade_nova, 20)
        self.assertEqual(op2.saldo_anterior_incorporado, 0)
        self.assertEqual(op2.quantidade_planejada, 20)

        # 6. Pendência 3 continua aberta (PENDENTE) no Ledger
        saldo_3.refresh_from_db()
        self.assertEqual(saldo_3.status, 'PENDENTE')
        self.assertIsNone(saldo_3.op_destino)

    def test_cenario_d_lider_incorpora_pendencia(self):
        """Cenário D: Existe pendência 3 BLA006 -> Líder cria OP=20 incorporando 3 -> Total 23 -> Ledger liga OP origem e destino -> Fechamento 23 conclui."""
        from .services import executar_fechamento_turno

        # 1. Gera pendência de 3 BLA006
        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, self.hoje, 30, usuario=self.lider
        )
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op1.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Falha'
            }]
        )
        saldo_3 = SaldoPendenteBladder.objects.get(op_origem=op1, status='PENDENTE')

        # 2. Líder cria nova demanda = 20 e escolhe INCORPORAR
        amanha = self.hoje + datetime.timedelta(days=1)
        op2 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, amanha, 20,
            saldos_selecionados_ids=[saldo_3.id],
            usuario=self.lider
        )

        # 5. OP registra: nova 20, incorporada 3, total 23
        self.assertEqual(op2.quantidade_nova, 20)
        self.assertEqual(op2.saldo_anterior_incorporado, 3)
        self.assertEqual(op2.quantidade_planejada, 23)

        # 6. Ledger liga OP origem -> OP destino
        saldo_3.refresh_from_db()
        self.assertEqual(saldo_3.status, 'INCORPORADO')
        self.assertEqual(saldo_3.op_destino, op2)
        self.assertEqual(saldo_3.op_origem, op1)

        # 7. Fechamento com 23 conclui a nova OP
        executar_fechamento_turno(
            data_turno=amanha,
            operador=self.operador2,
            itens_dados=[{
                'ordem_id': op2.id,
                'quantidade_realizada': 23,
                'motivo': '',
                'motivo_outro': '',
                'observacao': 'Tudo concluído'
            }]
        )
        op2.refresh_from_db()
        self.assertEqual(op2.status, 'CONCLUIDA')

        # 8. Não sobra pendência anterior
        self.assertEqual(
            SaldoPendenteBladder.objects.filter(produto=self.produto_bla6, status='PENDENTE').count(),
            0
        )

    def test_cenario_e_parcial_novamente(self):
        """Cenário E: OP total 23 -> Realiza 21 -> Saldo novo = 2 -> Saldo antigo 3 permanece incorporado -> Novo ledger gera saldo 2 da OP atual."""
        from .services import executar_fechamento_turno

        # 1. Cria OP1 (30), fecha com 27 -> saldo 3
        op1 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, self.hoje, 30, usuario=self.lider
        )
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op1.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Falha inicial'
            }]
        )
        saldo_antigo = SaldoPendenteBladder.objects.get(op_origem=op1, status='PENDENTE')

        # 2. Cria OP2 (20 + 3 = 23)
        amanha = self.hoje + datetime.timedelta(days=1)
        op2 = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, amanha, 20,
            saldos_selecionados_ids=[saldo_antigo.id],
            usuario=self.lider
        )

        # 3. Operador realiza 21 no fechamento (novo saldo = 2)
        executar_fechamento_turno(
            data_turno=amanha,
            operador=self.operador2,
            itens_dados=[{
                'ordem_id': op2.id,
                'quantidade_realizada': 21,
                'motivo': 'FALTA_MATERIA_PRIMA',
                'motivo_outro': '',
                'observacao': 'Faltou tarugo no fim do turno'
            }]
        )

        op2.refresh_from_db()
        self.assertEqual(op2.status, 'PARCIAL')
        self.assertEqual(op2.quantidade_realizada, 21)

        # O saldo antigo de 3 permanece historicamente como incorporado
        saldo_antigo.refresh_from_db()
        self.assertEqual(saldo_antigo.status, 'INCORPORADO')
        self.assertEqual(saldo_antigo.quantidade, 3)
        self.assertEqual(saldo_antigo.op_origem, op1)
        self.assertEqual(saldo_antigo.op_destino, op2)

        # Novo ledger gera somente saldo 2 a partir da OP atual (op2)
        novo_saldo = SaldoPendenteBladder.objects.get(op_origem=op2)
        self.assertEqual(novo_saldo.quantidade, 2)
        self.assertEqual(novo_saldo.status, 'PENDENTE')
        self.assertEqual(novo_saldo.op_origem, op2)

    def test_cenario_f_atraso_dinamico_antes_e_depois_do_fechamento(self):
        """Cenário F: Turno passou do horário sem fechamento -> atrasada -> após fechamento -> reflete resultado final."""
        from .services import executar_fechamento_turno

        # 1. Configura hora_fim no passado (00:00:01)
        self.config_escala.hora_fim = datetime.time(0, 0, 1)
        self.config_escala.save()

        op = criar_ordem_producao_com_saldos(
            self.processo, self.produto_bla6, self.hoje, 30, usuario=self.lider
        )

        # 2. Turno passou do horário configurado e fechamento não foi realizado -> atrasada
        self.assertTrue(op.esta_atrasada())

        # 3. No dashboard a OP aparece como atrasada
        res_dash = self.client_lider.get(reverse("bladder:dashboard"))
        self.assertEqual(res_dash.context['total_atrasadas'], 1)

        # 4. Operador realiza fechamento
        executar_fechamento_turno(
            data_turno=self.hoje,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 30,
                'motivo': '',
                'motivo_outro': '',
                'observacao': 'Fechamento concluído com atraso'
            }]
        )

        # 5. Após fechamento, passa a refletir o resultado final (CONCLUIDA) e NÃO está mais atrasada
        op.refresh_from_db()
        self.assertEqual(op.status, 'CONCLUIDA')
        self.assertFalse(op.esta_atrasada())

        # 6. Dashboard não conta mais como atrasada
        res_dash2 = self.client_lider.get(reverse("bladder:dashboard"))
        self.assertEqual(res_dash2.context['total_atrasadas'], 0)
        self.assertEqual(res_dash2.context['concluidas_dia'], 1)
class BladderImportProdutosCommandTestCase(TestCase):
    """Testa o comando de importação da planilha ET.029 atualizada (BLA001 a BLA010)."""

    def test_import_produtos_bladder_atualizada(self):
        from django.core.management import call_command
        import io

        out = io.StringIO()
        call_command('import_produtos_bladder', stdout=out)
        output = out.getvalue()

        self.assertIn("Importação Concluída com Sucesso", output)
        self.assertIn("BLA010", output)

        # Valida que todos os 10 modelos existem
        self.assertEqual(ProdutoBladder.objects.count(), 10)

        # Valida o novo modelo BLA010
        bla10 = ProdutoBladder.objects.get(codigo="BLA010")
        self.assertEqual(bla10.matriz_extrusao, "MAT01")
        self.assertEqual(bla10.peso_tarugo_kg, Decimal("2.300"))
        self.assertEqual(bla10.comprimento_extrusao_cm, Decimal("170.00"))
        self.assertEqual(bla10.comprimento_chanfrado_cm, Decimal("175.00"))
        self.assertEqual(bla10.diametro_tarugo_mm, Decimal("38.00"))
        self.assertTrue(bla10.ativo)

        # Valida atualização do BLA001 com a nova matriz MAT01 e novo tarugo
        bla1 = ProdutoBladder.objects.get(codigo="BLA001")
        self.assertEqual(bla1.matriz_extrusao, "MAT01")
        self.assertEqual(bla1.comprimento_extrusao_cm, Decimal("170.00"))
        self.assertEqual(bla1.peso_tarugo_kg, Decimal("2.500"))

        # Valida idempotência: executar novamente não duplica
        out2 = io.StringIO()
        call_command('import_produtos_bladder', stdout=out2)
        self.assertEqual(ProdutoBladder.objects.count(), 10)


class BladderBloco1ChaoDeFabricaTestCase(TestCase):
    """
    Testes de Homologação Final para o Bloco 1:
    - Status visual: PROGRAMADA antes do fechamento (não PENDENTE)
    - Status pós-fechamento: CONCLUÍDA, PARCIAL / PENDÊNCIA, NÃO REALIZADA / PENDÊNCIA
    - Único botão FECHAR TURNO no topo (sem duplicidade)
    - 2 cards por linha em tablet (col-12 col-md-6)
    - Modal de Detalhes Técnicos presente
    - Menu simplificado para Operador (sem Dashboard, Calendário, Ordens, Nova OP, Relatórios)
    - Menu completo para Líder
    - Bloqueio seguro de URLs administrativas para Operador
    """

    def setUp(self):
        self.grupo_lider, _ = Group.objects.get_or_create(name='Liderança Bladder')
        self.grupo_op, _ = Group.objects.get_or_create(name='Operadores Bladder')

        self.lider = User.objects.create_user(username="lider_bloco1", password="password123", first_name="Líder Bladder")
        self.lider.groups.add(self.grupo_lider)

        self.operador = User.objects.create_user(username="operador_bloco1", password="password123", first_name="Operador Bladder")
        self.operador.groups.add(self.grupo_op)
        self.perfil_op = PerfilOperacionalBladder.objects.create(
            usuario=self.operador,
            turma='TURMA_A',
            ativo=True
        )

        self.hoje = timezone.localdate()
        self.escala = ConfiguracaoEscalaBladder.objects.create(
            data_referencia=self.hoje,
            turma_referencia='TURMA_A',
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        self.processo = ProcessoBladder.objects.create(
            codigo="01", nome="Prensa 01", tipo="PRENSA", ordem_exibicao=1, ativo=True
        )
        self.produto = ProdutoBladder.objects.create(
            codigo="BLA004",
            descricao="B250/12",
            matriz_extrusao="MAT03",
            peso_tarugo_kg=Decimal("3.100"),
            diametro_tarugo_mm=Decimal("42.00"),
            comprimento_extrusao_cm=Decimal("130.00"),
            comprimento_chanfrado_cm=Decimal("125.00"),
            tempo_vulcanizacao_min=120,
            ativo=True
        )

        self.client_op = Client()
        self.client_op.force_login(self.operador)

        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

    def test_status_visual_antes_do_fechamento_programada(self):
        """Operador vê OP aberta como PROGRAMADA e NÃO como Pendente."""
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLOCO1-001",
            processo=self.processo,
            produto=self.produto,
            data_programada=self.hoje,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            saldo_anterior_incorporado=0,
            quantidade_planejada=20,
            quantidade_realizada=0,
            status='PENDENTE',
            criado_por=self.lider
        )

        self.assertEqual(op.status_visual, "PROGRAMADA")

        res = self.client_op.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "PROGRAMADA")
        self.assertNotContains(res, '<span class="badge bg-secondary">Pendente</span>')

    def test_status_visual_pos_fechamento(self):
        """Após fechamento: CONCLUÍDA, PARCIAL / PENDÊNCIA e NÃO REALIZADA / PENDÊNCIA."""
        # 1. Concluída 100%
        op_conc = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLOCO1-CONC",
            processo=self.processo,
            produto=self.produto,
            data_programada=self.hoje,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            quantidade_realizada=20,
            status='CONCLUIDA',
            criado_por=self.lider
        )
        self.assertEqual(op_conc.status_visual, "CONCLUÍDA")

        # 2. Parcial com produção > 0
        op_parc = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLOCO1-PARC",
            processo=self.processo,
            produto=self.produto,
            data_programada=self.hoje,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            quantidade_realizada=15,
            status='PARCIAL',
            criado_por=self.lider
        )
        self.assertEqual(op_parc.status_visual, "PARCIAL / PENDÊNCIA")

        # 3. Não realizada (produção 0 com saldo)
        op_zero = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLOCO1-ZERO",
            processo=self.processo,
            produto=self.produto,
            data_programada=self.hoje,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            quantidade_realizada=0,
            status='PARCIAL',
            criado_por=self.lider
        )
        self.assertEqual(op_zero.status_visual, "NÃO REALIZADA / PENDÊNCIA")

    def test_apenas_um_botao_fechar_turno_no_topo(self):
        """Apenas UM botão principal FECHAR TURNO, no topo da tela, sem duplicidade no rodapé."""
        OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLOCO1-002",
            processo=self.processo,
            produto=self.produto,
            data_programada=self.hoje,
            turma_prevista='TURMA_A',
            quantidade_nova=10,
            quantidade_planejada=10,
            status='PENDENTE',
            criado_por=self.lider
        )

        res = self.client_op.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        # Conta a quantidade de ocorrências de "FECHAR TURNO" no HTML
        content = res.content.decode("utf-8")
        self.assertEqual(content.count("FECHAR TURNO"), 1)

    def test_cards_grid_tablet_e_detalhes_tecnicos(self):
        """Cards usam grid de ~2 por linha (col-12 col-md-6) e modal de detalhes técnicos."""
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLOCO1-003",
            processo=self.processo,
            produto=self.produto,
            data_programada=self.hoje,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            status='PENDENTE',
            criado_por=self.lider
        )

        res = self.client_op.get(reverse("bladder:operador"))
        self.assertContains(res, "col-12 col-md-6")
        self.assertContains(res, "Ver Detalhes Técnicos")
        self.assertContains(res, f"modalDetalhes{op.pk}")
        self.assertContains(res, "MAT03")
        # Aceita separador decimal de ponto ou vírgula
        content = res.content.decode("utf-8")
        self.assertTrue("3.100 kg" in content or "3,100 kg" in content)

    def test_menu_operador_simplificado(self):
        """Operador não vê menus administrativos de Dashboard, Calendário, Ordens, Nova OP e Relatórios."""
        res = self.client_op.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)

        # Não deve conter links de menu administrativo
        self.assertNotContains(res, 'href="/bladder/"')
        self.assertNotContains(res, "Dashboard")
        self.assertNotContains(res, reverse("bladder:cronograma"))
        self.assertNotContains(res, reverse("bladder:ordens_lista"))
        self.assertNotContains(res, reverse("bladder:ordem_nova"))
        self.assertNotContains(res, reverse("bladder:relatorios"))

        # Deve conter Chão de Fábrica
        self.assertContains(res, reverse("bladder:operador"))
        self.assertContains(res, "Chão de Fábrica")

    def test_menu_lider_completo(self):
        """Líder mantém todos os menus administrativos visíveis."""
        res = self.client_lider.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)

        self.assertContains(res, reverse("bladder:dashboard"))
        self.assertContains(res, reverse("bladder:cronograma"))
        self.assertContains(res, reverse("bladder:ordens_lista"))
        self.assertContains(res, reverse("bladder:ordem_nova"))
        self.assertContains(res, reverse("bladder:relatorios"))

    def test_acesso_direto_operador_bloqueado(self):
        """Operador digitando URLs administrativas recebe redirecionamento seguro para /bladder/operador/."""
        rotas_admin = [
            reverse("bladder:dashboard"),
            reverse("bladder:cronograma"),
            reverse("bladder:ordens_lista"),
            reverse("bladder:ordem_nova"),
            reverse("bladder:relatorios"),
            reverse("bladder:relatorios_exportar_excel"),
        ]
        for url in rotas_admin:
            res = self.client_op.get(url)
            self.assertRedirects(res, reverse("bladder:operador"))


class BladderBloco2RelatoriosTestCase(TestCase):
    """
    Testes de Homologação Final para o Bloco 2:
    - Indicadores matemáticos obrigatórios (40/40 -> 100%, 27/30 -> 90%, 59/113 -> 52,21%)
    - Divisão por zero segura
    - Filtros por mês/ano, turno (Todos, Turma A, Turma B) e modelo (Todos, específico)
    - Produção por turno (programado, realizado, saldo, % cumprimento de Turma A, Turma B e Total)
    - Produção por dia (Data, Turma A, Turma B, Total) e acumulado do período
    - Pendências do período originárias dos fechamentos com motivo
    - Prevenção absoluta contra dupla contagem de saldos incorporados
    - Exportação Excel contendo todas as abas
    """

    def setUp(self):
        self.grupo_lider, _ = Group.objects.get_or_create(name='Liderança Bladder')
        self.grupo_op, _ = Group.objects.get_or_create(name='Operadores Bladder')

        self.config_escala = ConfiguracaoEscalaBladder.objects.create(
            data_referencia=datetime.date(2026, 9, 1),
            turma_referencia='TURMA_A',
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        self.lider = User.objects.create_user(username="lider_bloco2", password="password123", first_name="Líder Bladder")
        self.lider.groups.add(self.grupo_lider)

        self.operador_a = User.objects.create_user(username="op_a_bloco2", password="password123", first_name="Operador A")
        self.operador_a.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.operador_a, turma='TURMA_A', ativo=True)

        self.operador_b = User.objects.create_user(username="op_b_bloco2", password="password123", first_name="Operador B")
        self.operador_b.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.operador_b, turma='TURMA_B', ativo=True)

        self.processo = ProcessoBladder.objects.create(
            codigo="01", nome="Prensa 01", tipo="PRENSA", ordem_exibicao=1, ativo=True
        )

        self.produto_bla4 = ProdutoBladder.objects.create(
            codigo="BLA004", descricao="B250/12", peso_tarugo_kg=Decimal("3.100"), ativo=True
        )
        self.produto_bla1 = ProdutoBladder.objects.create(
            codigo="BLA001", descricao="B200/16", peso_tarugo_kg=Decimal("2.500"), ativo=True
        )

        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

    def test_exemplos_obrigatorios_matematicos(self):
        """Valida cálculos exatos: 40/40 -> 100%, 27/30 -> 90%, 59/113 -> 52,21% e zero seguro."""
        from bladder.views import formatar_percentual

        # 40 / 40 -> 100%
        self.assertEqual(formatar_percentual(40 / 40 * 100), "100%")

        # 27 / 30 -> 90%
        self.assertEqual(formatar_percentual(27 / 30 * 100), "90%")

        # 59 / 113 -> 52,21%
        pct_59_113 = 59 / 113 * 100
        self.assertEqual(formatar_percentual(pct_59_113), "52,21%")

        # Zero programado -> "-"
        self.assertEqual(formatar_percentual(None), "-")

        # Zero realizado de 100 programado -> 0%
        self.assertEqual(formatar_percentual(0.0), "0%")

    def test_filtros_mes_ano_turno_e_modelo(self):
        """Todos os componentes respeitam os filtros de período, turno e modelo."""
        d1 = datetime.date(2026, 9, 1)
        d2 = datetime.date(2026, 9, 2)

        # OP Turma A, BLA004, 20 un
        op1 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-REL-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d1,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            data_turno=d1,
            operador=self.operador_a,
            itens_dados=[{'ordem_id': op1.id, 'quantidade_realizada': 20, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
        )

        # OP Turma B, BLA001, 30 un
        op2 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-REL-002",
            processo=self.processo,
            produto=self.produto_bla1,
            data_programada=d2,
            turma_prevista='TURMA_B',
            quantidade_nova=30,
            quantidade_planejada=30,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            data_turno=d2,
            operador=self.operador_b,
            itens_dados=[{'ordem_id': op2.id, 'quantidade_realizada': 30, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
        )

        # 1. Filtro Todos: consolida 50 programados e 50 realizados
        res_todos = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026, 'turno': 'TODOS', 'modelo': 'TODOS'})
        self.assertEqual(res_todos.context['total_programado'], 50)
        self.assertEqual(res_todos.context['total_realizado'], 50)
        self.assertEqual(res_todos.context['percentual_geral_display'], "100%")

        # 2. Filtro Turma A: apenas op1 (20 un)
        res_turma_a = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026, 'turno': 'TURMA_A', 'modelo': 'TODOS'})
        self.assertEqual(res_turma_a.context['total_programado'], 20)
        self.assertEqual(res_turma_a.context['total_realizado'], 20)

        # 3. Filtro Turma B: apenas op2 (30 un)
        res_turma_b = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026, 'turno': 'TURMA_B', 'modelo': 'TODOS'})
        self.assertEqual(res_turma_b.context['total_programado'], 30)
        self.assertEqual(res_turma_b.context['total_realizado'], 30)

        # 4. Filtro Modelo BLA004: apenas op1
        res_bla4 = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026, 'turno': 'TODOS', 'modelo': 'BLA004'})
        self.assertEqual(res_bla4.context['total_programado'], 20)
        self.assertEqual(res_bla4.context['total_realizado'], 20)

    def test_producao_por_turno_e_consolidado(self):
        """Exibe Turma A, Turma B e Total Consolidado com programado, realizado, saldo e cumprimento."""
        d1 = datetime.date(2026, 9, 9)   # Turma A
        d2 = datetime.date(2026, 9, 10)  # Turma B

        # Turma A: Programado 40, Realizado 40 -> 100%
        op_a = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-TURMA-A",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d1,
            turma_prevista='TURMA_A',
            quantidade_nova=40,
            quantidade_planejada=40,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            data_turno=d1,
            operador=self.operador_a,
            itens_dados=[{'ordem_id': op_a.id, 'quantidade_realizada': 40, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
        )

        # Turma B: Programado 30, Realizado 27 -> 90%
        op_b = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-TURMA-B",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d2,
            turma_prevista='TURMA_B',
            quantidade_nova=30,
            quantidade_planejada=30,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            data_turno=d2,
            operador=self.operador_b,
            itens_dados=[{'ordem_id': op_b.id, 'quantidade_realizada': 27, 'motivo': 'PROBLEMA_EQUIPAMENTO', 'motivo_outro': '', 'observacao': ''}]
        )

        res = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        self.assertEqual(res.status_code, 200)

        # Turma A
        self.assertEqual(res.context['prog_turma_a'], 40)
        self.assertEqual(res.context['prod_turma_a'], 40)
        self.assertEqual(res.context['saldo_turma_a'], 0)
        self.assertEqual(res.context['pct_turma_a_display'], "100%")

        # Turma B
        self.assertEqual(res.context['prog_turma_b'], 30)
        self.assertEqual(res.context['prod_turma_b'], 27)
        self.assertEqual(res.context['saldo_turma_b'], 3)
        self.assertEqual(res.context['pct_turma_b_display'], "90%")

        # Total Consolidado
        self.assertEqual(res.context['prog_total_turmas'], 70)
        self.assertEqual(res.context['prod_total_turmas'], 67)
        self.assertEqual(res.context['saldo_total_turmas'], 3)

    def test_producao_diaria_e_acumulado(self):
        """Produção diária mostra exatamente os fechamentos reais por dia e o acumulado do período."""
        d1 = datetime.date(2026, 9, 1)
        d2 = datetime.date(2026, 9, 2)
        d3 = datetime.date(2026, 9, 3)

        # 01/09: Turma A produziu 100
        op1 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-DIA-1", processo=self.processo, produto=self.produto_bla4,
            data_programada=d1, turma_prevista='TURMA_A', quantidade_nova=100, quantidade_planejada=100, criado_por=self.lider
        )
        executar_fechamento_turno(d1, self.operador_a, [{'ordem_id': op1.id, 'quantidade_realizada': 100, 'motivo': '', 'motivo_outro': '', 'observacao': ''}])

        # 02/09: Turma B produziu 120
        op2 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-DIA-2", processo=self.processo, produto=self.produto_bla4,
            data_programada=d2, turma_prevista='TURMA_B', quantidade_nova=120, quantidade_planejada=120, criado_por=self.lider
        )
        executar_fechamento_turno(d2, self.operador_b, [{'ordem_id': op2.id, 'quantidade_realizada': 120, 'motivo': '', 'motivo_outro': '', 'observacao': ''}])

        # 03/09: Turma A produziu 90
        op3 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-DIA-3", processo=self.processo, produto=self.produto_bla4,
            data_programada=d3, turma_prevista='TURMA_A', quantidade_nova=90, quantidade_planejada=90, criado_por=self.lider
        )
        executar_fechamento_turno(d3, self.operador_a, [{'ordem_id': op3.id, 'quantidade_realizada': 90, 'motivo': '', 'motivo_outro': '', 'observacao': ''}])

        res = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        diaria = res.context['producao_diaria']
        self.assertEqual(len(diaria), 3)

        self.assertEqual(diaria[0]['data'], d1)
        self.assertEqual(diaria[0]['turma_a'], 100)
        self.assertEqual(diaria[0]['turma_b'], 0)
        self.assertEqual(diaria[0]['total'], 100)

        self.assertEqual(diaria[1]['data'], d2)
        self.assertEqual(diaria[1]['turma_a'], 0)
        self.assertEqual(diaria[1]['turma_b'], 120)
        self.assertEqual(diaria[1]['total'], 120)

        self.assertEqual(diaria[2]['data'], d3)
        self.assertEqual(diaria[2]['turma_a'], 90)
        self.assertEqual(diaria[2]['turma_b'], 0)
        self.assertEqual(diaria[2]['total'], 90)

        self.assertEqual(res.context['acumulado_periodo'], 310)

    def test_pendencias_do_periodo_origem_fechamento(self):
        """Seção de pendências traz apenas OPs fechadas com saldo > 0 e exibe motivo."""
        d = datetime.date(2026, 9, 15)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-PEND-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=25,
            quantidade_planejada=25,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            data_turno=d,
            operador=self.operador_a,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 23,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Vazamento de vapor na prensa'
            }]
        )

        res = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        pendencias = res.context['pendencias_periodo']
        self.assertEqual(len(pendencias), 1)

        p = pendencias[0]
        self.assertEqual(p['numero_ordem'], "OP-PEND-001")
        self.assertEqual(p['modelo'], "BLA004")
        self.assertEqual(p['quantidade_programada'], 25)
        self.assertEqual(p['quantidade_realizada'], 23)
        self.assertEqual(p['saldo'], 2)
        self.assertIn("Problema de equipamento", p['motivo'])

    def test_prevencao_dupla_contagem_saldo_incorporado(self):
        """Incorporar saldo em nova OP não duplica a produção realizada no relatório."""
        d1 = datetime.date(2026, 9, 19)
        d2 = datetime.date(2026, 9, 20)

        # 1. OP-1 fecha parcial: meta 20, realizada 18, saldo 2
        op1 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-DUPLA-1",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d1,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            d1, self.operador_a,
            [{'ordem_id': op1.id, 'quantidade_realizada': 18, 'motivo': 'PROBLEMA_QUALIDADE', 'motivo_outro': '', 'observacao': ''}]
        )

        # Relatório antes de criar OP-2: Realizado = 18
        res1 = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        self.assertEqual(res1.context['total_realizado'], 18)

        # 2. Líder cria OP-2 incorporando o saldo 2: Qtd Nova = 30 + Saldo Inc = 2 -> Meta = 32
        from bladder.services import criar_ordem_producao_com_saldos
        saldo_item = SaldoPendenteBladder.objects.filter(op_origem=op1, status='PENDENTE').first()
        self.assertIsNotNone(saldo_item)

        op2 = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d2,
            quantidade_nova=30,
            prioridade='NORMAL',
            saldos_selecionados_ids=[saldo_item.id],
            usuario=self.lider
        )
        self.assertEqual(op2.quantidade_planejada, 32)
        self.assertEqual(op2.saldo_anterior_incorporado, 2)

        # Antes do fechamento de OP-2: Realizado no relatório AINDA DEVE SER 18 (não duplica nada!)
        res2 = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        self.assertEqual(res2.context['total_realizado'], 18)

        # 3. Operador fecha OP-2 com 32 realizados
        executar_fechamento_turno(
            d2, self.operador_b,
            [{'ordem_id': op2.id, 'quantidade_realizada': 32, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
        )

        # Após fechamento de OP-2: Realizado no relatório = 18 + 32 = 50 (exatamente o produzido)
        res3 = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        self.assertEqual(res3.context['total_realizado'], 50)
        self.assertEqual(res3.context['total_programado'], 52)  # 20 + 32
        self.assertEqual(res3.context['saldo_pendente_total'], 2)  # 52 - 50 = 2

    def test_exportacao_excel_abas_e_filtros(self):
        """Exportação Excel sanitizada retorna HTTP 200 com 5 abas alinhadas."""
        import openpyxl
        import io

        d = datetime.date(2026, 9, 25)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-EXCEL-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            d, self.operador_a,
            [{'ordem_id': op.id, 'quantidade_realizada': 19, 'motivo': 'PROBLEMA_OPERACIONAL', 'motivo_outro': '', 'observacao': ''}]
        )

        res = self.client_lider.get(reverse("bladder:relatorios_exportar_excel"), {'mes': 9, 'ano': 2026, 'turno': 'TURMA_A', 'modelo': 'BLA004'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        sheet_names = wb.sheetnames
        self.assertIn("Ordens 09-2026", sheet_names)
        self.assertIn("Por Modelo", sheet_names)
        self.assertIn("Resumo e Turmas", sheet_names)
        self.assertIn("Produção Diária", sheet_names)
        self.assertIn("Pendências do Período", sheet_names)


class BladderBloco3OrdensTestCase(TestCase):
    """
    Testes de Homologação Final para o Bloco 3:
    - Nomes das colunas: Qtd. Nova, Pendência Incorporada, Meta Total, Realizado, Saldo Gerado
    - Meta Total = Qtd. Nova + Pendência Incorporada
    - Saldo Gerado = Meta Total - Realizado (após fechamento do turno)
    - Origem da pendência: rastreabilidade detalhada no detalhe da OP (OP origem, data, turma, modelo, programado, realizado, saldo)
    - Suporte a múltiplas origens de pendências incorporadas na mesma OP
    - Status visual: PROGRAMADA, CONCLUÍDA, PARCIAL / PENDÊNCIA, NÃO REALIZADA / PENDÊNCIA, CANCELADA
    - Cenários obrigatórios da SPEC (Cenários 1 a 6)
    """

    def setUp(self):
        self.grupo_lider, _ = Group.objects.get_or_create(name='Liderança Bladder')
        self.grupo_op, _ = Group.objects.get_or_create(name='Operadores Bladder')

        self.config_escala = ConfiguracaoEscalaBladder.objects.create(
            data_referencia=datetime.date(2026, 9, 1),
            turma_referencia='TURMA_A',
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        self.lider = User.objects.create_user(username="lider_bloco3", password="password123", first_name="Líder Bladder")
        self.lider.groups.add(self.grupo_lider)

        self.operador_a = User.objects.create_user(username="op_a_bloco3", password="password123", first_name="Operador A")
        self.operador_a.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.operador_a, turma='TURMA_A', ativo=True)

        self.operador_b = User.objects.create_user(username="op_b_bloco3", password="password123", first_name="Operador B")
        self.operador_b.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.operador_b, turma='TURMA_B', ativo=True)

        self.processo = ProcessoBladder.objects.create(
            codigo="01", nome="Prensa 01", tipo="PRENSA", ordem_exibicao=1, ativo=True
        )

        self.produto_bla4 = ProdutoBladder.objects.create(
            codigo="BLA004", descricao="B250/12", peso_tarugo_kg=Decimal("3.100"), ativo=True
        )

        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

    def test_cenario_1_concluida_meta_atingida(self):
        """
        CENÁRIO 1:
        Qtd. Nova = 20, Pendência Incorporada = 0, Meta Total = 20,
        Realizado = 20, Saldo Gerado = 0, Status visual = CONCLUÍDA.
        """
        d = datetime.date(2026, 9, 1)  # Turma A
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-CEN1-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            saldo_anterior_incorporado=0,
            quantidade_planejada=20,
            criado_por=self.lider
        )
        self.assertEqual(op.quantidade_planejada, 20)
        self.assertEqual(op.saldo_anterior_incorporado, 0)

        executar_fechamento_turno(
            d, self.operador_a,
            [{'ordem_id': op.id, 'quantidade_realizada': 20, 'motivo': '', 'motivo_outro': '', 'observacao': ''}]
        )
        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, 20)
        self.assertEqual(op.saldo_gerado, 0)
        self.assertEqual(op.status_visual, "CONCLUÍDA")

        # Verifica na tela de listagem
        res_list = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertContains(res_list, "Qtd. Nova")
        self.assertContains(res_list, "Pendência Incorporada")
        self.assertContains(res_list, "Meta Total")
        self.assertContains(res_list, "Realizado")
        self.assertContains(res_list, "Saldo Gerado")
        self.assertContains(res_list, "CONCLUÍDA")

        # Verifica na tela de detalhe
        res_det = self.client_lider.get(reverse("bladder:ordem_detalhe", kwargs={'pk': op.pk}))
        self.assertContains(res_det, "CONCLUÍDA")
        self.assertContains(res_det, "Qtd. Nova")
        self.assertContains(res_det, "Pendência Incorporada")
        self.assertContains(res_det, "Meta Total")

    def test_cenario_2_parcial_com_saldo_pendente(self):
        """
        CENÁRIO 2:
        Qtd. Nova = 20, Pendência Incorporada = 5, Meta Total = 25,
        Realizado = 23, Saldo Gerado = 2, Status visual = PARCIAL / PENDÊNCIA.
        """
        d = datetime.date(2026, 9, 1)  # Turma A
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-CEN2-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            saldo_anterior_incorporado=5,
            quantidade_planejada=25,
            criado_por=self.lider
        )
        self.assertEqual(op.quantidade_planejada, 25)

        executar_fechamento_turno(
            d, self.operador_a,
            [{'ordem_id': op.id, 'quantidade_realizada': 23, 'motivo': 'PROBLEMA_EQUIPAMENTO', 'motivo_outro': '', 'observacao': 'Vazamento'}]
        )
        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, 23)
        self.assertEqual(op.saldo_gerado, 2)
        self.assertEqual(op.status_visual, "PARCIAL / PENDÊNCIA")

        # Verifica na lista
        res_list = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertContains(res_list, "PARCIAL / PENDÊNCIA")
        self.assertContains(res_list, "2 un")

        # Verifica no detalhe
        res_det = self.client_lider.get(reverse("bladder:ordem_detalhe", kwargs={'pk': op.pk}))
        self.assertContains(res_det, "PARCIAL / PENDÊNCIA")
        self.assertContains(res_det, "2 un")

    def test_cenario_3_nao_realizada_com_pendencia_integral(self):
        """
        CENÁRIO 3:
        Qtd. Nova = 20, Pendência Incorporada = 5, Meta Total = 25,
        Realizado = 0, Saldo Gerado = 25, Situação = NÃO REALIZADA / PENDÊNCIA.
        """
        d = datetime.date(2026, 9, 1)  # Turma A
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-CEN3-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            saldo_anterior_incorporado=5,
            quantidade_planejada=25,
            criado_por=self.lider
        )

        executar_fechamento_turno(
            d, self.operador_a,
            [{'ordem_id': op.id, 'quantidade_realizada': 0, 'motivo': 'FALTA_ENERGIA', 'motivo_outro': '', 'observacao': 'Queda de energia da subestação'}]
        )
        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, 0)
        self.assertEqual(op.saldo_gerado, 25)
        self.assertEqual(op.status_visual, "NÃO REALIZADA / PENDÊNCIA")

        # Verifica na listagem e detalhe
        res_list = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertContains(res_list, "NÃO REALIZADA / PENDÊNCIA")
        self.assertContains(res_list, "25 un")

        res_det = self.client_lider.get(reverse("bladder:ordem_detalhe", kwargs={'pk': op.pk}))
        self.assertContains(res_det, "NÃO REALIZADA / PENDÊNCIA")
        self.assertContains(res_det, "25 un")

    def test_cenario_4_rastreabilidade_incorporacao_op_anterior(self):
        """
        CENÁRIO 4:
        Nova OP incorpora saldo de uma OP anterior.
        Detalhes precisam mostrar: OP origem, data, turma, produto, programado, realizado, saldo incorporado.
        """
        d1 = datetime.date(2026, 9, 1)  # Turma A
        d2 = datetime.date(2026, 9, 2)  # Turma B

        # 1. OP anterior fechada parcial
        op_origem = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-ORIGEM-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d1,
            turma_prevista='TURMA_A',
            quantidade_nova=30,
            quantidade_planejada=30,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            d1, self.operador_a,
            [{'ordem_id': op_origem.id, 'quantidade_realizada': 26, 'motivo': 'PROBLEMA_EQUIPAMENTO', 'motivo_outro': '', 'observacao': ''}]
        )
        saldo_item = SaldoPendenteBladder.objects.get(op_origem=op_origem, status='PENDENTE')
        self.assertEqual(saldo_item.quantidade, 4)

        # 2. Nova OP incorpora o saldo de 4
        from bladder.services import criar_ordem_producao_com_saldos
        op_nova = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d2,
            quantidade_nova=20,
            saldos_selecionados_ids=[saldo_item.id],
            usuario=self.lider
        )
        self.assertEqual(op_nova.quantidade_nova, 20)
        self.assertEqual(op_nova.saldo_anterior_incorporado, 4)
        self.assertEqual(op_nova.quantidade_planejada, 24)

        # 3. Detalhes de op_nova mostram a rastreabilidade completa da origem
        res = self.client_lider.get(reverse("bladder:ordem_detalhe", kwargs={'pk': op_nova.pk}))
        self.assertEqual(res.status_code, 200)

        # Deve conter OP origem, data, turma, modelo, programado (30), realizado (26) e saldo (+4 un)
        self.assertContains(res, op_origem.numero_ordem)
        self.assertContains(res, "01/09/2026")
        self.assertContains(res, "Turma A")
        self.assertContains(res, "BLA004")
        self.assertContains(res, "30")  # Programado original
        self.assertContains(res, "26")  # Realizado original
        self.assertContains(res, "+4 un")

    def test_cenario_5_incorporacao_multiplas_ops_origem(self):
        """
        CENÁRIO 5:
        Nova OP incorpora saldos de duas OPs diferentes.
        As duas origens precisam continuar rastreáveis individualmente.
        Ex: OP-001 (3 un) e OP-005 (2 un) -> Total incorporado = 5.
        """
        d1 = datetime.date(2026, 9, 1)  # Turma A
        d2 = datetime.date(2026, 9, 3)  # Turma A
        d_nova = datetime.date(2026, 9, 5)

        op1 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-ORIG-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d1,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            d1, self.operador_a,
            [{'ordem_id': op1.id, 'quantidade_realizada': 17, 'motivo': 'PROBLEMA_QUALIDADE', 'motivo_outro': '', 'observacao': ''}]
        )
        saldo1 = SaldoPendenteBladder.objects.get(op_origem=op1, status='PENDENTE')
        self.assertEqual(saldo1.quantidade, 3)

        op2 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-ORIG-005",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d2,
            turma_prevista='TURMA_A',
            quantidade_nova=25,
            quantidade_planejada=25,
            criado_por=self.lider
        )
        executar_fechamento_turno(
            d2, self.operador_a,
            [{'ordem_id': op2.id, 'quantidade_realizada': 23, 'motivo': 'PROBLEMA_EQUIPAMENTO', 'motivo_outro': '', 'observacao': ''}]
        )
        saldo2 = SaldoPendenteBladder.objects.get(op_origem=op2, status='PENDENTE')
        self.assertEqual(saldo2.quantidade, 2)

        # Nova OP incorpora ambos os saldos: Qtd Nova = 20, Pendência = 3 + 2 = 5, Meta Total = 25
        from bladder.services import criar_ordem_producao_com_saldos
        op_multi = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d_nova,
            quantidade_nova=20,
            saldos_selecionados_ids=[saldo1.id, saldo2.id],
            usuario=self.lider
        )
        self.assertEqual(op_multi.quantidade_nova, 20)
        self.assertEqual(op_multi.saldo_anterior_incorporado, 5)
        self.assertEqual(op_multi.quantidade_planejada, 25)

        # Detalhe exibe ambas as origens individualmente
        res = self.client_lider.get(reverse("bladder:ordem_detalhe", kwargs={'pk': op_multi.pk}))
        self.assertEqual(res.status_code, 200)

        # Origem 1: OP-ORIG-001 -> 3 un
        self.assertContains(res, op1.numero_ordem)
        self.assertContains(res, "+3 un")

        # Origem 2: OP-ORIG-005 -> 2 un
        self.assertContains(res, op2.numero_ordem)
        self.assertContains(res, "+2 un")

        # Total incorporado no badge
        self.assertContains(res, "Total Incorporado: +5 un")

    def test_cenario_6_op_aberta_no_turno_programada(self):
        """
        CENÁRIO 6:
        OP ainda está dentro do turno e não foi fechada.
        Não mostrar PENDENTE. Mostrar PROGRAMADA.
        """
        d = datetime.date(2026, 9, 1)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-ABERTA-001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            status='PENDENTE',
            criado_por=self.lider
        )

        self.assertEqual(op.status_visual, "PROGRAMADA")

        # Na lista de ordens
        res_list = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertContains(res_list, "PROGRAMADA")

        # No detalhe da OP
        res_det = self.client_lider.get(reverse("bladder:ordem_detalhe", kwargs={'pk': op.pk}))
        self.assertContains(res_det, "PROGRAMADA")

    def test_fluxo_integrado_completo_16_passos(self):
        """
        Teste Integrado Final dos 16 Passos da Seção 7 da Demanda:
        1. Líder cria OP BLA004 (20 un, sem pendência)
        2. Durante turno: operador vê como PROGRAMADA
        3. Operador consulta detalhes técnicos
        4. Sem lançamento obrigatório durante execução
        5. Único botão FECHAR TURNO
        6. Informa realizado = 18
        7. Sistema registra: Meta Total=20, Realizado=18, Saldo=2, PARCIAL / PENDÊNCIA
        8. Tela de Ordens mostra os valores
        9. Relatório: Prog=20, Real=18, Saldo=2, Cumprimento=90%
        10. Pendências do relatório mostram OP, turma, operador, data e motivo
        11. Líder incorpora os 2 un
        12. Nova OP: Nova=30, Inc=2, Meta=32
        13. Detalhes mostram OP de origem dos 2
        14. Antes do fechamento da nova OP: PROGRAMADA
        15. Fechamento da nova OP com 32: CONCLUÍDA, Saldo=0
        16. Relatório acumula fechamentos sem duplicar (Real=50)
        """
        d1 = datetime.date(2026, 9, 1)  # Turma A
        d2 = datetime.date(2026, 9, 2)  # Turma B

        # 1. Líder cria OP: BLA004, Qtd. Nova = 20, sem pendência
        from bladder.services import criar_ordem_producao_com_saldos
        op1 = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d1,
            quantidade_nova=20,
            usuario=self.lider
        )
        self.assertEqual(op1.quantidade_nova, 20)
        self.assertEqual(op1.saldo_anterior_incorporado, 0)
        self.assertEqual(op1.quantidade_planejada, 20)

        # 2. Durante o turno: operador vê BLA004 como PROGRAMADA
        client_op = Client()
        client_op.force_login(self.operador_a)
        res_chao = client_op.get(reverse("bladder:operador") + f"?data={d1.strftime('%Y-%m-%d')}")
        self.assertEqual(res_chao.status_code, 200)
        self.assertContains(res_chao, "PROGRAMADA")
        self.assertNotContains(res_chao, ">Pendente<")

        # 3. Operador consulta detalhes técnicos
        self.assertContains(res_chao, "Ver Detalhes Técnicos")
        self.assertContains(res_chao, "Tarugo:")
        self.assertContains(res_chao, "kg")

        # 4. Não existe lançamento obrigatório durante execução

        # 5. No final do turno: operador usa o único botão FECHAR TURNO
        self.assertContains(res_chao, "FECHAR TURNO")
        # Confirma que há apenas um botão FECHAR TURNO no HTML da tela do operador
        self.assertEqual(res_chao.content.decode('utf-8').count("FECHAR TURNO"), 1)

        # 6 e 7. Informa realizado = 18 com motivo de pendência
        executar_fechamento_turno(
            data_turno=d1,
            operador=self.operador_a,
            itens_dados=[{
                'ordem_id': op1.id,
                'quantidade_realizada': 18,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Falha na prensa 01'
            }]
        )
        op1.refresh_from_db()
        self.assertEqual(op1.quantidade_planejada, 20)
        self.assertEqual(op1.quantidade_realizada, 18)
        self.assertEqual(op1.saldo_gerado, 2)
        self.assertEqual(op1.status_visual, "PARCIAL / PENDÊNCIA")

        # 8. Tela de Ordens mostra corretamente os valores
        res_ordens = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertContains(res_ordens, "Qtd. Nova")
        self.assertContains(res_ordens, "Pendência Incorporada")
        self.assertContains(res_ordens, "Meta Total")
        self.assertContains(res_ordens, "PARCIAL / PENDÊNCIA")
        self.assertContains(res_ordens, "2 un")

        # 9. Relatório do mês mostra: Programado = 20, Realizado = 18, Saldo = 2, Cumprimento = 90%
        res_rel = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        self.assertEqual(res_rel.context['total_programado'], 20)
        self.assertEqual(res_rel.context['total_realizado'], 18)
        self.assertEqual(res_rel.context['saldo_pendente_total'], 2)
        self.assertEqual(res_rel.context['percentual_geral_display'], "90%")

        # 10. Pendências do relatório mostram OP, turma, operador do fechamento, data e motivo
        pendencias = res_rel.context['pendencias_periodo']
        self.assertEqual(len(pendencias), 1)
        self.assertEqual(pendencias[0]['numero_ordem'], op1.numero_ordem)
        self.assertEqual(pendencias[0]['turma'], "Turma A")
        self.assertEqual(pendencias[0]['operador_fechamento'], "Operador A")
        self.assertEqual(pendencias[0]['data_fechamento'], d1)
        self.assertIn("Problema de equipamento", pendencias[0]['motivo'])

        # 11. Posteriormente, líder incorpora os 2 em uma nova programação
        saldo_ledger = SaldoPendenteBladder.objects.get(op_origem=op1, status='PENDENTE')
        self.assertEqual(saldo_ledger.quantidade, 2)

        # 12. Nova OP: Qtd. Nova = 30, Pendência Incorporada = 2, Meta Total = 32
        op2 = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d2,
            quantidade_nova=30,
            saldos_selecionados_ids=[saldo_ledger.id],
            usuario=self.lider
        )
        self.assertEqual(op2.quantidade_nova, 30)
        self.assertEqual(op2.saldo_anterior_incorporado, 2)
        self.assertEqual(op2.quantidade_planejada, 32)

        # 13. Detalhes mostram a OP que originou os 2
        res_det2 = self.client_lider.get(reverse("bladder:ordem_detalhe", kwargs={'pk': op2.pk}))
        self.assertContains(res_det2, op1.numero_ordem)
        self.assertContains(res_det2, "+2 un")
        self.assertContains(res_det2, "Total Incorporado: +2 un")

        # 14. Antes do fechamento dessa nova OP: status = PROGRAMADA
        self.assertEqual(op2.status_visual, "PROGRAMADA")
        self.assertContains(res_det2, "PROGRAMADA")

        # 15. Após fechamento completo com 32: status = CONCLUÍDA; Saldo Gerado = 0
        executar_fechamento_turno(
            data_turno=d2,
            operador=self.operador_b,
            itens_dados=[{
                'ordem_id': op2.id,
                'quantidade_realizada': 32,
                'motivo': '',
                'motivo_outro': '',
                'observacao': 'Produção de 32 bladders concluída'
            }]
        )
        op2.refresh_from_db()
        self.assertEqual(op2.status_visual, "CONCLUÍDA")
        self.assertEqual(op2.saldo_gerado, 0)

        # 16. Relatório acumula a produção dos fechamentos sem duplicar os 2 provenientes da pendência
        res_rel_final = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 9, 'ano': 2026})
        self.assertEqual(res_rel_final.context['total_realizado'], 50)  # 18 + 32 = 50
        self.assertEqual(res_rel_final.context['total_programado'], 52)  # 20 + 32 = 52
        self.assertEqual(res_rel_final.context['saldo_pendente_total'], 2)  # 52 - 50 = 2


class HomologacaoChaoDeFabricaFichaTecnicaTestCase(TestCase):
    """
    Testes de Homologação da Nova Experiência de Chão de Fábrica e Ficha Técnica:
    1. Operador acessa Chão de Fábrica;
    2. Operador não acessa funções gerenciais;
    3. OP aberta é apresentada como PROGRAMADA;
    4. OP ainda aberta não é apresentada como PENDÊNCIA;
    5. Identificação completa da OP continua armazenada no banco;
    6. Representação curta (numero_ordem_curto) não altera numero_ordem;
    7. Ficha Técnica pertence à OP/produto correto;
    8. Ficha Técnica não permite lançamento de produção;
    9. Ficha Técnica não permite fechamento individual;
    10. Fechamento único continua funcionando;
    11. Pendência só nasce a partir do fechamento;
    12. Nenhum fluxo administrativo foi alterado;
    13. Cenário Funcional Controlado (BLA004, BLA006 com motivo, BLA007, total 62/65 = 95.38%);
    14. Incorporação da pendência de 3 do BLA006 em nova OP.
    """

    def setUp(self):
        self.grupo_lider, _ = Group.objects.get_or_create(name='Liderança Bladder')
        self.grupo_op, _ = Group.objects.get_or_create(name='Operadores Bladder')

        self.config_escala = ConfiguracaoEscalaBladder.objects.create(
            data_referencia=datetime.date(2026, 10, 1),
            turma_referencia='TURMA_A',
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        self.lider = User.objects.create_user(username="lider_homolog_cf", password="password123", first_name="Líder Bladder")
        self.lider.groups.add(self.grupo_lider)

        self.operador_a = User.objects.create_user(username="op_a_homolog_cf", password="password123", first_name="Operador A")
        self.operador_a.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.operador_a, turma='TURMA_A', ativo=True)

        self.operador_b = User.objects.create_user(username="op_b_homolog_cf", password="password123", first_name="Operador B")
        self.operador_b.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.operador_b, turma='TURMA_B', ativo=True)

        self.setor = Sector.objects.create(nome="BLADDER")
        self.maquina = Machine.objects.create(nome="EXTRUSORA DE BLADDER 02", setor=self.setor, criticidade="ALTA")

        self.processo = ProcessoBladder.objects.create(
            codigo="03", nome="Extrusão de Bladder", tipo="EXTRUSAO", maquina=self.maquina, ordem_exibicao=1, ativo=True
        )

        self.produto_bla4 = ProdutoBladder.objects.create(
            codigo="BLA004", descricao="B250/12", matriz_extrusao="MAT04",
            peso_tarugo_kg=Decimal("3.100"), diametro_tarugo_mm=Decimal("75.00"),
            comprimento_extrusao_cm=Decimal("110.00"), comprimento_chanfrado_cm=Decimal("105.00"),
            tempo_vulcanizacao_min=120, peso_vulcanizado_kg=Decimal("2.765"),
            circunferencia_centro_mm="650", altura_cm="35",
            ativo=True
        )
        self.produto_bla6 = ProdutoBladder.objects.create(
            codigo="BLA006", descricao="B120/14", matriz_extrusao="MAT06",
            peso_tarugo_kg=Decimal("1.500"), diametro_tarugo_mm=Decimal("60.00"),
            comprimento_extrusao_cm=Decimal("95.00"), comprimento_chanfrado_cm=Decimal("90.00"),
            tempo_vulcanizacao_min=120, peso_vulcanizado_kg=Decimal("1.350"),
            circunferencia_centro_mm="580", altura_cm="30",
            ativo=True
        )
        self.produto_bla7 = ProdutoBladder.objects.create(
            codigo="BLA007", descricao="B100/12", matriz_extrusao="MAT04",
            peso_tarugo_kg=Decimal("1.200"), diametro_tarugo_mm=Decimal("55.00"),
            comprimento_extrusao_cm=Decimal("80.00"), comprimento_chanfrado_cm=Decimal("75.00"),
            tempo_vulcanizacao_min=120, peso_vulcanizado_kg=Decimal("1.080"),
            circunferencia_centro_mm="520", altura_cm="28",
            ativo=True
        )

        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

        self.client_op = Client()
        self.client_op.force_login(self.operador_a)

    def test_01_operador_acessa_chao_de_fabrica(self):
        """Operador acessa Chão de Fábrica com sucesso (200 OK) e vê os elementos essenciais."""
        res = self.client_op.get(reverse("bladder:operador"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "CHÃO DE FÁBRICA")
        self.assertContains(res, "FECHAR TURNO")

    def test_02_operador_nao_acessa_funcoes_gerenciais(self):
        """Operador Bladder é redirecionado em rotas gerenciais (ou 403 em AJAX) e não vê links no menu."""
        rotas_gerenciais = [
            "dashboard",
            "cronograma",
            "ordens_lista",
            "ordem_nova",
            "relatorios",
        ]
        for rota in rotas_gerenciais:
            # Requisição padrão de navegador: redirecionamento seguro para Chão de Fábrica
            res = self.client_op.get(reverse(f"bladder:{rota}"))
            self.assertRedirects(res, reverse("bladder:operador"))
            # Requisição AJAX: retorno 403 Forbidden
            res_ajax = self.client_op.get(reverse(f"bladder:{rota}"), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(res_ajax.status_code, 403, f"Operador não deveria acessar rota gerencial via AJAX: {rota}")

        # No menu do template base, links administrativos não são renderizados para o operador
        res_op = self.client_op.get(reverse("bladder:operador"))
        content = res_op.content.decode('utf-8')
        self.assertNotIn('href="/bladder/cronograma/"', content)
        self.assertNotIn('href="/bladder/ordens/"', content)
        self.assertNotIn('href="/bladder/ordens/nova/"', content)
        self.assertNotIn('href="/bladder/relatorios/"', content)

    def test_03_op_aberta_apresentada_como_programada_nao_pendencia(self):
        """OP do turno ainda aberta deve aparecer como PROGRAMADA e NÃO como PENDÊNCIA."""
        d = datetime.date(2026, 10, 1)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0001",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            status='PENDENTE',
            criado_por=self.lider
        )
        self.assertEqual(op.status_visual, "PROGRAMADA")

        res = self.client_op.get(reverse("bladder:operador") + f"?data={d.strftime('%Y-%m-%d')}")
        self.assertContains(res, "PROGRAMADA")
        self.assertNotContains(res, ">Pendente<")
        self.assertNotContains(res, "PARCIAL / PENDÊNCIA")

    def test_04_identificacao_completa_armazenada_e_representacao_curta(self):
        """
        Identificador oficial completo (OP-BLA-20261001-0002) permanece intacto no banco.
        Representação curta (OP #002) é derivada e exibida no card do operador.
        Ficha técnica exibe o identificador oficial integral.
        """
        d = datetime.date(2026, 10, 1)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0002",
            processo=self.processo,
            produto=self.produto_bla6,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=15,
            quantidade_planejada=15,
            status='PENDENTE',
            criado_por=self.lider
        )

        # 1. Validação no banco e na property
        self.assertEqual(op.numero_ordem, "OP-BLA-20261001-0002")
        self.assertEqual(op.numero_ordem_curto, "OP #002")

        # 2. Na tela do operador
        res = self.client_op.get(reverse("bladder:operador") + f"?data={d.strftime('%Y-%m-%d')}")
        # Card mostra identificação curta
        self.assertContains(res, "OP #002")
        # Modal Ficha Técnica mostra identificação completa
        self.assertContains(res, "OP-BLA-20261001-0002")

        # 3. Confirma que banco continua inalterado
        op.refresh_from_db()
        self.assertEqual(op.numero_ordem, "OP-BLA-20261001-0002")

    def test_05_card_operacional_simplificado_e_especificacoes_na_ficha_tecnica(self):
        """
        Card principal mostra apenas identificação curta, processo/equipamento, prioridade, status,
        código do bladder, modelo/descrição, meta e botão Ficha Técnica.
        Especificações técnicas detalhadas foram retiradas do card e estão na Ficha Técnica.
        """
        d = datetime.date(2026, 10, 1)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0003",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            status='PENDENTE',
            criado_por=self.lider
        )

        res = self.client_op.get(reverse("bladder:operador") + f"?data={d.strftime('%Y-%m-%d')}")
        # Elementos do Card Simplificado
        self.assertContains(res, "OP #003")
        self.assertContains(res, "BLA004")
        self.assertContains(res, "B250/12")
        self.assertContains(res, "Extrusão de Bladder")
        self.assertContains(res, "Meta do Turno")
        self.assertContains(res, "FICHA TÉCNICA")

        # Grupos da Ficha Técnica
        self.assertContains(res, "1. Identificação Geral")
        self.assertContains(res, "2. Tarugo")
        self.assertContains(res, "3. Parâmetros de Extrusão")
        self.assertContains(res, "4. Parâmetros de Vulcanização")
        self.assertContains(res, "5. Instruções Especiais e Ferramental")

    def test_06_ficha_tecnica_pertence_ao_produto_e_op_correta(self):
        """Ficha Técnica exibe os dados reais do produto e da OP correspondente."""
        d = datetime.date(2026, 10, 1)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0004",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            status='PENDENTE',
            criado_por=self.lider
        )

        res = self.client_op.get(reverse("bladder:operador") + f"?data={d.strftime('%Y-%m-%d')}")
        self.assertContains(res, f"modalDetalhes{op.pk}")
        self.assertContains(res, "3,100 kg")
        self.assertContains(res, "75,00 mm")
        self.assertContains(res, "MAT04")
        self.assertContains(res, "110,00 cm")
        self.assertContains(res, "120 min")

    def test_07_ficha_tecnica_somente_consulta(self):
        """Ficha Técnica é exclusivamente para consulta: não permite lançar produção nem fechar atividade."""
        d = datetime.date(2026, 10, 1)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0005",
            processo=self.processo,
            produto=self.produto_bla6,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=10,
            quantidade_planejada=10,
            status='PENDENTE',
            criado_por=self.lider
        )

        res = self.client_op.get(reverse("bladder:operador") + f"?data={d.strftime('%Y-%m-%d')}")
        content = res.content.decode('utf-8')

        # Na página como um todo, não há formulário de fechamento individual de atividade
        self.assertNotIn('<form action="/bladder/operador/apontar/', content)
        self.assertNotIn('name="quantidade_realizada"', content)
        # Contém o aviso de consulta exclusiva
        self.assertIn("Visualização técnica exclusivamente para consulta", content)

    def test_08_fechamento_unico_do_turno_no_topo(self):
        """Tela apresenta somente um botão FECHAR TURNO no topo."""
        d = datetime.date(2026, 10, 1)
        OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0006",
            processo=self.processo,
            produto=self.produto_bla7,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=15,
            quantidade_planejada=15,
            status='PENDENTE',
            criado_por=self.lider
        )

        res = self.client_op.get(reverse("bladder:operador") + f"?data={d.strftime('%Y-%m-%d')}")
        content = res.content.decode('utf-8')
        # Apenas uma ocorrência do botão FECHAR TURNO
        self.assertEqual(content.count("FECHAR TURNO"), 1)

    def test_09_saldo_programacao_vs_pendencia_formal(self):
        """
        Diferença estrita:
        Durante o turno aberto: saldo operacional existe na OP, mas pendência formal NÃO existe no Ledger.
        Após o fechamento com realizado inferior: saldo gerado é registrado e a pendência formal nasce.
        """
        d = datetime.date(2026, 10, 1)
        op = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0007",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            status='PENDENTE',
            criado_por=self.lider
        )

        # 1. Antes do fechamento: saldo remanescente é 20, mas ledger está vazio
        self.assertEqual(op.saldo_remanescente, 20)
        self.assertEqual(SaldoPendenteBladder.objects.filter(op_origem=op).count(), 0)

        # 2. Executa fechamento com 12 realizadas e motivo
        executar_fechamento_turno(
            data_turno=d,
            operador=self.operador_a,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 12,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Falha no motor'
            }]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, 'PARCIAL')
        self.assertEqual(op.status_visual, 'PARCIAL / PENDÊNCIA')
        self.assertEqual(op.saldo_gerado, 8)

        # 3. Agora a pendência formal nasce no Ledger com vínculo à OP de origem
        saldo_ledger = SaldoPendenteBladder.objects.filter(op_origem=op).first()
        self.assertIsNotNone(saldo_ledger)
        self.assertEqual(saldo_ledger.quantidade, 8)
        self.assertEqual(saldo_ledger.status, 'PENDENTE')

        # O motivo da ocorrência fica registrado no ItemFechamentoTurnoBladder e acessível na OP
        item_fechamento = op.itens_fechamento.first()
        self.assertEqual(item_fechamento.motivo, 'PROBLEMA_EQUIPAMENTO')
        self.assertEqual(op.motivo_pendencia, 'Problema de equipamento')

    def test_10_cenario_controlado_homologacao_bla004_bla006_bla007(self):
        """
        Cenário Funcional Controlado Obrigatório da Homologação (Seção 20):
        Turma A
        BLA004: Meta = 20, Fechamento = 20 -> CONCLUÍDA
        BLA006: Meta = 30, Fechamento = 27, Motivo = Problema no equipamento -> PARCIAL / PENDÊNCIA, Saldo = 3
        BLA007: Meta = 15, Fechamento = 15 -> CONCLUÍDA

        Produção realizada total: 20 + 27 + 15 = 62 unidades.
        Programado total: 20 + 30 + 15 = 65 unidades.
        Saldo formal total: 3 unidades.
        Cumprimento: 62 / 65 * 100 ≈ 95,38%.
        """
        d = datetime.date(2026, 10, 1)  # Turma A

        op1 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0008",
            processo=self.processo,
            produto=self.produto_bla4,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=20,
            quantidade_planejada=20,
            status='PENDENTE',
            criado_por=self.lider
        )
        op2 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0009",
            processo=self.processo,
            produto=self.produto_bla6,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=30,
            quantidade_planejada=30,
            status='PENDENTE',
            criado_por=self.lider
        )
        op3 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0010",
            processo=self.processo,
            produto=self.produto_bla7,
            data_programada=d,
            turma_prevista='TURMA_A',
            quantidade_nova=15,
            quantidade_planejada=15,
            status='PENDENTE',
            criado_por=self.lider
        )

        # Fechamento único do turno com os valores definidos
        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador_a,
            itens_dados=[
                {
                    'ordem_id': op1.id,
                    'quantidade_realizada': 20,
                    'motivo': '',
                    'motivo_outro': '',
                    'observacao': 'Meta 100% atingida'
                },
                {
                    'ordem_id': op2.id,
                    'quantidade_realizada': 27,
                    'motivo': 'PROBLEMA_EQUIPAMENTO',
                    'motivo_outro': '',
                    'observacao': 'Problema no equipamento'
                },
                {
                    'ordem_id': op3.id,
                    'quantidade_realizada': 15,
                    'motivo': '',
                    'motivo_outro': '',
                    'observacao': 'Meta 100% atingida'
                },
            ]
        )

        op1.refresh_from_db()
        op2.refresh_from_db()
        op3.refresh_from_db()

        # Validações dos status individuais
        self.assertEqual(op1.status, 'CONCLUIDA')
        self.assertEqual(op1.status_visual, 'CONCLUÍDA')
        self.assertEqual(op1.saldo_gerado, 0)

        self.assertEqual(op2.status, 'PARCIAL')
        self.assertEqual(op2.status_visual, 'PARCIAL / PENDÊNCIA')
        self.assertEqual(op2.saldo_gerado, 3)

        self.assertEqual(op3.status, 'CONCLUIDA')
        self.assertEqual(op3.status_visual, 'CONCLUÍDA')
        self.assertEqual(op3.saldo_gerado, 0)

        # Validações dos totais do turno
        total_realizado = op1.quantidade_realizada + op2.quantidade_realizada + op3.quantidade_realizada
        total_programado = op1.quantidade_planejada + op2.quantidade_planejada + op3.quantidade_planejada
        saldo_formal = op2.saldo_gerado

        self.assertEqual(total_realizado, 62)
        self.assertEqual(total_programado, 65)
        self.assertEqual(saldo_formal, 3)

        cumprimento = round((total_realizado / total_programado) * 100, 2)
        self.assertEqual(cumprimento, 95.38)

        # Validação do Ledger de Pendências
        saldos_pendentes = SaldoPendenteBladder.objects.filter(status='PENDENTE')
        self.assertEqual(saldos_pendentes.count(), 1)
        saldo_bla6 = saldos_pendentes.first()
        self.assertEqual(saldo_bla6.quantidade, 3)
        self.assertEqual(saldo_bla6.produto, self.produto_bla6)
        self.assertEqual(saldo_bla6.op_origem, op2)

        # Motivo acessível na OP de origem
        self.assertEqual(op2.motivo_pendencia, 'Problema de equipamento')

        # Nenhuma nova OP foi criada automaticamente
        self.assertEqual(OrdemProducaoBladder.objects.count(), 3)

        # Validação no Relatório
        res_rel = self.client_lider.get(reverse("bladder:relatorios"), {'mes': 10, 'ano': 2026})
        self.assertEqual(res_rel.status_code, 200)
        self.assertEqual(res_rel.context['total_realizado'], 62)
        self.assertEqual(res_rel.context['total_programado'], 65)
        self.assertEqual(res_rel.context['saldo_pendente_total'], 3)
        self.assertNotEqual(res_rel.context['total_realizado'], 65)

    def test_11_incorporacao_da_pendencia_bla006(self):
        """
        Teste de Incorporação da Pendência (Seção 21):
        Após gerar a pendência de 3 do BLA006, cria uma nova programação com Qtd. Nova independente,
        incorpora os 3 via fluxo existente, vincula no ledger e mantém OP original intacta.
        """
        d1 = datetime.date(2026, 10, 1)  # Turma A
        d2 = datetime.date(2026, 10, 2)  # Turma B

        # 1. OP Original gerando pendência de 3
        op_origem = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261001-0011",
            processo=self.processo,
            produto=self.produto_bla6,
            data_programada=d1,
            turma_prevista='TURMA_A',
            quantidade_nova=30,
            quantidade_planejada=30,
            status='PENDENTE',
            criado_por=self.lider
        )

        executar_fechamento_turno(
            data_turno=d1,
            operador=self.operador_a,
            itens_dados=[{
                'ordem_id': op_origem.id,
                'quantidade_realizada': 27,
                'motivo': 'PROBLEMA_EQUIPAMENTO',
                'motivo_outro': '',
                'observacao': 'Problema no equipamento'
            }]
        )
        op_origem.refresh_from_db()
        self.assertEqual(op_origem.saldo_gerado, 3)

        saldo_ledger = SaldoPendenteBladder.objects.get(op_origem=op_origem, status='PENDENTE')
        self.assertEqual(saldo_ledger.quantidade, 3)

        # 2. Nova OP no dia seguinte: Qtd. Nova = 25, incorporando os 3 de pendência
        op_destino = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.produto_bla6,
            data_programada=d2,
            quantidade_nova=25,
            saldos_selecionados_ids=[saldo_ledger.id],
            usuario=self.lider
        )

        # 3. Validações da nova OP
        self.assertEqual(op_destino.quantidade_nova, 25)
        self.assertEqual(op_destino.saldo_anterior_incorporado, 3)
        self.assertEqual(op_destino.quantidade_planejada, 28)

        # 4. Validações do Ledger
        saldo_ledger.refresh_from_db()
        self.assertEqual(saldo_ledger.status, 'INCORPORADO')
        self.assertEqual(saldo_ledger.op_destino, op_destino)
        self.assertEqual(saldo_ledger.op_origem, op_origem)

        # 5. OP de origem permanece intacta
        op_origem.refresh_from_db()
        self.assertEqual(op_origem.numero_ordem, "OP-BLA-20261001-0011")
        self.assertEqual(op_origem.quantidade_planejada, 30)
        self.assertEqual(op_origem.quantidade_realizada, 27)
        self.assertEqual(op_origem.status, 'PARCIAL')

        # 6. Identificação completa de ambas as OPs continua preservada
        self.assertTrue(op_origem.numero_ordem.startswith("OP-BLA-20261001-"))
        self.assertTrue(op_destino.numero_ordem.startswith("OP-BLA-20261002-"))

    def test_12_fluxos_administrativos_intactos(self):
        """Todos os fluxos e telas de liderança (Ordens, Calendário, Relatórios) permanecem intactos."""
        res_ordens = self.client_lider.get(reverse("bladder:ordens_lista"))
        self.assertEqual(res_ordens.status_code, 200)

        res_cal = self.client_lider.get(reverse("bladder:cronograma"))
        self.assertEqual(res_cal.status_code, 200)

        res_rel = self.client_lider.get(reverse("bladder:relatorios"))
        self.assertEqual(res_rel.status_code, 200)


class BladderHomologacaoNovasRegrasNegocioTestCase(BladderBaseTestCase):
    """
    Suíte de testes para a nova rodada de homologação funcional do Setor de Bladder:
    - Seção 27: 35 testes obrigatórios
    - Seção 28: Teste integrado completo do dia da Turma A (BLA004, BLA006, BLA007, BLA009)
    """

    def setUp(self):
        super().setUp()
        self.cat_equip, _ = CategoriaDesvioBladder.objects.get_or_create(
            codigo="PROBLEMA_EQUIPAMENTO",
            defaults={"nome": "Problema no equipamento", "ordem": 1, "ativo": True}
        )
        self.cat_mp, _ = CategoriaDesvioBladder.objects.get_or_create(
            codigo="FALTA_MATERIA_PRIMA",
            defaults={"nome": "Falta de matéria-prima", "ordem": 2, "ativo": True}
        )
        self.cat_qual, _ = CategoriaDesvioBladder.objects.get_or_create(
            codigo="PROBLEMA_QUALIDADE",
            defaults={"nome": "Problema de qualidade", "ordem": 3, "ativo": True}
        )
        self.cat_manut, _ = CategoriaDesvioBladder.objects.get_or_create(
            codigo="MANUTENCAO",
            defaults={"nome": "Manutenção", "ordem": 4, "ativo": True}
        )
        self.cat_op, _ = CategoriaDesvioBladder.objects.get_or_create(
            codigo="FALTA_OPERADOR",
            defaults={"nome": "Falta de operador", "ordem": 5, "ativo": True}
        )
        self.cat_outro, _ = CategoriaDesvioBladder.objects.get_or_create(
            codigo="OUTRO",
            defaults={"nome": "Outro", "ordem": 6, "ativo": True}
        )
        self.cat_operacional, _ = CategoriaDesvioBladder.objects.get_or_create(
            codigo="PROBLEMA_OPERACIONAL",
            defaults={"nome": "Problema operacional", "ordem": 7, "ativo": True}
        )

        # Máquinas e Processos adicionais
        self.proc_prensa1 = self.processo
        self.maq_prensa2 = Machine.objects.create(nome="PRENSA DE BLADER 02", setor=self.setor, criticidade="MEDIA")
        self.proc_prensa2 = ProcessoBladder.objects.create(
            codigo="02", nome="Prensa de Vulcanização 02", tipo="PRENSA", maquina=self.maq_prensa2, ordem_exibicao=2, ativo=True
        )

        self.maq_extrusora = Machine.objects.create(nome="EXTRUSORA BLADDER", setor=self.setor, criticidade="ALTA")
        self.proc_extrusora = ProcessoBladder.objects.create(
            codigo="03", nome="Extrusão de Tarugos", tipo="EXTRUSAO", maquina=self.maq_extrusora, ordem_exibicao=3, ativo=True
        )

        # Produtos Canônicos da especificação
        self.prod_bla4, _ = ProdutoBladder.objects.get_or_create(
            codigo="BLA004",
            defaults={"descricao": "B250/12 - Tarugo Padrão", "peso_tarugo_kg": Decimal("3.200"), "ativo": True}
        )
        self.prod_bla6, _ = ProdutoBladder.objects.get_or_create(
            codigo="BLA006",
            defaults={"descricao": "B200/16 - Reforçado", "peso_tarugo_kg": Decimal("2.800"), "ativo": True}
        )
        self.prod_bla7, _ = ProdutoBladder.objects.get_or_create(
            codigo="BLA007",
            defaults={"descricao": "B140/15 - Especial", "peso_tarugo_kg": Decimal("2.100"), "ativo": True}
        )
        self.prod_bla9, _ = ProdutoBladder.objects.get_or_create(
            codigo="BLA009",
            defaults={"descricao": "240/15 - Convencional", "peso_tarugo_kg": Decimal("3.000"), "ativo": True}
        )

        # Configura a escala de teste para que 01/10/2026 seja determinísticamente Turma A
        self.config_escala.data_referencia = datetime.date(2026, 10, 1)
        self.config_escala.turma_referencia = "TURMA_A"
        self.config_escala.save()

        # Clients autenticados
        self.client_lider = Client()
        self.client_lider.force_login(self.lider)

        self.client_op1 = Client()
        self.client_op1.force_login(self.operador1)

        self.client_op2 = Client()
        self.client_op2.force_login(self.operador2)

    # ------------------------------------------------------------------
    # 1 a 9: PLANEJAMENTO / CRONOGRAMA
    # ------------------------------------------------------------------
    def test_01_a_04_planejamento_escala_e_turma_derivada(self):
        """1-4: Líder cria OP sem escolher turma, backend deriva Turma A/B pela escala e respeita ajuste excepcional."""
        # 1 & 2: Líder cria OP para 01/10/2026 -> backend deriva TURMA_A pela data
        d1 = datetime.date(2026, 10, 1)
        turma_d1, _, _ = calcular_turma_do_dia(d1)
        self.assertEqual(turma_d1, "TURMA_A")

        op1 = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.prod_bla4,
            data_programada=d1,
            quantidade_nova=20,
            usuario=self.lider
        )
        self.assertEqual(op1.turma_prevista, "TURMA_A")
        self.assertEqual(op1.quantidade_planejada, 20)

        # 3: Dia alternado 02/10/2026 deriva TURMA_B
        d2 = datetime.date(2026, 10, 2)
        turma_d2, _, _ = calcular_turma_do_dia(d2)
        self.assertEqual(turma_d2, "TURMA_B")

        op2 = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.prod_bla4,
            data_programada=d2,
            quantidade_nova=20,
            usuario=self.lider
        )
        self.assertEqual(op2.turma_prevista, "TURMA_B")

        # 4: Ajuste excepcional de escala é respeitado
        AjusteEscalaExcepcionalBladder.objects.create(
            data=d2,
            turma_designada="TURMA_A",
            motivo="Troca de turno excepcional autorizada",
            criado_por=self.lider
        )
        turma_d2_ajustada, is_ajuste, _ = calcular_turma_do_dia(d2)
        self.assertTrue(is_ajuste)
        self.assertEqual(turma_d2_ajustada, "TURMA_A")

    def test_05_reprogramar_data_atualiza_turma_derivada(self):
        """5: Reprogramar a data da OP atualiza automaticamente a turma derivada pela escala da nova data."""
        d1 = datetime.date(2026, 10, 1)  # TURMA_A
        d2 = datetime.date(2026, 10, 2)  # TURMA_B

        op = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.prod_bla4,
            data_programada=d1,
            quantidade_nova=20,
            usuario=self.lider
        )
        self.assertEqual(op.turma_prevista, "TURMA_A")

        reprogramar_ordem_producao(
            op_id=op.id,
            nova_data=d2,
            motivo="Ajuste operacional de data",
            usuario=self.lider
        )
        op.refresh_from_db()
        self.assertEqual(op.data_programada, d2)
        self.assertEqual(op.turma_prevista, "TURMA_B")
        self.assertTrue(HistoricoProgramacaoBladder.objects.filter(ordem=op, tipo_evento="REPROGRAMACAO").exists())

    def test_06_seletor_bladder_codigo_com_medida(self):
        """6: Bladder aparece no formulário como 'Código — Medida' sem matrizes ou detalhes técnicos extensos."""
        form = OrdemProducaoBladderForm()
        label_bla4 = form.fields['produto'].label_from_instance(self.prod_bla4)
        label_bla6 = form.fields['produto'].label_from_instance(self.prod_bla6)

        self.assertEqual(label_bla4, "BLA004 — B250/12")
        self.assertEqual(label_bla6, "BLA006 — B200/16")
        self.assertNotIn("matriz", label_bla4.lower())
        self.assertNotIn("kg", label_bla4.lower())

    def test_07_a_09_planejamento_meta_maquina_extrusora_multiplos_modelos(self):
        """7-9: Quantidade permanece a informada, máquina é decisão do líder e extrusora aceita múltiplos modelos no mesmo dia."""
        d = datetime.date(2026, 10, 1)
        # 7: Quantidade informada é meta humana, não alterada pelo sistema
        op_ext1 = criar_ordem_producao_com_saldos(
            processo=self.proc_extrusora,
            produto=self.prod_bla7,
            data_programada=d,
            quantidade_nova=15,
            usuario=self.lider
        )
        # 8: Decisão manual do processo/máquina
        self.assertEqual(op_ext1.processo, self.proc_extrusora)
        self.assertEqual(op_ext1.quantidade_planejada, 15)

        # 9: Extrusora aceita múltiplos modelos no mesmo dia sem bloqueio
        op_ext2 = criar_ordem_producao_com_saldos(
            processo=self.proc_extrusora,
            produto=self.prod_bla9,
            data_programada=d,
            quantidade_nova=10,
            usuario=self.lider
        )
        self.assertEqual(op_ext2.processo, self.proc_extrusora)
        self.assertEqual(op_ext2.produto, self.prod_bla9)
        self.assertEqual(op_ext2.quantidade_planejada, 10)
        self.assertEqual(OrdemProducaoBladder.objects.filter(processo=self.proc_extrusora, data_programada=d).count(), 2)

    # ------------------------------------------------------------------
    # 10 a 18: FECHAMENTO DE TURNO
    # ------------------------------------------------------------------
    def test_10_fechamento_meta_20_realizado_20_concluida(self):
        """10: Meta 20 / Realizado 20 -> Concluída, saldo 0, excedente 0, sem justificativa."""
        d = datetime.date(2026, 10, 1)
        op = criar_ordem_producao_com_saldos(self.processo, self.prod_bla4, d, 20, usuario=self.lider)
        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador1,
            itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 20, 'categorias': [], 'descricao_desvio': ''}]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, "CONCLUIDA")
        self.assertEqual(op.quantidade_realizada, 20)
        self.assertEqual(op.excedente, 0)
        self.assertEqual(op.saldo_gerado, 0)
        self.assertEqual(SaldoPendenteBladder.objects.filter(fechamento=fechamento).count(), 0)

    def test_11_12_fechamento_meta_20_realizado_22_concluida_com_excedente(self):
        """11-12: Meta 20 / Realizado 22 -> Concluída, excedente 2, sem pendência e sem exigir justificativa."""
        d = datetime.date(2026, 10, 1)
        op = criar_ordem_producao_com_saldos(self.processo, self.prod_bla4, d, 20, usuario=self.lider)
        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador1,
            itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 22, 'categorias': [], 'descricao_desvio': ''}]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, "CONCLUIDA")
        self.assertEqual(op.quantidade_realizada, 22)
        self.assertEqual(op.excedente, 2)
        self.assertEqual(op.saldo_gerado, 0)
        self.assertEqual(op.diferenca, 2)
        self.assertEqual(SaldoPendenteBladder.objects.filter(fechamento=fechamento).count(), 0)

    def test_13_a_15_fechamento_meta_20_realizado_18_exige_categoria_e_descricao(self):
        """13-15: Meta 20 / Realizado 18 -> Parcial, pendência 2, exigindo categoria e descrição livre."""
        d = datetime.date(2026, 10, 1)
        op = criar_ordem_producao_com_saldos(self.processo, self.prod_bla4, d, 20, usuario=self.lider)

        # 14: Sem categoria falha
        with self.assertRaises(ValueError) as cm1:
            executar_fechamento_turno(
                data_turno=d,
                operador=self.operador1,
                itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 18, 'categorias': [], 'descricao_desvio': 'Parada'}]
            )
        self.assertIn("o motivo do não cumprimento integral é obrigatório", str(cm1.exception))

        # 15: Com categoria mas sem descrição livre falha
        with self.assertRaises(ValueError) as cm2:
            executar_fechamento_turno(
                data_turno=d,
                operador=self.operador1,
                itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 18, 'categorias': [self.cat_equip.id], 'descricao_desvio': ''}]
            )
        self.assertIn("a descrição do ocorrido ('O que aconteceu?') é obrigatória", str(cm2.exception))

        # 13: Com categoria e descrição é aceito
        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 18,
                'categorias': [self.cat_equip.id],
                'descricao_desvio': 'A prensa apresentou vazamento durante o ciclo.'
            }]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, "PARCIAL")
        self.assertEqual(op.quantidade_realizada, 18)
        self.assertEqual(op.saldo_gerado, 2)
        self.assertEqual(op.excedente, 0)
        self.assertEqual(SaldoPendenteBladder.objects.filter(fechamento=fechamento).count(), 1)
        self.assertEqual(SaldoPendenteBladder.objects.get(fechamento=fechamento).quantidade, 2)

    def test_16_17_fechamento_meta_20_realizado_0_nao_realizada_exige_categoria_e_descricao(self):
        """16-17: Meta 20 / Realizado 0 -> Não realizada, pendência 20, exigindo categoria + descrição."""
        d = datetime.date(2026, 10, 1)
        op = criar_ordem_producao_com_saldos(self.processo, self.prod_bla4, d, 20, usuario=self.lider)

        with self.assertRaises(ValueError):
            executar_fechamento_turno(
                data_turno=d,
                operador=self.operador1,
                itens_dados=[{'ordem_id': op.id, 'quantidade_realizada': 0, 'categorias': [], 'descricao_desvio': ''}]
            )

        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 0,
                'categorias': [self.cat_mp.id],
                'descricao_desvio': 'Material não liberado pelo setor de preparação.'
            }]
        )
        op.refresh_from_db()
        self.assertEqual(op.status, "PARCIAL")  # Base model enum representa déficit com saldo
        self.assertEqual(op.quantidade_realizada, 0)
        self.assertEqual(op.saldo_gerado, 20)
        self.assertEqual(SaldoPendenteBladder.objects.get(fechamento=fechamento).quantidade, 20)

    def test_18_fechamento_suporta_multiplas_categorias(self):
        """18: Múltiplas categorias de desvio podem ser vinculadas ao mesmo item de fechamento."""
        d = datetime.date(2026, 10, 1)
        op = criar_ordem_producao_com_saldos(self.processo, self.prod_bla4, d, 20, usuario=self.lider)
        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op.id,
                'quantidade_realizada': 10,
                'categorias': [self.cat_mp.id, self.cat_operacional.id],
                'descricao_desvio': 'Falta de matéria-prima associada a remanejamento operacional.'
            }]
        )
        item = fechamento.itens.first()
        cats_ids = set(item.categorias.values_list('id', flat=True))
        self.assertIn(self.cat_mp.id, cats_ids)
        self.assertIn(self.cat_operacional.id, cats_ids)
        self.assertEqual(len(cats_ids), 2)
        self.assertIn("Falta de matéria-prima", item.categorias_display)
        self.assertIn("Problema operacional", item.categorias_display)

    # ------------------------------------------------------------------
    # 19 a 24: LEDGER DE PENDÊNCIAS
    # ------------------------------------------------------------------
    def test_19_a_24_ledger_rastreabilidade_e_sem_consumo_duplo(self):
        """19-24: Pendência nasce somente no fechamento, não cria OP automática, pode ser incorporada manualmente e não duplica consumo."""
        d1 = datetime.date(2026, 10, 1)
        op_origem = criar_ordem_producao_com_saldos(self.processo, self.prod_bla6, d1, 30, usuario=self.lider)

        # 19: Antes do fechamento, ledger não tem pendência
        self.assertEqual(SaldoPendenteBladder.objects.filter(op_origem=op_origem).count(), 0)

        # Fechamento com 27 realizadas (saldo 3)
        fechamento = executar_fechamento_turno(
            data_turno=d1,
            operador=self.operador1,
            itens_dados=[{
                'ordem_id': op_origem.id,
                'quantidade_realizada': 27,
                'categorias': [self.cat_equip.id],
                'descricao_desvio': 'Parada momentânea'
            }]
        )
        # 19 & 20: Pendência de 3 unidades nasce no Ledger, nenhuma OP nova foi criada automaticamente
        saldo_item = SaldoPendenteBladder.objects.get(op_origem=op_origem)
        self.assertEqual(saldo_item.quantidade, 3)
        self.assertEqual(saldo_item.status, "PENDENTE")
        self.assertEqual(OrdemProducaoBladder.objects.count(), 1)

        # 21 & 22: Líder posteriormente decide incorporar manualmente em nova OP
        d3 = datetime.date(2026, 10, 3)
        op_destino = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.prod_bla6,
            data_programada=d3,
            quantidade_nova=20,
            saldos_selecionados_ids=[saldo_item.id],
            usuario=self.lider
        )
        # 23: Rastreabilidade preservada
        self.assertEqual(op_destino.quantidade_nova, 20)
        self.assertEqual(op_destino.saldo_anterior_incorporado, 3)
        self.assertEqual(op_destino.quantidade_planejada, 23)

        saldo_item.refresh_from_db()
        self.assertEqual(saldo_item.status, "INCORPORADO")
        self.assertEqual(saldo_item.op_origem, op_origem)
        self.assertEqual(saldo_item.op_destino, op_destino)

        # 24: Não existe consumo duplo do mesmo saldo (tentar reutilizar saldo já incorporado não o incorpora)
        op_terceira = criar_ordem_producao_com_saldos(
            processo=self.processo,
            produto=self.prod_bla6,
            data_programada=d3,
            quantidade_nova=10,
            saldos_selecionados_ids=[saldo_item.id],
            usuario=self.lider
        )
        self.assertEqual(op_terceira.saldo_anterior_incorporado, 0)
        self.assertEqual(op_terceira.quantidade_planejada, 10)

    # ------------------------------------------------------------------
    # 25 a 32: RELATÓRIOS E DASHBOARD
    # ------------------------------------------------------------------
    def test_25_a_32_relatorios_cumprimento_uncapped_excedente_e_sem_duplicidade(self):
        """25-32: Cumprimento matemático acima de 100% não é limitado, excedente e pendência exibidos, produção não duplica."""
        d = datetime.date(2026, 10, 1)

        # OP1: 20 meta / 20 realizada -> 100%
        op1 = criar_ordem_producao_com_saldos(self.processo, self.prod_bla4, d, 20, usuario=self.lider)
        # OP2: 20 meta / 22 realizada -> 110%, Excedente = 2
        op2 = criar_ordem_producao_com_saldos(self.proc_prensa2, self.prod_bla6, d, 20, usuario=self.lider)
        # OP3: 20 meta / 18 realizada -> 90%, Pendência = 2
        op3 = criar_ordem_producao_com_saldos(self.proc_extrusora, self.prod_bla7, d, 20, usuario=self.lider)

        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador1,
            itens_dados=[
                {'ordem_id': op1.id, 'quantidade_realizada': 20, 'categorias': [], 'descricao_desvio': ''},
                {'ordem_id': op2.id, 'quantidade_realizada': 22, 'categorias': [], 'descricao_desvio': ''},
                {
                    'ordem_id': op3.id,
                    'quantidade_realizada': 18,
                    'categorias': [self.cat_qual.id],
                    'descricao_desvio': 'Ajuste de temperatura causou refugo'
                },
            ]
        )
        op1.refresh_from_db()
        op2.refresh_from_db()
        op3.refresh_from_db()

        # 25-27: Cumprimento matemático
        self.assertEqual(op1.percentual_conclusao, 100.0)
        self.assertEqual(op2.percentual_conclusao, 110.0)  # Não limitado a 100%!
        self.assertEqual(op3.percentual_conclusao, 90.0)

        # 28-29: Excedente e Pendência por OP
        self.assertEqual(op2.excedente, 2)
        self.assertEqual(op3.saldo_gerado, 2)

        # 30-31: Relatório web contém categorias e descrição
        res = self.client_lider.get(reverse("bladder:relatorios") + f"?mes={d.month}&ano={d.year}")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Problema de qualidade")
        self.assertContains(res, "Ajuste de temperatura causou refugo")
        self.assertContains(res, "110%")

        # 32: Exportação Excel não duplica e sanitiza
        res_excel = self.client_lider.get(reverse("bladder:relatorios_exportar_excel") + f"?mes={d.month}&ano={d.year}")
        self.assertEqual(res_excel.status_code, 200)
        self.assertEqual(res_excel['Content-Type'], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ------------------------------------------------------------------
    # 33 a 35: PERMISSÕES
    # ------------------------------------------------------------------
    def test_33_a_35_permissoes_operador_lider_staff(self):
        """33-35: Operador sem telas gerenciais, líder acessa planejamento, usuário sem perfil é bloqueado."""
        # 33: Operador bloqueado no planejamento (redirecionado com segurança para o chão de fábrica)
        res_op_nova = self.client_op1.get(reverse("bladder:ordem_nova"))
        self.assertRedirects(res_op_nova, reverse("bladder:operador"))
        res_op_rel = self.client_op1.get(reverse("bladder:relatorios"))
        self.assertRedirects(res_op_rel, reverse("bladder:operador"))

        # 34: Líder acessa planejamento
        res_lider_nova = self.client_lider.get(reverse("bladder:ordem_nova"))
        self.assertEqual(res_lider_nova.status_code, 200)
        res_lider_rel = self.client_lider.get(reverse("bladder:relatorios"))
        self.assertEqual(res_lider_rel.status_code, 200)

        # 35: Staff genérico sem acesso ao bladder bloqueado (redirecionado para portal_select)
        client_staff = Client()
        client_staff.force_login(self.sem_acesso)
        res_staff = client_staff.get(reverse("bladder:ordens_lista"))
        self.assertEqual(res_staff.status_code, 302)
        self.assertIn(reverse("portal_select"), res_staff['Location'])

    # ------------------------------------------------------------------
    # SEÇÃO 28: CENÁRIO INTEGRADO COMPLETO (DIA DA TURMA A)
    # ------------------------------------------------------------------
    def test_cenario_integrado_secao_28_dia_turma_a(self):
        """
        Teste Integrado Canônico da Seção 28:
        Programação do Dia da Turma A:
        - Prensa 01: BLA004, Meta = 20
        - Prensa 02: BLA006, Meta = 30
        - Extrusora: BLA007, Meta = 15
        - Extrusora: BLA009, Meta = 10
        Fechamento:
        - BLA004: 20
        - BLA006: 27 (Problema no equipamento, "Parada por falha durante o ciclo.")
        - BLA007: 17
        - BLA009: 0 (Falta de matéria-prima + Problema operacional, "Material não liberado em tempo para execução da atividade.")
        Auditoria de Totais e Regra Crítica:
        - Meta Total = 75
        - Realizado Total = 64
        - Pendência Total = 13 (3 + 10)
        - Excedente Total = 2
        - Diferença Líquida = -11
        - O excedente de BLA007 NÃO compensa o déficit de outros modelos.
        """
        d = datetime.date(2026, 10, 1)  # Turma A
        turma, _, _ = calcular_turma_do_dia(d)
        self.assertEqual(turma, "TURMA_A")

        # 1. Programação
        op1 = criar_ordem_producao_com_saldos(self.proc_prensa1, self.prod_bla4, d, 20, usuario=self.lider)
        op2 = criar_ordem_producao_com_saldos(self.proc_prensa2, self.prod_bla6, d, 30, usuario=self.lider)
        op3 = criar_ordem_producao_com_saldos(self.proc_extrusora, self.prod_bla7, d, 15, usuario=self.lider)
        op4 = criar_ordem_producao_com_saldos(self.proc_extrusora, self.prod_bla9, d, 10, usuario=self.lider)

        # Sistema deriva Turma A para todas
        self.assertEqual(op1.turma_prevista, "TURMA_A")
        self.assertEqual(op2.turma_prevista, "TURMA_A")
        self.assertEqual(op3.turma_prevista, "TURMA_A")
        self.assertEqual(op4.turma_prevista, "TURMA_A")

        # 2. Fechamento Único do Turno
        fechamento = executar_fechamento_turno(
            data_turno=d,
            operador=self.operador1,
            itens_dados=[
                {
                    'ordem_id': op1.id,
                    'quantidade_realizada': 20,
                    'categorias': [],
                    'descricao_desvio': ''
                },
                {
                    'ordem_id': op2.id,
                    'quantidade_realizada': 27,
                    'categorias': [self.cat_equip.id],
                    'descricao_desvio': 'Parada por falha durante o ciclo.'
                },
                {
                    'ordem_id': op3.id,
                    'quantidade_realizada': 17,
                    'categorias': [],
                    'descricao_desvio': ''
                },
                {
                    'ordem_id': op4.id,
                    'quantidade_realizada': 0,
                    'categorias': [self.cat_mp.id, self.cat_operacional.id],
                    'descricao_desvio': 'Material não liberado em tempo para execução da atividade.'
                },
            ]
        )

        op1.refresh_from_db()
        op2.refresh_from_db()
        op3.refresh_from_db()
        op4.refresh_from_db()

        # Resultados por OP:
        # BLA004: Meta 20, Realizado 20, Concluída, diferenca 0
        self.assertEqual(op1.status, "CONCLUIDA")
        self.assertEqual(op1.quantidade_realizada, 20)
        self.assertEqual(op1.diferenca, 0)
        self.assertEqual(op1.excedente, 0)
        self.assertEqual(op1.saldo_gerado, 0)

        # BLA006: Meta 30, Realizado 27, Parcial, Pendência 3, diferenca -3
        self.assertEqual(op2.status, "PARCIAL")
        self.assertEqual(op2.quantidade_realizada, 27)
        self.assertEqual(op2.diferenca, -3)
        self.assertEqual(op2.excedente, 0)
        self.assertEqual(op2.saldo_gerado, 3)

        # BLA007: Meta 15, Realizado 17, Concluída, Excedente 2, diferenca +2
        self.assertEqual(op3.status, "CONCLUIDA")
        self.assertEqual(op3.quantidade_realizada, 17)
        self.assertEqual(op3.diferenca, 2)
        self.assertEqual(op3.excedente, 2)
        self.assertEqual(op3.saldo_gerado, 0)

        # BLA009: Meta 10, Realizado 0, Não realizada, Pendência 10, diferenca -10
        self.assertEqual(op4.status, "PARCIAL")
        self.assertEqual(op4.quantidade_realizada, 0)
        self.assertEqual(op4.diferenca, -10)
        self.assertEqual(op4.excedente, 0)
        self.assertEqual(op4.saldo_gerado, 10)

        # TOTAIS DO DIA
        meta_total = op1.quantidade_planejada + op2.quantidade_planejada + op3.quantidade_planejada + op4.quantidade_planejada
        realizado_total = op1.quantidade_realizada + op2.quantidade_realizada + op3.quantidade_realizada + op4.quantidade_realizada
        self.assertEqual(meta_total, 75)
        self.assertEqual(realizado_total, 64)

        # PENDÊNCIA TOTAL DEVE SER CALCULADA POR OP:
        # sum(max(meta_op - realizado_op, 0)) -> 0 + 3 + 0 + 10 = 13
        pendencia_total_calculada = (
            max(0, op1.quantidade_planejada - op1.quantidade_realizada) +
            max(0, op2.quantidade_planejada - op2.quantidade_realizada) +
            max(0, op3.quantidade_planejada - op3.quantidade_realizada) +
            max(0, op4.quantidade_planejada - op4.quantidade_realizada)
        )
        self.assertEqual(pendencia_total_calculada, 13)

        # EXCEDENTE TOTAL:
        # sum(max(realizado_op - meta_op, 0)) -> 0 + 0 + 2 + 0 = 2
        excedente_total_calculado = (
            max(0, op1.quantidade_realizada - op1.quantidade_planejada) +
            max(0, op2.quantidade_realizada - op2.quantidade_planejada) +
            max(0, op3.quantidade_realizada - op3.quantidade_planejada) +
            max(0, op4.quantidade_realizada - op4.quantidade_planejada)
        )
        self.assertEqual(excedente_total_calculado, 2)

        # DIFERENÇA LÍQUIDA GERAL: 64 - 75 = -11
        diferenca_liquida = realizado_total - meta_total
        self.assertEqual(diferenca_liquida, -11)

        # VALIDAÇÃO CRÍTICA DA SEÇÃO 28:
        # Pendência total (13) NÃO É igual a abs(diferenca_liquida) (11)
        self.assertNotEqual(pendencia_total_calculada, abs(diferenca_liquida))
        self.assertEqual(pendencia_total_calculada, 13)
        self.assertEqual(excedente_total_calculado, 2)

        # Validação do Ledger: exatamente 2 registros de saldo abertos (3 un BLA006 e 10 un BLA009)
        saldos_ledger = SaldoPendenteBladder.objects.filter(fechamento=fechamento, status="PENDENTE")
        self.assertEqual(saldos_ledger.count(), 2)
        saldos_dict = {s.produto.codigo: s.quantidade for s in saldos_ledger}
        self.assertEqual(saldos_dict["BLA006"], 3)
        self.assertEqual(saldos_dict["BLA009"], 10)


# ==============================================================================
# PASSAGEM DE TURNO ENTRE AS EQUIPES DO SETOR DE BLADDER (TESTES FORMAIS)
# ==============================================================================

class PassagemTurnoBladderTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.grupo_lider, _ = Group.objects.get_or_create(name="Liderança Bladder")
        self.grupo_op, _ = Group.objects.get_or_create(name="Operadores Bladder")

        # Escala ativa base: Dia 05/10/2026 é Turma A
        self.data_base = datetime.date(2026, 10, 5)
        ConfiguracaoEscalaBladder.objects.all().delete()
        self.config_escala = ConfiguracaoEscalaBladder.objects.create(
            data_referencia=self.data_base,
            turma_referencia="TURMA_A",
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        # Usuários
        # Líder
        self.lider = User.objects.create_user(username="lider_teste", password="password123", first_name="Líder")
        self.lider.groups.add(self.grupo_lider)

        # Operadores Turma A
        self.joao = User.objects.create_user(username="joao_op", password="password123", first_name="João")
        self.joao.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.joao, turma="TURMA_A", ativo=True)

        self.jose = User.objects.create_user(username="jose_op", password="password123", first_name="José")
        self.jose.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.jose, turma="TURMA_A", ativo=True)

        # Operadores Turma B
        self.maria = User.objects.create_user(username="maria_op", password="password123", first_name="Maria")
        self.maria.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.maria, turma="TURMA_B", ativo=True)

        self.carlos = User.objects.create_user(username="carlos_op", password="password123", first_name="Carlos")
        self.carlos.groups.add(self.grupo_op)
        PerfilOperacionalBladder.objects.create(usuario=self.carlos, turma="TURMA_B", ativo=True)

        # Apoio Operacional
        self.apoio = User.objects.create_user(username="apoio_teste", password="password123", first_name="Apoio")
        self.apoio_obj = FuncionarioApoioBladder.objects.create(
            usuario=self.apoio,
            papel="Apoio Operacional",
            tipo_escala="DIAS_SEMANA",
            dias_semana="0,1,2,3,4,5,6",
            ativo=True
        )

        # Superuser
        self.admin = User.objects.create_superuser(username="admin_super", password="password123", email="admin@test.com")

        # Usuário de outro módulo (Manutenção sem perfil Bladder)
        self.grupo_manutencao, _ = Group.objects.get_or_create(name="Técnicos Manutenção")
        self.user_manutencao = User.objects.create_user(username="tec_manutencao", password="password123")
        self.user_manutencao.groups.add(self.grupo_manutencao)

        # Staff genérico (sem grupo Bladder)
        self.staff_generico = User.objects.create_user(username="staff_gen", password="password123", is_staff=True)

        # Máquina e Processo
        self.setor_bladders, _ = Sector.objects.get_or_create(nome="BLADDERS")
        self.maquina_prensa = Machine.objects.create(nome="Prensa 01", setor=self.setor_bladders)
        self.processo_prensa = ProcessoBladder.objects.create(
            codigo="PREN01", nome="Vulcanização Prensa 01", tipo="PRENSA", maquina=self.maquina_prensa, ordem_exibicao=1, ativo=True
        )

        # Produtos
        self.prod_bla006 = ProdutoBladder.objects.create(
            codigo="BLA006", descricao="Bladder BLA006 18x8", peso_tarugo_kg=Decimal("4.500"), ativo=True
        )
        self.prod_bla007 = ProdutoBladder.objects.create(
            codigo="BLA007", descricao="Bladder BLA007 20x8", peso_tarugo_kg=Decimal("5.100"), ativo=True
        )

        # OP de teste
        self.op1 = OrdemProducaoBladder.objects.create(
            numero_ordem="OP-BLA-20261005-0001",
            processo=self.processo_prensa,
            produto=self.prod_bla006,
            data_programada=self.data_base,
            turma_prevista="TURMA_A",
            quantidade_nova=30,
            quantidade_planejada=30,
            quantidade_realizada=0,
            status="PENDENTE",
            criado_por=self.lider
        )

    # 1. Turma A cria mensagem e destino calculado é próximo turno correto (Turma B / Dia 2)
    def test_01_turma_a_cria_mensagem_destino_automatico_proximo_turno_turma_b(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Tarugo separado ao lado da extrusora.",
            tipo="INFORMATIVO",
            categoria="MATERIAL",
            prioridade="NORMAL",
            data_turno_origem=self.data_base
        )
        self.assertEqual(msg.turma_origem, "TURMA_A")
        self.assertEqual(msg.data_turno_origem, self.data_base)
        self.assertEqual(msg.turma_destino, "TURMA_B")
        self.assertEqual(msg.data_turno_destino, self.data_base + datetime.timedelta(days=1))

    # 2. Turma B recebe automaticamente ao abrir Chão de Fábrica
    def test_02_turma_b_recebe_automaticamente_no_chao_de_fabrica(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Atenção à temperatura de prensagem no primeiro ciclo.",
            tipo="INFORMATIVO",
            categoria="EQUIPAMENTO",
            prioridade="IMPORTANTE",
            data_turno_origem=self.data_base
        )
        dia_seguinte = self.data_base + datetime.timedelta(days=1)
        self.client.login(username="maria_op", password="password123")
        response = self.client.get(reverse("bladder:operador") + f"?data={dia_seguinte.isoformat()}")
        self.assertEqual(response.status_code, 200)
        recados = response.context["recados_recebidos"]
        self.assertEqual(len(recados), 1)
        self.assertEqual(recados[0].id, msg.id)
        self.assertContains(response, "Atenção à temperatura de prensagem no primeiro ciclo.")

    # 3. Ajuste excepcional de escala é respeitado (inclusive FOLGA)
    def test_03_ajuste_excepcional_escala_respeitado(self):
        dia_seguinte = self.data_base + datetime.timedelta(days=1)  # 06/10
        dia_pos = self.data_base + datetime.timedelta(days=2)       # 07/10

        # Dia 06/10 é configurado como FOLGA (Parada Geral)
        AjusteEscalaExcepcionalBladder.objects.create(
            data=dia_seguinte,
            turma_designada="FOLGA",
            motivo="Manutenção Preventiva Geral",
            criado_por=self.lider
        )

        prox_data, prox_turma, is_ajuste, motivo = calcular_proximo_turno_operacional(self.data_base)
        self.assertEqual(prox_data, dia_pos)
        self.assertEqual(prox_turma, "TURMA_A")  # Na alternância regular, após folga do dia 06 (Turma B), dia 07 é Turma A

    # 4. Operador não escolhe destinatário manual
    def test_04_operador_nao_escolhe_destinatario_manual(self):
        form = MensagemPassagemTurnoForm()
        self.assertNotIn("turma_destino", form.fields)
        self.assertNotIn("data_turno_destino", form.fields)
        self.assertNotIn("destinatario", form.fields)

    # 5. Autor é registrado automaticamente
    def test_05_autor_registrado_automaticamente(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Verificar pressão hidráulica.",
            tipo="INFORMATIVO",
            categoria="EQUIPAMENTO",
            data_turno_origem=self.data_base
        )
        self.assertEqual(msg.autor, self.joao)

    # 6. Informativa permite CIENTE
    def test_06_informativa_permite_ciente(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Material novo no pallet.",
            tipo="INFORMATIVO",
            data_turno_origem=self.data_base
        )
        acao, created = registrar_ciencia_mensagem_turno(msg, self.maria)
        self.assertTrue(created)
        self.assertEqual(acao.acao, "CIENTE")
        self.assertEqual(acao.usuario, self.maria)
        self.assertTrue(msg.usuario_deu_ciencia(self.maria))

    # 7. Ciência de João não marca Maria como ciente
    def test_07_ciencia_de_joao_nao_marca_maria_como_ciente(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.carlos,
            mensagem="Aviso importante.",
            tipo="INFORMATIVO",
            data_turno_origem=self.data_base
        )
        registrar_ciencia_mensagem_turno(msg, self.joao)
        self.assertTrue(msg.usuario_deu_ciencia(self.joao))
        self.assertFalse(msg.usuario_deu_ciencia(self.maria))

    # 8. Mesmo usuário não duplica ciência
    def test_08_mesmo_usuario_nao_duplica_ciencia(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Teste idempotência.",
            tipo="INFORMATIVO",
            data_turno_origem=self.data_base
        )
        acao1, created1 = registrar_ciencia_mensagem_turno(msg, self.maria)
        acao2, created2 = registrar_ciencia_mensagem_turno(msg, self.maria)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(AcaoMensagemTurnoBladder.objects.filter(mensagem=msg, usuario=self.maria, acao="CIENTE").count(), 1)

    # 9. Acompanhamento permite RESOLVIDO
    def test_09_acompanhamento_permite_resolvido(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Prensa 01 com ruído.",
            tipo="ACOMPANHAMENTO",
            categoria="EQUIPAMENTO",
            data_turno_origem=self.data_base
        )
        self.assertEqual(msg.status, "ABERTA")
        resolver_mensagem_acompanhamento(msg, self.maria, observacao="Aperto de parafuso realizado.")
        msg.refresh_from_db()
        self.assertEqual(msg.status, "RESOLVIDA")

    # 10. Resolução registra usuário e data/hora
    def test_10_resolucao_registra_usuario_e_data(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Verificar válvula.",
            tipo="ACOMPANHAMENTO",
            data_turno_origem=self.data_base
        )
        resolver_mensagem_acompanhamento(msg, self.maria, observacao="Válvula calibrada.")
        msg.refresh_from_db()
        self.assertEqual(msg.resolvido_por, self.maria)
        self.assertIsNotNone(msg.resolvido_em)
        self.assertEqual(msg.observacao_resolucao, "Válvula calibrada.")
        self.assertTrue(AcaoMensagemTurnoBladder.objects.filter(mensagem=msg, usuario=self.maria, acao="RESOLVIDO").exists())

    # 11. Acompanhamento permite REPASSAR
    def test_11_acompanhamento_permite_repassar(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Vazamento ainda sob monitoramento.",
            tipo="ACOMPANHAMENTO",
            data_turno_origem=self.data_base
        )
        nova_msg = repassar_mensagem_acompanhamento(msg, self.maria, observacao="Ainda requer observação.")
        msg.refresh_from_db()
        self.assertEqual(msg.status, "REPASSADA")
        self.assertEqual(nova_msg.status, "ABERTA")

    # 12. Repasse cria continuidade preservando origem
    def test_12_repasse_cria_continuidade_preservando_origem(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Problema crônico no termopar.",
            tipo="ACOMPANHAMENTO",
            data_turno_origem=self.data_base
        )
        nova_msg = repassar_mensagem_acompanhamento(msg, self.maria, observacao="Troca de turno B para A.")
        self.assertEqual(nova_msg.mensagem_origem, msg)
        self.assertIn(msg, nova_msg.cadeia_historica)

    # 13. Repasse calcula corretamente o próximo turno
    def test_13_repasse_calcula_corretamente_proximo_turno(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Verificar no início do dia.",
            tipo="ACOMPANHAMENTO",
            data_turno_origem=self.data_base
        )
        # msg vai para Turma B / Dia 06
        self.assertEqual(msg.data_turno_destino, self.data_base + datetime.timedelta(days=1))
        self.assertEqual(msg.turma_destino, "TURMA_B")

        # Maria (Turma B no Dia 06) repassa para a próxima equipe
        nova = repassar_mensagem_acompanhamento(msg, self.maria)
        self.assertEqual(nova.turma_origem, "TURMA_B")
        self.assertEqual(nova.data_turno_origem, self.data_base + datetime.timedelta(days=1))
        self.assertEqual(nova.turma_destino, "TURMA_A")
        self.assertEqual(nova.data_turno_destino, self.data_base + datetime.timedelta(days=2))

    # 14. Mensagem original não é alterada destrutivamente
    def test_14_mensagem_original_nao_e_alterada_destrutivamente(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Texto original intacto.",
            tipo="ACOMPANHAMENTO",
            data_turno_origem=self.data_base
        )
        repassar_mensagem_acompanhamento(msg, self.maria)
        msg.refresh_from_db()
        self.assertEqual(msg.mensagem, "Texto original intacto.")
        self.assertEqual(msg.autor, self.joao)
        self.assertEqual(msg.turma_origem, "TURMA_A")

    # 15. OP opcional fica vinculada
    def test_15_op_opcional_fica_vinculada(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Recado sobre a OP.",
            tipo="INFORMATIVO",
            ordem_producao=self.op1,
            data_turno_origem=self.data_base
        )
        self.assertEqual(msg.ordem_producao, self.op1)

    # 16. Produto e contexto correto são derivados da OP
    def test_16_produto_e_contexto_derivados(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Contexto derivado.",
            tipo="INFORMATIVO",
            ordem_producao=self.op1,
            data_turno_origem=self.data_base
        )
        self.assertEqual(msg.produto, self.prod_bla006)
        self.assertEqual(msg.processo, self.processo_prensa)
        self.assertEqual(msg.maquina, self.maquina_prensa)

    # 17. Mensagem não altera OP
    def test_17_mensagem_nao_altera_op(self):
        status_antigo = self.op1.status
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Recado.",
            ordem_producao=self.op1,
            data_turno_origem=self.data_base
        )
        self.op1.refresh_from_db()
        self.assertEqual(self.op1.status, status_antigo)

    # 18. Mensagem não altera Meta
    def test_18_mensagem_nao_altera_meta(self):
        meta_antiga = self.op1.quantidade_planejada
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Recado.",
            ordem_producao=self.op1,
            data_turno_origem=self.data_base
        )
        self.op1.refresh_from_db()
        self.assertEqual(self.op1.quantidade_planejada, meta_antiga)

    # 19. Mensagem não altera Realizado
    def test_19_mensagem_nao_altera_realizado(self):
        real_antigo = self.op1.quantidade_realizada
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Recado.",
            ordem_producao=self.op1,
            data_turno_origem=self.data_base
        )
        self.op1.refresh_from_db()
        self.assertEqual(self.op1.quantidade_realizada, real_antigo)

    # 20. Mensagem não cria SaldoPendenteBladder
    def test_20_mensagem_nao_cria_saldopendentebladder(self):
        cont_antigo = SaldoPendenteBladder.objects.count()
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Recado.",
            ordem_producao=self.op1,
            data_turno_origem=self.data_base
        )
        self.assertEqual(SaldoPendenteBladder.objects.count(), cont_antigo)

    # 21. Funcionário de Apoio autorizado visualiza e atua
    def test_21_funcionario_apoio_autorizado_visualiza_e_atua(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Apoio deve checar anéis de acabamento.",
            tipo="ACOMPANHAMENTO",
            data_turno_origem=self.data_base
        )
        self.client.login(username="apoio_teste", password="password123")
        dia_seguinte = self.data_base + datetime.timedelta(days=1)
        response = self.client.get(reverse("bladder:operador") + f"?data={dia_seguinte.isoformat()}")
        self.assertEqual(response.status_code, 200)

        # Apoio registra ciência
        acao, created = registrar_ciencia_mensagem_turno(msg, self.apoio)
        self.assertTrue(created)
        self.assertTrue(msg.usuario_deu_ciencia(self.apoio))

    # 22. Apoio não é transformado em Turma A/B
    def test_22_apoio_nao_e_transformado_em_turma_a_b(self):
        msg = criar_mensagem_passagem_turno(
            autor=self.apoio,
            mensagem="Recado registrado pelo apoio.",
            data_turno_origem=self.data_base
        )
        self.assertEqual(msg.turma_origem, "TURMA_A")  # Turma titular oficial do dia 05/10
        self.assertEqual(msg.autor, self.apoio)
        self.assertFalse(hasattr(self.apoio, "perfil_operacional_bladder"))

    # 23. Líder visualiza histórico e filtros
    def test_23_lider_visualiza_historico_e_filtros(self):
        criar_mensagem_passagem_turno(autor=self.joao, mensagem="Recado 1", prioridade="URGENTE", data_turno_origem=self.data_base)
        criar_mensagem_passagem_turno(autor=self.maria, mensagem="Recado 2", prioridade="NORMAL", data_turno_origem=self.data_base)

        self.client.login(username="lider_teste", password="password123")
        response = self.client.get(reverse("bladder:passagem_turno_lista"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_geral"], 2)

        # Filtro por prioridade
        resp_urgente = self.client.get(reverse("bladder:passagem_turno_lista") + "?prioridade=URGENTE")
        self.assertEqual(resp_urgente.status_code, 200)
        self.assertEqual(len(resp_urgente.context["mensagens"]), 1)

    # 24. Operador de outro módulo não acessa
    def test_24_operador_de_outro_modulo_nao_acessa(self):
        self.client.login(username="tec_manutencao", password="password123")
        response = self.client.get(reverse("bladder:operador"))
        self.assertRedirects(response, reverse("portal_select"), fetch_redirect_response=False)

        resp_post = self.client.post(reverse("bladder:passagem_turno_criar"), data={"mensagem": "Hack"})
        self.assertRedirects(resp_post, reverse("portal_select"), fetch_redirect_response=False)

    # 25. Staff genérico não acessa
    def test_25_staff_generico_nao_acessa(self):
        self.client.login(username="staff_gen", password="password123")
        response = self.client.get(reverse("bladder:operador"))
        self.assertRedirects(response, reverse("portal_select"), fetch_redirect_response=False)

    # 26. Superuser acessa tudo
    def test_26_superuser_acessa(self):
        self.client.login(username="admin_super", password="password123")
        response = self.client.get(reverse("bladder:operador"))
        self.assertEqual(response.status_code, 200)
        response_lider = self.client.get(reverse("bladder:passagem_turno_lista"))
        self.assertEqual(response_lider.status_code, 200)

    # 27. URL direta protegida no backend
    def test_27_url_direta_protegida_backend(self):
        msg = criar_mensagem_passagem_turno(autor=self.joao, mensagem="Msg teste.", data_turno_origem=self.data_base)
        client_anonimo = Client()
        resp = client_anonimo.post(reverse("bladder:passagem_turno_acao", kwargs={"pk": msg.id}), data={"acao": "CIENTE"})
        self.assertEqual(resp.status_code, 302)  # Redireciona para login

    # 28. Mensagem resolvida permanece no histórico
    def test_28_mensagem_resolvida_permanece_no_historico(self):
        msg = criar_mensagem_passagem_turno(autor=self.joao, mensagem="Resolvida persistente.", tipo="ACOMPANHAMENTO", data_turno_origem=self.data_base)
        resolver_mensagem_acompanhamento(msg, self.maria)
        self.assertTrue(MensagemPassagemTurnoBladder.objects.filter(pk=msg.id, status="RESOLVIDA").exists())

    # 29. Filtro por período funciona
    def test_29_filtro_por_periodo_funciona(self):
        dia1 = self.data_base
        dia2 = self.data_base + datetime.timedelta(days=1)
        criar_mensagem_passagem_turno(autor=self.joao, mensagem="Dia 1", data_turno_origem=dia1)
        criar_mensagem_passagem_turno(autor=self.maria, mensagem="Dia 2", data_turno_origem=dia2)

        self.client.login(username="lider_teste", password="password123")
        url = reverse("bladder:passagem_turno_lista") + f"?data_inicio={dia2.isoformat()}&data_fim={dia2.isoformat()}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["mensagens"]), 1)
        self.assertEqual(response.context["mensagens"][0].mensagem, "Dia 2")

    # 30. Prioridade Urgente aparece antes da Normal
    def test_30_prioridade_urgente_aparece_antes_da_normal(self):
        msg_normal = criar_mensagem_passagem_turno(autor=self.joao, mensagem="Normal", prioridade="NORMAL", data_turno_origem=self.data_base)
        msg_urgente = criar_mensagem_passagem_turno(autor=self.joao, mensagem="Urgente", prioridade="URGENTE", data_turno_origem=self.data_base)

        lista = obter_mensagens_recebidas_turno(
            data_turno=self.data_base + datetime.timedelta(days=1),
            turma="TURMA_B"
        )
        self.assertEqual(lista[0].id, msg_urgente.id)
        self.assertEqual(lista[1].id, msg_normal.id)

    # 31. Teste Integrado Canônico (Seção 33): Dia 1 Turma A -> Dia 2 Turma B repassa -> Dia 3 Turma A resolve
    def test_31_cenario_integrado_completo_dia1_a_dia2_b_dia3_a(self):
        # DIA 1 — TURMA A: João cria ACOMPANHAMENTO
        dia1 = self.data_base
        msg1 = criar_mensagem_passagem_turno(
            autor=self.joao,
            tipo="ACOMPANHAMENTO",
            categoria="EQUIPAMENTO",
            prioridade="IMPORTANTE",
            mensagem="Pequeno vazamento observado próximo ao final do turno. Verificar antes de iniciar a atividade.",
            ordem_producao=self.op1,
            data_turno_origem=dia1
        )
        self.assertEqual(msg1.turma_origem, "TURMA_A")
        self.assertEqual(msg1.turma_destino, "TURMA_B")
        self.assertEqual(msg1.data_turno_destino, dia1 + datetime.timedelta(days=1))

        # DIA 2 — TURMA B: Maria abre Chão de Fábrica, dá ciência e repassa
        dia2 = dia1 + datetime.timedelta(days=1)
        self.client.login(username="maria_op", password="password123")
        resp_dia2 = self.client.get(reverse("bladder:operador") + f"?data={dia2.isoformat()}")
        self.assertEqual(resp_dia2.status_code, 200)
        self.assertContains(resp_dia2, "Pequeno vazamento observado próximo ao final do turno.")

        # Maria marca CIENTE
        registrar_ciencia_mensagem_turno(msg1, self.maria)
        self.assertTrue(msg1.usuario_deu_ciencia(self.maria))
        self.assertFalse(msg1.usuario_deu_ciencia(self.carlos))  # Outro operador da Turma B não está ciente

        # Maria seleciona REPASSAR AO PRÓXIMO TURNO
        msg2 = repassar_mensagem_acompanhamento(msg1, self.maria, observacao="Vazamento persiste na partida.")
        self.assertEqual(msg1.status, "REPASSADA")
        self.assertEqual(msg2.turma_origem, "TURMA_B")
        self.assertEqual(msg2.turma_destino, "TURMA_A")
        self.assertEqual(msg2.data_turno_destino, dia1 + datetime.timedelta(days=2))
        self.assertEqual(msg2.mensagem_origem, msg1)

        # DIA 3 — TURMA A: José recebe e marca RESOLVIDO
        dia3 = dia1 + datetime.timedelta(days=2)
        self.client.login(username="jose_op", password="password123")
        resp_dia3 = self.client.get(reverse("bladder:operador") + f"?data={dia3.isoformat()}")
        self.assertEqual(resp_dia3.status_code, 200)

        resolver_mensagem_acompanhamento(msg2, self.jose, observacao="Troca de retentor concluída.")
        msg2.refresh_from_db()
        self.assertEqual(msg2.status, "RESOLVIDA")
        self.assertEqual(msg2.resolvido_por, self.jose)

        # Verificação da Cadeia Completa
        self.assertEqual(msg2.cadeia_historica, [msg1])
        # Nenhuma OP ou saldo de produção foi alterado
        self.op1.refresh_from_db()
        self.assertEqual(self.op1.quantidade_realizada, 0)
        self.assertEqual(SaldoPendenteBladder.objects.count(), 0)

    # 32. Teste Informativo Canônico (Seção 34): Turma A envia INFORMATIVO, Turma B recebe e dá CIENTE
    def test_32_cenario_informativo_sem_resolver_ou_repassar(self):
        msg_info = criar_mensagem_passagem_turno(
            autor=self.joao,
            tipo="INFORMATIVO",
            categoria="PRODUCAO",
            mensagem="Material do BLA007 ficou separado ao lado da extrusora.",
            data_turno_origem=self.data_base
        )
        self.assertEqual(msg_info.tipo, "INFORMATIVO")

        # Turma B recebe e dá ciência
        acao, created = registrar_ciencia_mensagem_turno(msg_info, self.maria)
        self.assertTrue(created)

        # Tentativa de resolver ou repassar mensagem informativa deve falhar
        with self.assertRaises(ValueError):
            resolver_mensagem_acompanhamento(msg_info, self.maria)
        with self.assertRaises(ValueError):
            repassar_mensagem_acompanhamento(msg_info, self.maria)

    # 33. Integração com Fechamento do Turno e Independência da Produção
    def test_33_fechamento_turno_integracao_e_independencia_producao(self):
        self.client.login(username="joao_op", password="password123")
        response = self.client.get(reverse("bladder:fechamento_turno"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PASSAGEM PARA O PRÓXIMO TURNO")

        # Fechamento pode ocorrer normalmente mesmo sem recados criados
        post_data = {
            f"qtd_realizada_{self.op1.id}": "30",
            f"categorias_{self.op1.id}": [],
            f"descricao_desvio_{self.op1.id}": "",
            "observacoes_gerais": "Turno normal sem recados adicionais."
        }
        resp_post = self.client.post(reverse("bladder:fechamento_turno"), data=post_data)
        self.assertRedirects(resp_post, reverse("bladder:operador"))
        self.op1.refresh_from_db()
        self.assertEqual(self.op1.status, "CONCLUIDA")

    # 34. Layout touch-friendly e responsividade para Tablet
    def test_34_responsividade_e_tablet_touch_friendly(self):
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Layout tablet test.",
            prioridade="URGENTE",
            data_turno_origem=self.data_base
        )
        dia_seguinte = self.data_base + datetime.timedelta(days=1)
        self.client.login(username="maria_op", password="password123")
        response = self.client.get(reverse("bladder:operador") + f"?data={dia_seguinte.isoformat()}")
        self.assertEqual(response.status_code, 200)
        # Verifica a presença dos botões touch com classe touch-btn
        self.assertContains(response, "touch-btn")
        self.assertContains(response, "PASSAGEM DO TURNO ANTERIOR")
        self.assertContains(response, "collapseRecadosTurno")

    # 35. Operador titular acessa a tela de Recados Criados
    def test_35_operador_acessa_tela_recados_criados(self):
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Recado criado para a turma seguinte.",
            data_turno_origem=self.data_base
        )
        self.client.login(username="joao_op", password="password123")
        response = self.client.get(reverse("bladder:recados_criados"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quadro de Recados e Passagem de Turno")
        self.assertContains(response, "Recado criado para a turma seguinte.")

    # 36. Funcionário de Apoio e Líder acessam a tela de Recados Criados
    def test_36_apoio_e_lider_acessam_recados_criados(self):
        # Apoio acessa
        self.client.login(username="apoio_teste", password="password123")
        resp_apoio = self.client.get(reverse("bladder:recados_criados"))
        self.assertEqual(resp_apoio.status_code, 200)

        # Líder acessa
        self.client.login(username="lider_teste", password="password123")
        resp_lider = self.client.get(reverse("bladder:recados_criados"))
        self.assertEqual(resp_lider.status_code, 200)

    # 37. Operador de outro módulo e staff genérico são bloqueados na tela de Recados Criados
    def test_37_usuario_externo_bloqueado_em_recados_criados(self):
        self.client.login(username="tec_manutencao", password="password123")
        resp_tec = self.client.get(reverse("bladder:recados_criados"))
        self.assertRedirects(resp_tec, reverse("portal_select"), fetch_redirect_response=False)

        self.client.login(username="staff_gen", password="password123")
        resp_staff = self.client.get(reverse("bladder:recados_criados"))
        self.assertRedirects(resp_staff, reverse("portal_select"), fetch_redirect_response=False)

    # 38. Filtros por visão na tela de Recados Criados (meu_turno, todos, meus, abertas, resolvidas)
    def test_38_filtros_visao_recados_criados(self):
        msg1 = criar_mensagem_passagem_turno(autor=self.joao, mensagem="Msg Joao 1", tipo="ACOMPANHAMENTO", data_turno_origem=self.data_base)
        msg2 = criar_mensagem_passagem_turno(autor=self.maria, mensagem="Msg Maria 2", tipo="INFORMATIVO", data_turno_origem=self.data_base)
        resolver_mensagem_acompanhamento(msg1, self.maria)

        self.client.login(username="joao_op", password="password123")

        # Visão: todos
        resp_todos = self.client.get(reverse("bladder:recados_criados") + "?visao=todos")
        self.assertEqual(resp_todos.status_code, 200)
        self.assertEqual(len(resp_todos.context["mensagens"]), 2)

        # Visão: meus
        resp_meus = self.client.get(reverse("bladder:recados_criados") + "?visao=meus")
        self.assertEqual(resp_meus.status_code, 200)
        self.assertEqual(len(resp_meus.context["mensagens"]), 1)
        self.assertEqual(resp_meus.context["mensagens"][0].autor, self.joao)

        # Visão: resolvidas
        resp_resolvidas = self.client.get(reverse("bladder:recados_criados") + "?visao=resolvidas")
        self.assertEqual(resp_resolvidas.status_code, 200)
        self.assertEqual(len(resp_resolvidas.context["mensagens"]), 1)
        self.assertEqual(resp_resolvidas.context["mensagens"][0].status, "RESOLVIDA")

    # 39. Filtros por categoria, prioridade e busca textual em Recados Criados
    def test_39_filtros_categoria_e_busca_recados_criados(self):
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Vazamento crítico de óleo na Prensa 01.",
            categoria="EQUIPAMENTO",
            prioridade="URGENTE",
            data_turno_origem=self.data_base
        )
        criar_mensagem_passagem_turno(
            autor=self.joao,
            mensagem="Pallet de composto pronto.",
            categoria="MATERIAL",
            prioridade="NORMAL",
            data_turno_origem=self.data_base
        )

        self.client.login(username="joao_op", password="password123")

        # Filtro categoria EQUIPAMENTO
        resp_cat = self.client.get(reverse("bladder:recados_criados") + "?visao=todos&categoria=EQUIPAMENTO")
        self.assertEqual(len(resp_cat.context["mensagens"]), 1)
        self.assertContains(resp_cat, "Vazamento crítico")

        # Busca textual
        resp_busca = self.client.get(reverse("bladder:recados_criados") + "?visao=todos&q=óleo")
        self.assertEqual(len(resp_busca.context["mensagens"]), 1)










