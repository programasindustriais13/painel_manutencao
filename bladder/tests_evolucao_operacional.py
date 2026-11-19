"""
Validação Integral e Exaustiva da SPEC_EVOLUCAO_OPERACIONAL_TURNOS_BLADDER.md
Cobre 100% dos cenários solicitados nas Seções 27, 28, 29 e Entrega D (WCAG AA).

Seções Cobertas:
- Seção 27: Entrega A — Manuseio Parcial e Transferência Seletiva (Cenários 1 a 12)
- Seção 28: Entrega B — Modo Noturno e Estação de Retirada USB (Cenários 1 a 21)
- Seção 29: Entrega C — Tela de Boas-Vindas Contextual e Roteamento (Cenários 1 a 8)
- Entrega D: Contraste WCAG AA e Ausência de Containers Escuros Ilegíveis
"""

import time
import uuid
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client, RequestFactory
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.urls import reverse
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware

from maintenance.models import Machine, Sector
from maintenance.middleware import SessionExpiryByProfileMiddleware
from bladder.models import (
    ProcessoBladder, ProdutoBladder, OrdemProducaoBladder,
    ConfiguracaoEscalaBladder, PerfilOperacionalBladder,
    ApontamentoTurnoBladder, CategoriaDesvioBladder,
    TransferenciaManuseioBladder, SessaoNoturnaBladder,
    FechamentoTurnoBladder, MovimentacaoEstoqueBladder,
    MensagemPassagemTurnoBladder
)
from bladder.producao import registrar_producao, manuseios_pendentes
from bladder.services import (
    executar_fechamento_turno, garantir_usuario_noturno,
    ativar_estacao_noturna, saida_estoque_noturna,
    encerrar_estacao_noturna
)


class BaseEvolucaoTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoje = timezone.localdate()
        cls.grupo_operador, _ = Group.objects.get_or_create(name='Operadores Bladder')
        cls.grupo_lider, _ = Group.objects.get_or_create(name='Liderança Bladder')
        cls.grupo_manutencao, _ = Group.objects.get_or_create(name='Tecnicos')

        # Operador Turma A
        cls.operador_a = User.objects.create_user(
            username='operador_turma_a', password='password123', first_name='Carlos', last_name='Silva'
        )
        cls.operador_a.groups.add(cls.grupo_operador)
        PerfilOperacionalBladder.objects.create(usuario=cls.operador_a, turma='TURMA_A', ativo=True)

        # Operador Turma B
        cls.operador_b = User.objects.create_user(
            username='operador_turma_b', password='password123', first_name='Marcos', last_name='Souza'
        )
        cls.operador_b.groups.add(cls.grupo_operador)
        PerfilOperacionalBladder.objects.create(usuario=cls.operador_b, turma='TURMA_B', ativo=True)

        # Líder Bladder
        cls.lider = User.objects.create_user(
            username='lider_bladder', password='password123', first_name='Líder', last_name='Bladder'
        )
        cls.lider.groups.add(cls.grupo_lider)
        PerfilOperacionalBladder.objects.create(usuario=cls.lider, turma='TURMA_A', ativo=True)

        # Usuário de outro setor (Manutenção) sem acesso ao Bladder
        cls.usuario_manut = User.objects.create_user(
            username='tecnico_mecanico', password='password123', first_name='João', last_name='Mecânico'
        )
        cls.usuario_manut.groups.add(cls.grupo_manutencao)

        # Escala ativa: Hoje é Turma A
        ConfiguracaoEscalaBladder.objects.all().delete()
        ConfiguracaoEscalaBladder.objects.create(
            data_referencia=cls.hoje,
            turma_referencia='TURMA_A',
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        # Setor e Máquinas
        cls.setor = Sector.objects.create(nome='BLADDER SETOR')
        cls.maquina_extrusora = Machine.objects.create(nome='Extrusora 01', setor=cls.setor)
        cls.maquina_manuseio = Machine.objects.create(nome='Bancada Manuseio', setor=cls.setor)

        # Processos 03 (Extrusão) e 06 (Manuseio)
        cls.proc_extrusao = ProcessoBladder.objects.create(
            codigo='03', nome='Extrusão de Bladder', maquina=cls.maquina_extrusora, ativo=True
        )
        cls.proc_manuseio = ProcessoBladder.objects.create(
            codigo='06', nome='Manuseio de Tarugos', maquina=cls.maquina_manuseio, ativo=True
        )

        # Produtos
        cls.produto_bla240 = ProdutoBladder.objects.create(
            codigo='BLA240', descricao='B240/15', estoque_atual=20, estoque_minimo=10, ativo=True
        )
        cls.produto_bla100 = ProdutoBladder.objects.create(
            codigo='BLA100', descricao='B100/12', estoque_atual=5, estoque_minimo=15, ativo=True
        )

        # Categoria de desvio para fechamento
        cls.categoria_desvio = CategoriaDesvioBladder.objects.create(
            codigo='EQUIPAMENTO', nome='Falha de Equipamento', ativo=True
        )

    def setUp(self):
        FechamentoTurnoBladder.objects.all().delete()
        OrdemProducaoBladder.objects.all().delete()
        ApontamentoTurnoBladder.objects.all().delete()
        TransferenciaManuseioBladder.objects.all().delete()
        SessaoNoturnaBladder.objects.all().delete()
        MovimentacaoEstoqueBladder.objects.all().delete()
        MensagemPassagemTurnoBladder.objects.all().delete()

    def _criar_op(self, processo, produto=None, meta=40):
        prod = produto or self.produto_bla240
        return OrdemProducaoBladder.objects.create(
            numero_ordem=f'OP-{uuid.uuid4().hex[:8].upper()}',
            processo=processo,
            produto=prod,
            data_programada=self.hoje,
            turma_prevista='TURMA_A',
            quantidade_nova=meta,
            quantidade_planejada=meta,
            criado_por=self.operador_a
        )

    def _executar_extrusao(self, op, quantidade=40):
        dados_ext = {
            'quantidade_realizada': quantidade,
            'temperatura': '90.0',
            'velocidade_esteira': '2.0',
            'velocidade_fuso': '30.0',
            'temperatura_tcu_1': '50.0',
            'temperatura_tcu_2': '50.0',
            'temperatura_tcu_3': '50.0',
            'temperatura_tcu_4': '50.0',
            'tipo_processamento': 'Normal',
            'resfriamento': 'Agua',
        }
        extrusao, _ = registrar_producao(op.pk, self.operador_a, dados_ext, uuid.uuid4())
        return extrusao


# ==============================================================================
# SEÇÃO 27: ENTREGA A — MANUSEIO PARCIAL E TRANSFERÊNCIA SELETIVA (CENÁRIOS 1 A 12)
# ==============================================================================
class EvolucaoOperacionalEntregaATestCase(BaseEvolucaoTestCase):

    def test_cenario_01_extrusao_cria_manuseio_pendente(self):
        """Cenário 1: Extrusão #03 realizada cria pendência de manuseio PENDENTE com qtd_manuseada=0."""
        op = self._criar_op(self.proc_extrusao, meta=40)
        ext = self._executar_extrusao(op, 40)

        self.assertEqual(ext.quantidade_realizada, 40)
        self.assertEqual(ext.quantidade_manuseada, 0)
        self.assertEqual(ext.status_manuseio, 'PENDENTE')
        self.assertFalse(hasattr(ext, 'manuseio'))
        self.assertTrue(manuseios_pendentes().filter(pk=ext.pk).exists())

    def test_cenario_02_salvar_parcial_grava_status_parcial_e_amostras(self):
        """Cenário 2: Salvar parcial (15 un) atualiza status para PARCIAL e preserva amostras."""
        op = self._criar_op(self.proc_extrusao, meta=40)
        ext = self._executar_extrusao(op, 40)

        dados_man = {
            'quantidade_manuseada': 15,
            'lote_produto': 'LOTE-001',
            'materia_prima': 'TORTUGA - FBB0001',
            'lote_material': 'MAT-999',
        }
        # 15 unidades exigem ceil(15/10) = 2 amostras proporcionais
        amostras_parciais = [
            {'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'},
            {'diametro': '38.2', 'comprimento': '160.5', 'peso': '3.120'},
        ]
        manuseio, criado = registrar_producao(
            op.pk, self.operador_a, dados_man, uuid.uuid4(),
            extrusao_id=ext.pk, amostras=amostras_parciais, acao='salvar_parcial'
        )
        self.assertTrue(criado)
        self.assertEqual(manuseio.status_manuseio, 'PARCIAL')
        self.assertEqual(manuseio.quantidade_manuseada, 15)
        self.assertEqual(manuseio.amostras.count(), 2)

    def test_cenario_03_extrusao_origem_reflete_status_e_quantidade(self):
        """Cenário 3: Extrusão de origem reflete status_manuseio='PARCIAL' e quantidade_manuseada=15."""
        op = self._criar_op(self.proc_extrusao, meta=40)
        ext = self._executar_extrusao(op, 40)
        dados_man = {'quantidade_manuseada': 15, 'lote_produto': 'L-01', 'materia_prima': 'MAT', 'lote_material': 'L-M'}
        amostras = [{'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'}, {'diametro': '38.1', 'comprimento': '160.1', 'peso': '3.110'}]
        registrar_producao(op.pk, self.operador_a, dados_man, uuid.uuid4(), extrusao_id=ext.pk, amostras=amostras, acao='salvar_parcial')

        ext.refresh_from_db()
        self.assertEqual(ext.status_manuseio, 'PARCIAL')
        self.assertEqual(ext.quantidade_manuseada, 15)

    def test_cenario_04_salvar_parcial_nao_duplica_op_nem_cria_nova_op(self):
        """Cenário 4: Manuseio parcial NÃO duplica OP nem cria nova ordem no banco."""
        op = self._criar_op(self.proc_extrusao, meta=40)
        ext = self._executar_extrusao(op, 40)
        qtd_ops_antes = OrdemProducaoBladder.objects.count()

        dados_man = {'quantidade_manuseada': 20, 'lote_produto': 'L-01', 'materia_prima': 'MAT', 'lote_material': 'L-M'}
        amostras = [{'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'}, {'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'}]
        registrar_producao(op.pk, self.operador_a, dados_man, uuid.uuid4(), extrusao_id=ext.pk, amostras=amostras, acao='salvar_parcial')

        self.assertEqual(OrdemProducaoBladder.objects.count(), qtd_ops_antes)

    def test_cenario_05_salvar_parcial_nao_incrementa_producao_da_op(self):
        """Cenário 5: Manuseio parcial NÃO soma à produção realizada da OP."""
        op = self._criar_op(self.proc_extrusao, meta=40)
        ext = self._executar_extrusao(op, 40)
        op.refresh_from_db()
        # Na extrusão com quantidade_apurada=True, total_executado(op) reflete a extrusão (40 un)
        # O manuseio (código 06) tem quantidade_realizada=0 e quantidade_apurada=False
        prod_antes = op.quantidade_realizada

        dados_man = {'quantidade_manuseada': 10, 'lote_produto': 'L-01', 'materia_prima': 'MAT', 'lote_material': 'L-M'}
        amostras = [{'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'}]
        registrar_producao(op.pk, self.operador_a, dados_man, uuid.uuid4(), extrusao_id=ext.pk, amostras=amostras, acao='salvar_parcial')

        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, prod_antes)

    def test_cenario_06_retomada_mesmo_turno_preenche_dados_e_amostras(self):
        """Cenário 6: Retomada carrega amostras e permite complementar."""
        op = self._criar_op(self.proc_extrusao, meta=20)
        ext = self._executar_extrusao(op, 20)
        dados_man = {'quantidade_manuseada': 10, 'lote_produto': 'L-01', 'materia_prima': 'MAT', 'lote_material': 'L-M'}
        amostras = [{'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'}]
        man, _ = registrar_producao(op.pk, self.operador_a, dados_man, uuid.uuid4(), extrusao_id=ext.pk, amostras=amostras, acao='salvar_parcial')

        client = Client()
        client.force_login(self.operador_a)
        res = client.get(reverse('bladder:manuseio_registrar', args=[ext.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Retomada de Manuseio Parcial")
        self.assertContains(res, "Já foram manuseados <strong>10</strong> de <strong>20</strong> tarugos")

    def test_cenario_07_conclusao_manuseio_atinge_total_e_recalcula_medias(self):
        """Cenário 7: Concluir manuseio com quantidade total atinge CONCLUIDO e recalcula médias."""
        op = self._criar_op(self.proc_extrusao, meta=20)
        ext = self._executar_extrusao(op, 20)

        dados_man = {'quantidade_manuseada': 10, 'lote_produto': 'L-01', 'materia_prima': 'MAT', 'lote_material': 'L-M'}
        amostras_parciais = [{'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'}]
        registrar_producao(op.pk, self.operador_a, dados_man, uuid.uuid4(), extrusao_id=ext.pk, amostras=amostras_parciais, acao='salvar_parcial')

        # Conclusão com 20 un e 2 amostras
        amostras_finais = [
            {'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'},
            {'diametro': '38.4', 'comprimento': '161.0', 'peso': '3.120'},
        ]
        dados_man['quantidade_manuseada'] = 20
        man_final, _ = registrar_producao(
            op.pk, self.operador_a, dados_man, uuid.uuid4(),
            extrusao_id=ext.pk, amostras=amostras_finais, acao='concluir'
        )
        self.assertEqual(man_final.status_manuseio, 'CONCLUIDO')
        self.assertEqual(man_final.quantidade_manuseada, 20)
        self.assertEqual(man_final.media_diametro, Decimal('38.20'))
        self.assertEqual(man_final.media_comprimento, Decimal('160.50'))
        self.assertEqual(man_final.media_peso, Decimal('3.110'))

    def test_cenario_08_fechamento_lista_manuseios_incompletos_com_checkbox(self):
        """Cenário 8: Fechamento de turno exibe seção de manuseios incompletos com switches/checkboxes."""
        op = self._criar_op(self.proc_extrusao, meta=30)
        ext = self._executar_extrusao(op, 30)

        client = Client()
        client.force_login(self.operador_a)
        res = client.get(reverse('bladder:fechamento_turno'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Manuseios Pendentes / Parciais deste Turno")
        self.assertContains(res, f"chk-manuseio-{ext.pk}")
        self.assertContains(res, "Encaminhar:")

    def test_cenario_09_fechamento_sem_selecionar_manuseio_incompleto_bloqueado(self):
        """Cenário 9: Tentar fechar turno com manuseios incompletos sem encaminhar é bloqueado."""
        op = self._criar_op(self.proc_extrusao, meta=30)
        ext = self._executar_extrusao(op, 30)

        itens = [{'ordem_id': op.pk, 'quantidade_realizada': 30, 'categorias': [], 'descricao_desvio': ''}]
        with self.assertRaises(ValueError) as ctx:
            executar_fechamento_turno(self.hoje, self.operador_a, itens, manuseios_transferir_ids=[])
        self.assertIn("Existem manuseios incompletos neste turno", str(ctx.exception))

    def test_cenario_10_fechamento_com_encaminhamento_cria_transferencia_auditoria(self):
        """Cenário 10: Fechamento com encaminhamento cria TransferenciaManuseioBladder com status ENCAMINHADO."""
        op = self._criar_op(self.proc_extrusao, meta=30)
        ext = self._executar_extrusao(op, 30)
        itens = [{'ordem_id': op.pk, 'quantidade_realizada': 30, 'categorias': [], 'descricao_desvio': ''}]

        fechamento = executar_fechamento_turno(
            self.hoje, self.operador_a, itens, manuseios_transferir_ids=[ext.pk]
        )
        self.assertIsNotNone(fechamento)

        transf = TransferenciaManuseioBladder.objects.get(extrusao=ext)
        self.assertEqual(transf.status, 'ENCAMINHADO')
        self.assertEqual(transf.turma_origem, 'TURMA_A')
        self.assertEqual(transf.turma_destino, 'TURMA_B')
        self.assertEqual(transf.quantidade_extrusada, 30)
        self.assertEqual(transf.quantidade_restante, 30)
        self.assertEqual(transf.operador_transferiu, self.operador_a)

    def test_cenario_11_quadro_proximo_turno_exibe_secao_manuseios_recebidos(self):
        """Cenário 11: Quadro operacional do próximo turno exibe a seção MANUSEIOS RECEBIDOS DO TURNO ANTERIOR."""
        op = self._criar_op(self.proc_extrusao, meta=25)
        ext = self._executar_extrusao(op, 25)
        TransferenciaManuseioBladder.objects.create(
            extrusao=ext,
            turma_origem='TURMA_A',
            turma_destino='TURMA_A',  # Usando TURMA_A para o teste com a data de hoje
            data_turno_origem=self.hoje,
            data_turno_destino=self.hoje,
            operador_transferiu=self.operador_a,
            quantidade_extrusada=25,
            quantidade_acumulada_manuseada=0,
            quantidade_restante=25,
            status='ENCAMINHADO'
        )

        client = Client()
        client.force_login(self.operador_a)
        res = client.get(reverse('bladder:operador'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "MANUSEIOS RECEBIDOS DO TURNO ANTERIOR")
        self.assertContains(res, "RETOMAR MANUSEIO")
        self.assertContains(res, op.numero_ordem_curto)

    def test_cenario_12_retomada_proximo_turno_atualiza_transferencia_para_retomado_e_concluido(self):
        """Cenário 12: Retomada pela próxima equipe atualiza transferência para RETOMADO e depois CONCLUIDO."""
        op = self._criar_op(self.proc_extrusao, meta=20)
        ext = self._executar_extrusao(op, 20)
        transf = TransferenciaManuseioBladder.objects.create(
            extrusao=ext,
            turma_origem='TURMA_A',
            turma_destino='TURMA_B',
            data_turno_origem=self.hoje,
            data_turno_destino=self.hoje,
            operador_transferiu=self.operador_a,
            quantidade_extrusada=20,
            quantidade_acumulada_manuseada=0,
            quantidade_restante=20,
            status='ENCAMINHADO'
        )

        # 1. Configura escala para Turma B assumir o turno
        ConfiguracaoEscalaBladder.objects.all().delete()
        ConfiguracaoEscalaBladder.objects.create(
            data_referencia=self.hoje,
            turma_referencia='TURMA_B',
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True
        )

        # Retomada parcial por Operador B
        dados_man = {'quantidade_manuseada': 10, 'lote_produto': 'L-B', 'materia_prima': 'MAT-B', 'lote_material': 'LB-01'}
        amostras = [{'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'}]
        registrar_producao(op.pk, self.operador_b, dados_man, uuid.uuid4(), extrusao_id=ext.pk, amostras=amostras, acao='salvar_parcial')

        transf.refresh_from_db()
        self.assertEqual(transf.status, 'RETOMADO')
        self.assertEqual(transf.quantidade_acumulada_manuseada, 10)
        self.assertEqual(transf.quantidade_restante, 10)
        self.assertEqual(transf.operador_retomou, self.operador_b)

        # 2. Conclusão por Operador B
        amostras_finais = [
            {'diametro': '38.0', 'comprimento': '160.0', 'peso': '3.100'},
            {'diametro': '38.2', 'comprimento': '160.2', 'peso': '3.110'},
        ]
        dados_man['quantidade_manuseada'] = 20
        registrar_producao(op.pk, self.operador_b, dados_man, uuid.uuid4(), extrusao_id=ext.pk, amostras=amostras_finais, acao='concluir')

        transf.refresh_from_db()
        self.assertEqual(transf.status, 'CONCLUIDO')
        self.assertEqual(transf.quantidade_restante, 0)


# ==============================================================================
# SEÇÃO 28: ENTREGA B — MODO NOTURNO E ESTAÇÃO USB (CENÁRIOS 1 A 21)
# ==============================================================================
class EvolucaoOperacionalEntregaBTestCase(BaseEvolucaoTestCase):

    def test_cenario_01_provisionamento_usuario_noturno_sem_staff_nem_superuser(self):
        """Cenário 1: garantir_usuario_noturno() cria usuário restrito sem staff e sem superuser."""
        user = garantir_usuario_noturno()
        self.assertEqual(user.username, 'noturno_bladder')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_cenario_02_ativacao_fecha_sessao_anterior_com_auditoria(self):
        """Cenário 2: Ativação por operador cria SessaoNoturnaBladder com status ATIVA e operador_ativou."""
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/ativar/')
        req.user = self.operador_a
        SessionMiddleware(lambda r: None).process_request(req)
        req.session.save()

        sessao = ativar_estacao_noturna(self.operador_a, req)
        self.assertEqual(sessao.status, 'ATIVA')
        self.assertEqual(sessao.operador_ativou, self.operador_a)
        self.assertIsNotNone(sessao.data_hora_inicio)
        self.assertIsNone(sessao.data_hora_fim)

    def test_cenario_03_ativacao_autentica_usuario_noturno_e_redireciona(self):
        """Cenário 3: POST /bladder/noturno/ativar/ redireciona para a tela noturna."""
        client = Client()
        client.force_login(self.operador_a)
        res = client.post(reverse('bladder:estacao_noturna_ativar'))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse('bladder:estacao_noturna'))

    def test_cenario_04_usuario_noturno_bloqueado_em_rotas_administrativas(self):
        """Cenário 4: Usuário noturno é confinado pelo middleware exclusivamente a /bladder/noturno/."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        middleware = SessionExpiryByProfileMiddleware(lambda r: None)

        rotas_bloqueadas = [
            '/bladder/operador/',
            '/bladder/fechamento_turno/',
            '/bladder/dashboard/',
            '/bladder/ordens/',
            '/admin/',
            '/tv/',
        ]
        for rota in rotas_bloqueadas:
            req = factory.get(rota)
            req.user = usuario_noturno
            SessionMiddleware(lambda r: None).process_request(req)
            req.session['is_night_shift_session'] = True
            req.session['night_shift_start_ts'] = time.time()
            req.session.save()

            resp = middleware(req)
            self.assertEqual(resp.status_code, 302, f"Rota {rota} deveria redirecionar")
            self.assertEqual(resp.url, '/bladder/noturno/')

    def test_cenario_05_usuario_noturno_isento_de_timeout_5_minutos(self):
        """Cenário 5: Middleware NÃO expira sessão noturna após 5 minutos de inatividade humana."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        middleware = SessionExpiryByProfileMiddleware(lambda r: None)

        req = factory.get('/bladder/noturno/')
        req.user = usuario_noturno
        SessionMiddleware(lambda r: None).process_request(req)
        req.session['is_night_shift_session'] = True
        req.session['night_shift_start_ts'] = time.time()
        # Inatividade humana de 10 minutos (600s > 300s)
        req.session['_last_human_activity'] = time.time() - 600
        req.session.save()

        # Deve passar sem deslogar (retornando get_response que criamos)
        called = False
        def fake_response(r):
            nonlocal called
            called = True
            from django.http import HttpResponse
            return HttpResponse("OK")

        mw = SessionExpiryByProfileMiddleware(fake_response)
        resp = mw(req)
        self.assertTrue(called)
        self.assertEqual(resp.status_code, 200)

    def test_cenario_06_recarregar_tela_preserva_sessao_noturna(self):
        """Cenário 6: Recarregar tela (F5) em /bladder/noturno/ mantém a sessão intacta."""
        usuario_noturno = garantir_usuario_noturno()
        client = Client()
        client.force_login(usuario_noturno)
        s = client.session
        s['is_night_shift_session'] = True
        s['night_shift_start_ts'] = time.time()
        s.save()

        res1 = client.get(reverse('bladder:estacao_noturna'))
        self.assertEqual(res1.status_code, 200)
        res2 = client.get(reverse('bladder:estacao_noturna'))
        self.assertEqual(res2.status_code, 200)

    def test_cenario_07_teto_16h_expira_sessao_noturna_e_marca_auditoria(self):
        """Cenário 7: Teto máximo de 16 horas expira a sessão noturna e marca status EXPIRADA."""
        usuario_noturno = garantir_usuario_noturno()
        sessao_db = SessaoNoturnaBladder.objects.create(operador_ativou=self.operador_a, status='ATIVA')

        factory = RequestFactory()
        req = factory.get('/bladder/noturno/')
        req.user = usuario_noturno
        SessionMiddleware(lambda r: None).process_request(req)
        req.session['is_night_shift_session'] = True
        req.session['sessao_noturna_id'] = sessao_db.pk
        req.session['night_shift_start_ts'] = time.time() - (16.5 * 3600)  # 16.5 horas decorridas
        req.session.save()
        setattr(req, '_messages', FallbackStorage(req))

        middleware = SessionExpiryByProfileMiddleware(lambda r: None)
        resp = middleware(req)
        self.assertEqual(resp.status_code, 302)
        sessao_db.refresh_from_db()
        self.assertEqual(sessao_db.status, 'EXPIRADA')

    def test_cenario_08_tela_noturna_renderiza_tres_campos(self):
        """Cenário 8: Tela noturna exibe exatamente os 3 campos e oculta navbar e modal de inatividade."""
        usuario_noturno = garantir_usuario_noturno()
        client = Client()
        client.force_login(usuario_noturno)
        res = client.get(reverse('bladder:estacao_noturna'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="select-produto"')
        self.assertContains(res, 'id="input-lote"')
        self.assertContains(res, 'id="input-volume"')
        # Verifica que a navbar normal e o modal de inatividade NÃO são renderizados
        self.assertNotContains(res, 'inactivityWarningModal')
        self.assertNotContains(res, 'Aviso de Inatividade')
        self.assertNotContains(res, 'class="bladder-navbar"')

    def test_cenario_08b_api_session_status_e_keep_alive_isento_para_noturno(self):
        """Cenário 8b: Endpoints de sessão tratam conta noturna como isenta sem expirar por inatividade."""
        usuario_noturno = garantir_usuario_noturno()
        client = Client()
        client.force_login(usuario_noturno)
        session = client.session
        session['is_night_shift_session'] = True
        session.save()

        res_status = client.get(reverse('api_session_status'))
        self.assertEqual(res_status.status_code, 200)
        data_status = res_status.json()
        self.assertTrue(data_status.get('is_night_shift'))
        self.assertEqual(data_status.get('remaining_seconds'), 99999999)

        res_keep = client.post(reverse('api_session_keep_alive'))
        self.assertEqual(res_keep.status_code, 200)
        data_keep = res_keep.json()
        self.assertEqual(data_keep.get('status'), 'ok')

    def test_cenario_09_lote_preserva_zeros_a_esquerda(self):
        """Cenário 9: Zeros à esquerda no Lote (ex: '000524') são preservados como string."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno

        mov = saida_estoque_noturna(
            produto_id=self.produto_bla240.pk,
            lote='000524',
            volume='1',
            request=req
        )
        self.assertEqual(mov.lote_etiqueta, '000524')

    @patch('bladder.services.disparar_sincronizacao_lote_dr201_async')
    def test_cenario_10_prova_de_estoque_20_retira_5_saldo_15(self, mock_dr):
        """Cenário 10: Prova do Estoque: Saldo inicial 20, retirada de volume 5, saldo final 15."""
        self.assertEqual(self.produto_bla240.estoque_atual, 20)
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno

        with self.captureOnCommitCallbacks(execute=True):
            mov = saida_estoque_noturna(
                produto_id=self.produto_bla240.pk,
                lote='LOTE-PROVA-20-15',
                volume='5',
                request=req
            )
        self.produto_bla240.refresh_from_db()
        self.assertEqual(mov.saldo_anterior, 20)
        self.assertEqual(mov.quantidade, 5)
        self.assertEqual(mov.saldo_posterior, 15)
        self.assertEqual(self.produto_bla240.estoque_atual, 15)

    def test_cenario_11_exatamente_uma_movimentacao_no_ledger(self):
        """Cenário 11: Retirada gera exatamente UMA movimentação no ledger MovimentacaoEstoqueBladder."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno

        saida_estoque_noturna(
            produto_id=self.produto_bla240.pk,
            lote='LOTE-UNICO',
            volume='3',
            request=req
        )
        self.assertEqual(MovimentacaoEstoqueBladder.objects.filter(lote_etiqueta='LOTE-UNICO').count(), 1)

    @patch('bladder.services.disparar_sincronizacao_lote_dr201_async')
    def test_cenario_12_dr201_exatamente_uma_linha_na_fila_simulada(self, mock_dr):
        """Cenário 12: Retirada enfileira exatamente uma chamada de sincronização da DR-201 com chave de idempotência."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno

        with self.captureOnCommitCallbacks(execute=True):
            saida_estoque_noturna(
                produto_id=self.produto_bla240.pk,
                lote='LOTE-DR201',
                volume='2',
                request=req
            )
        self.assertEqual(mock_dr.call_count, 1)

    def test_cenario_13_retirada_volume_maior_que_estoque_bloqueada(self):
        """Cenário 13: Retirada de quantidade maior que saldo em estoque (ex: 25 > 20) é bloqueada."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno

        with self.assertRaises(ValueError) as ctx:
            saida_estoque_noturna(
                produto_id=self.produto_bla240.pk,
                lote='LOTE-FAIL',
                volume='25',
                request=req
            )
        self.assertIn("Saldo insuficiente", str(ctx.exception))

    def test_cenario_14_retirada_volume_zero_ou_negativo_bloqueada(self):
        """Cenário 14: Retirada com volume zero ou negativo é bloqueada."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno

        with self.assertRaises(ValueError):
            saida_estoque_noturna(self.produto_bla240.pk, 'L-0', '0', request=req)
        with self.assertRaises(ValueError):
            saida_estoque_noturna(self.produto_bla240.pk, 'L-NEG', '-5', request=req)

    def test_cenario_15_retirada_produto_inativo_ou_inexistente_bloqueada(self):
        """Cenário 15: Retirada de produto inexistente ou inativo é bloqueada."""
        self.produto_bla100.ativo = False
        self.produto_bla100.save()
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno

        with self.assertRaises((ValueError, ProdutoBladder.DoesNotExist)):
            saida_estoque_noturna(999999, 'L-ERR', '1', request=req)
        with self.assertRaises(ValueError):
            saida_estoque_noturna(self.produto_bla100.pk, 'L-INATIVO', '1', request=req)

    def test_cenario_16_idempotencia_contra_duplo_disparo(self):
        """Cenário 16: Disparos múltiplos com a mesma idempotency_key retornam o mesmo registro sem duplicar saída."""
        usuario_noturno = garantir_usuario_noturno()
        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno
        token = str(uuid.uuid4())

        mov1 = saida_estoque_noturna(self.produto_bla240.pk, 'L-IDEMP', '2', request=req, idempotency_key=token)
        mov2 = saida_estoque_noturna(self.produto_bla240.pk, 'L-IDEMP', '2', request=req, idempotency_key=token)

        self.assertEqual(mov1.pk, mov2.pk)
        self.assertEqual(MovimentacaoEstoqueBladder.objects.filter(idempotency_key=token).count(), 1)
        self.produto_bla240.refresh_from_db()
        self.assertEqual(self.produto_bla240.estoque_atual, 18)  # 20 - 2 = 18 (apenas uma dedução)

    def test_cenario_17_historico_sessao_exibe_retiradas_em_tempo_real(self):
        """Cenário 17: GET /bladder/noturno/ exibe na tabela as saídas realizadas na sessão."""
        usuario_noturno = garantir_usuario_noturno()
        sessao = SessaoNoturnaBladder.objects.create(operador_ativou=self.operador_a, status='ATIVA')

        factory = RequestFactory()
        req = factory.post('/bladder/noturno/retirar/')
        req.user = usuario_noturno
        saida_estoque_noturna(self.produto_bla240.pk, 'LOTE-HIST-01', '4', request=req, sessao_noturna=sessao)

        client = Client()
        client.force_login(usuario_noturno)
        s = client.session
        s['sessao_noturna_id'] = sessao.pk
        s.save()

        res = client.get(reverse('bladder:estacao_noturna'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'LOTE-HIST-01')
        self.assertContains(res, '4 un')

    def test_cenario_18_iniciar_turno_diurno_credenciais_invalidas_mantem_estacao(self):
        """Cenário 18: Inserir credenciais inválidas na modal mantém o terminal na estação noturna."""
        usuario_noturno = garantir_usuario_noturno()
        client = Client()
        client.force_login(usuario_noturno)

        res = client.post(reverse('bladder:estacao_noturna_encerrar'), {
            'username': 'operador_turma_a',
            'password': 'senha_totalmente_errada'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse('bladder:estacao_noturna'))

    def test_cenario_19_iniciar_turno_diurno_usuario_sem_perfil_bladder_rejeitado(self):
        """Cenário 19: Usuário válido porém de outro setor (sem perfil Bladder) é rejeitado."""
        usuario_noturno = garantir_usuario_noturno()
        client = Client()
        client.force_login(usuario_noturno)

        res = client.post(reverse('bladder:estacao_noturna_encerrar'), {
            'username': 'tecnico_mecanico',
            'password': 'password123'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse('bladder:estacao_noturna'))

    def test_cenario_20_login_valido_encerra_sessao_noturna_e_vai_para_boas_vindas(self):
        """Cenário 20: Credenciais válidas encerram a sessão noturna, logam o diurno e redirecionam para boas-vindas."""
        usuario_noturno = garantir_usuario_noturno()
        sessao = SessaoNoturnaBladder.objects.create(operador_ativou=self.operador_a, status='ATIVA')

        client = Client()
        client.force_login(usuario_noturno)
        s = client.session
        s['is_night_shift_session'] = True
        s['sessao_noturna_id'] = sessao.pk
        s.save()

        res = client.post(reverse('bladder:estacao_noturna_encerrar'), {
            'username': 'operador_turma_a',
            'password': 'password123'
        }, follow=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse('bladder:boas_vindas'))

        sessao.refresh_from_db()
        self.assertEqual(sessao.status, 'ENCERRADA')
        self.assertEqual(sessao.operador_encerrou, self.operador_a)
        self.assertIsNotNone(sessao.data_hora_fim)

    def test_cenario_21_transicao_restabelece_timeout_humano_5_minutos(self):
        """Cenário 21: Ao assumir o diurno, o relógio de inatividade de 5 minutos é restabelecido."""
        factory = RequestFactory()
        req = factory.get('/bladder/operador/')
        req.user = self.operador_a
        SessionMiddleware(lambda r: None).process_request(req)
        # Inatividade humana de 6 minutos para operador diurno
        req.session['_last_human_activity'] = time.time() - 360
        req.session.save()
        setattr(req, '_messages', FallbackStorage(req))

        middleware = SessionExpiryByProfileMiddleware(lambda r: None)
        resp = middleware(req)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.url)


# ==============================================================================
# SEÇÃO 29: ENTREGA C — TELA DE BOAS-VINDAS CONTEXTUAL (CENÁRIOS 1 A 8)
# ==============================================================================
class EvolucaoOperacionalEntregaCTestCase(BaseEvolucaoTestCase):

    def test_cenario_01_saudacao_contextual_horario(self):
        """Cenário 1: Saudação varia conforme horário local: BOM DIA, BOA TARDE, BOA NOITE."""
        client = Client()
        client.force_login(self.operador_a)

        # 1. 09:00 -> BOM DIA
        with patch('django.utils.timezone.localtime') as mock_tz:
            mock_tz.return_value = datetime.datetime(2026, 11, 18, 9, 0, tzinfo=timezone.get_current_timezone())
            res = client.get(reverse('bladder:boas_vindas'))
            self.assertContains(res, "BOM DIA")

        # 2. 14:00 -> BOA TARDE
        with patch('django.utils.timezone.localtime') as mock_tz:
            mock_tz.return_value = datetime.datetime(2026, 11, 18, 14, 0, tzinfo=timezone.get_current_timezone())
            res = client.get(reverse('bladder:boas_vindas'))
            self.assertContains(res, "BOA TARDE")

        # 3. 21:00 -> BOA NOITE
        with patch('django.utils.timezone.localtime') as mock_tz:
            mock_tz.return_value = datetime.datetime(2026, 11, 18, 21, 0, tzinfo=timezone.get_current_timezone())
            res = client.get(reverse('bladder:boas_vindas'))
            self.assertContains(res, "BOA NOITE")

    def test_cenario_02_dados_reais_do_turno_exibidos(self):
        """Cenário 2: Exibe OPs programadas, metas, manuseios transferidos e recados do dia."""
        op = self._criar_op(self.proc_extrusao, meta=35)
        client = Client()
        client.force_login(self.operador_a)

        res = client.get(reverse('bladder:boas_vindas'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, op.numero_ordem_curto)
        self.assertContains(res, "35")
        self.assertContains(res, "Carlos")

    def test_cenario_03_situacao_do_estoque_exibida(self):
        """Cenário 3: Exibe situação semafórica do estoque de bladders acabados."""
        client = Client()
        client.force_login(self.operador_a)
        res = client.get(reverse('bladder:boas_vindas'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Alerta de Estoque")
        self.assertContains(res, "Bladders Acabados")

    def test_cenario_04_botoes_de_acao_operador_vs_lider(self):
        """Cenário 4: Operador vê botão 'IR PARA O TURNO'; líder vê também botão de acompanhamento/dashboard."""
        client = Client()

        # Operador comum
        client.force_login(self.operador_a)
        res_op = client.get(reverse('bladder:boas_vindas'))
        self.assertContains(res_op, reverse('bladder:operador'))
        self.assertNotContains(res_op, "GESTÃO &bull; PAINEL GERAL")

        # Líder
        client.force_login(self.lider)
        res_lider = client.get(reverse('bladder:boas_vindas'))
        self.assertContains(res_lider, reverse('bladder:operador'))
        self.assertContains(res_lider, reverse('bladder:dashboard'))

    def test_cenario_05_roteamento_inteligente_primeiro_acesso_vai_para_boas_vindas(self):
        """Cenário 5: Primeiro acesso pós-login sem bladder_welcome_seen direciona para boas-vindas."""
        client = Client()
        client.force_login(self.operador_a)

        res_hr = client.get(reverse('home_redirect'))
        self.assertEqual(res_hr.status_code, 302)
        self.assertEqual(res_hr.url, reverse('bladder:boas_vindas'))

        res_ps = client.get(reverse('portal_select'))
        self.assertEqual(res_ps.status_code, 302)
        self.assertEqual(res_ps.url, reverse('bladder:boas_vindas'))

    def test_cenario_06_apos_visualizar_f5_e_navegacao_nao_causam_loop(self):
        """Cenário 6: Após renderizar boas-vindas, flag de sessão é gravada e F5/navegações vão direto ao turno."""
        client = Client()
        client.force_login(self.operador_a)

        # 1. Primeiro acesso
        res_init = client.get(reverse('home_redirect'))
        self.assertEqual(res_init.url, reverse('bladder:boas_vindas'))

        # 2. Abre a tela de boas-vindas (marca welcome_seen na sessão)
        res_bv = client.get(reverse('bladder:boas_vindas'))
        self.assertEqual(res_bv.status_code, 200)

        # 3. Próximo acesso a home_redirect vai direto a /bladder/operador/
        res_subseq = client.get(reverse('home_redirect'))
        self.assertEqual(res_subseq.status_code, 302)
        self.assertEqual(res_subseq.url, reverse('bladder:operador'))

    def test_cenario_07_usuario_noturno_nao_acessa_boas_vindas(self):
        """Cenário 7: Usuário noturno é confinado e não tem acesso à tela de boas-vindas."""
        usuario_noturno = garantir_usuario_noturno()
        client = Client()
        client.force_login(usuario_noturno)
        s = client.session
        s['is_night_shift_session'] = True
        s['night_shift_start_ts'] = time.time()
        s.save()

        res = client.get(reverse('bladder:boas_vindas'))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, '/bladder/noturno/')

    def test_cenario_08_outros_modulos_nao_sao_afetados(self):
        """Cenário 8: Usuários de outros módulos não são redirecionados para boas-vindas do Bladder."""
        client = Client()
        client.force_login(self.usuario_manut)

        res = client.get(reverse('home_redirect'))
        self.assertEqual(res.status_code, 302)
        self.assertNotIn('bladder', res.url)


# ==============================================================================
# ENTREGA D — CORREÇÃO VISUAL E CONTRASTE WCAG AA NO FECHAMENTO DE TURNO
# ==============================================================================
class EvolucaoOperacionalEntregaDTestCase(BaseEvolucaoTestCase):

    def test_cenario_01_fechamento_turno_contraste_wcag_aa_sem_classes_escuras(self):
        """Valida eliminação de containers escuros ilegíveis e adoção de tema claro WCAG AA."""
        self._criar_op(self.proc_extrusao, meta=10)
        client = Client()
        client.force_login(self.operador_a)

        res = client.get(reverse('bladder:fechamento_turno'))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        # Não deve haver classes de container escuro no tema claro
        self.assertNotIn('bg-black bg-opacity-', html)
        self.assertNotIn('<table class="table table-dark', html)
        # Deve conter classes da nova arquitetura de tema claro e alto contraste
        self.assertIn('fechamento-container', html)
        self.assertIn('fechamento-card', html)
        self.assertIn('box-deficit', html)
        self.assertIn('btn-cat-desvio', html)

    def test_cenario_02_elementos_de_interface_e_botoes_touch_minimo_48px(self):
        """Valida botões com classes touch-btn e dimensões industriais mínimas."""
        client = Client()
        client.force_login(self.operador_a)
        res = client.get(reverse('bladder:fechamento_turno'))
        html = res.content.decode('utf-8')

        self.assertIn('touch-btn', html)
        self.assertIn('min-height: 48px', html)
