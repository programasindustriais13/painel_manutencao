"""Cenários A–K: dados de execução, dependências, apuração e segurança."""
import datetime
import io
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from unittest.mock import patch
from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.db import close_old_connections, OperationalError
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from maintenance.models import Machine, Sector
from .models import (ProcessoBladder, ProdutoBladder, OrdemProducaoBladder,
                     ConfiguracaoEscalaBladder, PerfilOperacionalBladder,
                     ApontamentoTurnoBladder, MovimentacaoEstoqueBladder,
                     CategoriaDesvioBladder, SaldoPendenteBladder, AmostraManuseioBladder,
                     HistoricoApontamentoBladder, FuncionarioApoioBladder)
from .producao import registrar_producao, corrigir_producao, manuseios_pendentes
from .forms_producao import formulario_amostras, numero_amostras, formulario_processo
from .services import executar_fechamento_turno, registrar_ou_atualizar_apontamento, corrigir_apontamento_operador_ou_lider, encerrar_op_parcial_ou_total, cancelar_ordem_producao, reprogramar_ordem_producao, criar_ordem_producao_com_saldos


def preparar_fixtures(cls):
    cls.hoje = timezone.localdate()
    cls.operador = User.objects.create_user(username='execucao_operador')
    grupo, _ = Group.objects.get_or_create(name='Operadores Bladder')
    cls.operador.groups.add(grupo)
    PerfilOperacionalBladder.objects.create(usuario=cls.operador, turma='TURMA_A')
    cls.lider = User.objects.create_user(username='execucao_lider')
    cls.lider.groups.add(Group.objects.get_or_create(name='Liderança Bladder')[0])
    ConfiguracaoEscalaBladder.objects.create(data_referencia=cls.hoje, turma_referencia='TURMA_A')
    cls.produto = ProdutoBladder.objects.create(codigo='BLA003', descricao='B240/15', tempo_vulcanizacao_min=120)
    setor = Sector.objects.create(nome='BLADDER execucao')
    cls.processos = {}
    for n in range(1, 7):
        codigo = f'{n:02d}'
        maquina = Machine.objects.create(nome=f'Equipamento {codigo}', setor=setor, criticidade='MEDIA')
        cls.processos[codigo] = ProcessoBladder.objects.create(id=100+n, codigo=codigo, nome=f'Processo {codigo}', maquina=maquina)
    cls.categoria = CategoriaDesvioBladder.objects.create(codigo='TESTE_EXECUCAO', nome='Problema no equipamento')


class ApontamentosProducaoTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        preparar_fixtures(cls)

    def op(self, codigo='01', meta=5):
        return OrdemProducaoBladder.objects.create(numero_ordem=f'OP-BLA-{uuid.uuid4().hex[:12]}',
            processo=self.processos[codigo], produto=self.produto, data_programada=self.hoje,
            turma_prevista='TURMA_A', quantidade_nova=meta, quantidade_planejada=meta, criado_por=self.lider)

    def dados(self, codigo='01', qtd=27):
        if codigo in ('01', '02'):
            return dict(tempo_vulcanizacao='120.5', pressao='10.25', temperatura='190', condicao='Bom', lote_produto='000123', volume='00001')
        if codigo in ('03', '04'):
            return dict(quantidade_realizada=qtd, temperatura='90.5', velocidade_esteira='2.5', velocidade_fuso='35.25',
                        temperatura_tcu_1='50.1', temperatura_tcu_2='50.2', temperatura_tcu_3='50.3', temperatura_tcu_4='50.4',
                        **({'tipo_processamento': 'Material normal', 'resfriamento': 'Tanque de água'} if codigo == '03' else {}))
        if codigo == '05':
            return dict(tempo_vulcanizacao='8.25', temperatura='100.5', pressao='5.5', condicao='Bons', observacoes='Inspeção confirmada')
        return dict(lote_produto='000123', materia_prima='Composto 001', lote_material='000999', observacoes='Amostragem real')

    def registrar(self, op, dados=None, **kwargs):
        return registrar_producao(op.pk, self.operador, dados or self.dados(op.processo.codigo), kwargs.pop('chave', uuid.uuid4()), **kwargs)[0]

    def medidas(self, qtd):
        return [dict(diametro=str(Decimal('38') + Decimal(n % 3)/10), comprimento='160.5', peso='3.125') for n in range(numero_amostras(qtd))]

    def fechar(self, op, qtd):
        return executar_fechamento_turno(self.hoje, self.operador, [dict(ordem_id=op.pk, quantidade_realizada=qtd,
              categorias=[self.categoria.pk], descricao_desvio='Equipamento indisponível no final do turno')])

    def test_a_vulcanizacao_individual_qualidades_sem_estoque(self):
        op = self.op()
        with patch('bladder.services.disparar_sincronizacao_dr201_async') as sync:
            for condicao in ['Bom', 'IA', 'Lixo']:
                dados = self.dados(); dados['condicao'] = condicao
                ap = self.registrar(op, dados)
                self.assertEqual(ap.quantidade_realizada, 1)
            self.assertFalse(sync.called)
        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, 3)
        self.assertEqual(op.apontamentos.count(), 3)
        self.assertEqual(set(op.apontamentos.values_list('condicao', flat=True)), {'Bom','IA','Lixo'})
        self.assertEqual(op.apontamentos.first().lote_produto, '000123')
        self.assertFalse(MovimentacaoEstoqueBladder.objects.exists())

    def test_card_avisa_meta_atingida_e_superada_sem_fechar_op(self):
        op = self.op('01', meta=2)
        self.client.force_login(self.operador)
        self.registrar(op)
        resposta = self.client.get(reverse('bladder:operador'))
        self.assertContains(resposta, 'Faltam <strong>1 un</strong> para a meta.', html=True)
        self.assertNotContains(resposta, 'META ATINGIDA')
        self.registrar(op)
        op.refresh_from_db()
        self.assertEqual(op.status, 'EM_EXECUCAO')
        resposta = self.client.get(reverse('bladder:operador'))
        self.assertContains(resposta, 'META ATINGIDA')
        self.assertContains(resposta, 'A OP permanece aberta até o fechamento do turno.')
        self.assertContains(resposta, 'REGISTRAR PRODUÇÃO')
        self.registrar(op)
        op.refresh_from_db()
        self.assertEqual((op.quantidade_realizada, op.status), (3, 'EM_EXECUCAO'))
        resposta = self.client.get(reverse('bladder:operador'))
        self.assertContains(resposta, 'META SUPERADA')
        self.assertContains(resposta, '+1 un acima da meta.')

    def test_card_nao_fabrica_meta_para_aneis_zero_ou_manuseio_legado(self):
        aneis = self.op('05', meta=2)
        self.registrar(aneis, self.dados('05'))
        self.op('01', meta=0)
        historico_manuseio = self.op('06', meta=2)
        historico_manuseio.quantidade_realizada = 2
        historico_manuseio.save(update_fields=['quantidade_realizada'])
        self.client.force_login(self.operador)
        resposta = self.client.get(reverse('bladder:operador'))
        self.assertContains(resposta, 'Quantidade não apurada')
        self.assertNotContains(resposta, 'META ATINGIDA')
        self.assertNotContains(resposta, 'META SUPERADA')

    def test_b_tempo_pressao_vazios_e_obrigatorios_a_cada_registro(self):
        op = self.op(); self.registrar(op)
        self.client.force_login(self.operador)
        response = self.client.get(reverse('bladder:producao_registrar', args=[op.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['form']['tempo_vulcanizacao'].value())
        self.assertIsNone(response.context['form']['pressao'].value())
        dados=self.dados();dados.pop('tempo_vulcanizacao');dados.pop('pressao')
        with self.assertRaises(ValueError): self.registrar(op,dados)
        self.assertEqual(op.apontamentos.count(),1)

    def test_c_duas_prensas_ids_diferentes_dos_codigos(self):
        ops=[self.op('01'),self.op('02')]
        for op in ops:
            ap=self.registrar(op)
            self.assertEqual(ap.equipamento_id,op.processo.maquina_id)
            self.assertEqual(ap.codigo_processo,op.processo.codigo)
            self.assertEqual(ap.ordem_id,op.pk)
            self.assertNotEqual(ap.processo_registrado_id,int(ap.codigo_processo))

    def test_d_extrusao_real_preserva_meta_e_libera_manuseio(self):
        op=self.op('03',30); ap=self.registrar(op)
        op.refresh_from_db()
        self.assertEqual((op.quantidade_realizada,op.quantidade_planejada),(27,30))
        self.assertEqual(ap.temperatura_tcu_4,Decimal('50.4'))
        self.assertEqual(list(manuseios_pendentes()),[ap])
        self.assertEqual(OrdemProducaoBladder.objects.count(),1)

    def test_e_manuseio_nao_e_liberado_por_programacao_inicio_ou_zero(self):
        op=self.op('03',30)
        self.assertFalse(manuseios_pendentes().exists())
        self.client.force_login(self.operador)
        response=self.client.get(reverse('bladder:manuseio_registrar',args=[99999]))
        self.assertEqual(response.status_code,404)
        legado=registrar_ou_atualizar_apontamento(op.pk,self.operador,0,situacao='EM_ANDAMENTO')
        with self.assertRaises(ValueError): self.registrar(op,self.dados('06'),extrusao_id=legado.pk,amostras=[])
        op6=self.op('06',30)
        with self.assertRaises(ValueError): self.registrar(op6,self.dados('06'))

    def test_f_amostras_30_e_31_medias_e_individuais(self):
        for qtd,n in [(30,3),(31,4)]:
            op=self.op('03',qtd); fonte=self.registrar(op,self.dados('03',qtd))
            medidas=self.medidas(qtd)
            if qtd==30:
                for dados,d in zip(medidas,['38.0','38.2','37.9']):dados['diametro']=d
            ap=self.registrar(op,self.dados('06'),extrusao_id=fonte.pk,amostras=medidas)
            self.assertEqual(ap.amostras.count(),n)
            self.assertEqual(len(formulario_amostras(qtd).forms),n)
            self.assertEqual(ap.media_peso,Decimal('3.125'))
            self.assertEqual(ap.media_comprimento,Decimal('160.50'))
            if qtd==30:self.assertEqual(ap.media_diametro,Decimal('38.03'))
            self.assertFalse(manuseios_pendentes().filter(pk=fonte.pk).exists())
        for qtd,n in [(0,0),(1,1),(10,1),(20,2),(50,5),(100,10)]:self.assertEqual(numero_amostras(qtd),n)

    def test_f_quantidade_e_medias_forjadas_nao_substituem_amostras(self):
        op=self.op('03',30);fonte=self.registrar(op,self.dados('03',30))
        with self.assertRaises(ValueError):self.registrar(op,self.dados('06'),extrusao_id=fonte.pk,amostras=self.medidas(20))
        dados=self.dados('06');dados['media_diametro']='999'
        ap=self.registrar(op,dados,extrusao_id=fonte.pk,amostras=self.medidas(30))
        self.assertEqual(ap.media_diametro,Decimal('38.10'))

    def test_g_extrusoes_parciais_independentes_20_30(self):
        op=self.op('03',50)
        fontes=[self.registrar(op,self.dados('03',q)) for q in [20,30]]
        for fonte in fontes:
            man=self.registrar(op,self.dados('06'),extrusao_id=fonte.pk,amostras=self.medidas(fonte.quantidade_realizada))
            self.assertEqual(man.amostras.count(),fonte.quantidade_realizada//10)
        op.refresh_from_db();self.assertEqual(op.quantidade_realizada,50)
        self.assertEqual(op.apontamentos.filter(origem='PROCESSO').count(),2)
        self.assertEqual(OrdemProducaoBladder.objects.count(),1)

    def test_h_apex_sem_manuseio_ou_op_extra(self):
        op=self.op('04',30);ap=self.registrar(op)
        self.assertEqual(ap.quantidade_realizada,27)
        self.assertFalse(manuseios_pendentes().exists())
        with self.assertRaises(ValueError):self.registrar(op,self.dados('06'),extrusao_id=ap.pk,amostras=self.medidas(27))
        self.assertEqual(OrdemProducaoBladder.objects.count(),1)

    def test_i_aneis_condicoes_confirmadas_sem_quantidade(self):
        op=self.op('05',20)
        for condicao in ['Bons','Parcialmente Bons','Ruins']:
            dados=self.dados('05');dados['condicao']=condicao
            ap=self.registrar(op,dados);self.assertFalse(ap.quantidade_apurada)
            self.assertEqual(ap.condicao,condicao);self.assertEqual(ap.pressao,Decimal('5.5'))
        op.refresh_from_db();self.assertFalse(op.quantidade_apurada);self.assertEqual(op.quantidade_realizada,0)
        self.assertIn('não apurada',ap.quantidade_display)
        dados=self.dados('05');dados['condicao']='IA'
        with self.assertRaises(ValueError):self.registrar(op,dados)

    def test_j_fechamento_apura_sem_segundo_consolidado_e_gera_saldo3(self):
        op=self.op('03',30);ap=self.registrar(op)
        f=self.fechar(op,27)
        self.assertEqual(f.itens.get().quantidade_realizada,27)
        self.assertEqual(op.apontamentos.count(),1)
        ap.refresh_from_db();self.assertEqual(ap.fechamento_id,f.pk)
        self.assertEqual(SaldoPendenteBladder.objects.get().quantidade,3)
        with self.assertRaises(ValueError):self.fechar(op,27)

    def test_j_fechamento_rejeita_total_divergente_e_deficit_sem_motivo(self):
        op=self.op('03',30);self.registrar(op)
        with self.assertRaises(ValueError):self.fechar(op,30)
        with self.assertRaises(ValueError):executar_fechamento_turno(self.hoje,self.operador,[{'ordem_id':op.pk,'quantidade_realizada':27,'categorias':[],'descricao_desvio':''}])
        self.assertFalse(op.itens_fechamento.exists())

    def test_j_sobreproducao_nao_conclui_antes_fechamento(self):
        op=self.op('03',20);self.registrar(op,self.dados('03',22))
        op.refresh_from_db();self.assertEqual(op.status,'EM_EXECUCAO')
        f=self.fechar(op,22);self.assertEqual(f.itens.get().excedente,2)
        self.assertFalse(SaldoPendenteBladder.objects.exists())

    def test_j_fechamento_aneis_nao_inventa_quantidade_ou_ledger(self):
        op=self.op('05',20);self.registrar(op)
        f=self.fechar(op,0);item=f.itens.get()
        self.assertFalse(item.quantidade_apurada)
        self.assertEqual(item.saldo_gerado,0)
        self.assertEqual(op.apontamentos.count(),1)
        self.assertFalse(SaldoPendenteBladder.objects.exists())
        self.client.force_login(self.lider)
        response=self.client.get(reverse('bladder:relatorios'))
        self.assertEqual(response.context['total_programado'],0)
        self.assertContains(response,'sem quantidade apurada')
        response=self.client.get(reverse('bladder:relatorios_exportar_excel'))
        import openpyxl
        wb=openpyxl.load_workbook(io.BytesIO(response.content))
        self.assertIn('Quantidade não apurada',wb.sheetnames)

    def test_j_sem_detalhes_preserva_fechamento_manual_e_historicos(self):
        op=self.op('01',5)
        self.assertFalse(op.exige_execucoes)  # Fixture deliberadamente legada.
        f=self.fechar(op,4)
        ap=op.apontamentos.get();self.assertEqual(ap.origem,'LEGADO')
        self.assertIsNone(ap.tempo_vulcanizacao);self.assertEqual(ap.identificacao_registrada,{})
        self.assertEqual(f.itens.get().quantidade_realizada,4)

    def test_k_idempotencia_por_chave_e_exclusividade_manuseio(self):
        op=self.op('03',30);chave=uuid.uuid4()
        ap=self.registrar(op,chave=chave);repetido=self.registrar(op,chave=chave)
        self.assertEqual(ap.pk,repetido.pk)
        self.registrar(op,self.dados('06'),extrusao_id=ap.pk,amostras=self.medidas(27))
        with self.assertRaises(ValueError):self.registrar(op,self.dados('06'),extrusao_id=ap.pk,amostras=self.medidas(27))
        self.assertEqual(op.apontamentos.count(),2)

    def test_k_contexto_processos_e_numeros_invalidos(self):
        op=self.op()
        for campo,valor in [('pressao','NaN'),('pressao','Infinity'),('pressao','-1'),('tempo_vulcanizacao',''),('tempo_vulcanizacao','1.2345')]:
            dados=self.dados();dados[campo]=valor
            with self.subTest(campo=campo,valor=valor),self.assertRaises(ValueError):self.registrar(op,dados)
        dados=self.dados();dados['velocidade_fuso']='5'
        with self.assertRaises(ValueError):self.registrar(op,dados)

    def test_k_permissoes_turma_inativa_e_apoio_fora_escala(self):
        op=self.op()
        externo=User.objects.create_user(username='externo',is_staff=True)
        with self.assertRaises(PermissionError):registrar_producao(op.pk,externo,self.dados(),uuid.uuid4())
        PerfilOperacionalBladder.objects.filter(usuario=self.operador).update(turma='TURMA_B')
        self.operador=User.objects.get(pk=self.operador.pk)
        with self.assertRaises(PermissionError):self.registrar(op)
        PerfilOperacionalBladder.objects.filter(usuario=self.operador).update(turma='TURMA_A',ativo=False)
        self.operador=User.objects.get(pk=self.operador.pk)
        with self.assertRaises(PermissionError):self.registrar(op)
        apoio=User.objects.create_user(username='apoio')
        FuncionarioApoioBladder.objects.create(usuario=apoio,tipo_escala='DATAS_ESPECIFICAS',datas_especificas='2000-01-01')
        with self.assertRaises(PermissionError):registrar_producao(op.pk,apoio,self.dados(),uuid.uuid4())

    def test_k_csrf_anonimo_op_inexistente_e_token_contextual(self):
        op=self.op();url=reverse('bladder:producao_registrar',args=[op.pk])
        self.assertEqual(self.client.get(url).status_code,302)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.operador)
        self.assertEqual(csrf.post(url,self.dados()).status_code,403)
        self.client.force_login(self.operador)
        self.assertEqual(self.client.get(reverse('bladder:producao_registrar',args=[9999])).status_code,404)
        response=self.client.get(url);token=response.context['form']['token'].value()
        outro=self.op('02')
        response=self.client.post(reverse('bladder:producao_registrar',args=[outro.pk]),{**self.dados('02'),'token':token})
        self.assertContains(response,'outra OP')
        self.assertFalse(ApontamentoTurnoBladder.objects.exists())

    def test_k_post_duplicado_e_identidade_derivada_banco(self):
        op=self.op();self.client.force_login(self.operador)
        url=reverse('bladder:producao_registrar',args=[op.pk]);token=self.client.get(url).context['form']['token'].value()
        dados={**self.dados(),'token':token,'operador':self.lider.pk,'produto':9999,'equipamento':9999}
        self.assertEqual(self.client.post(url,dados).status_code,302)
        self.assertEqual(self.client.post(url,dados).status_code,302)
        ap=op.apontamentos.get();self.assertEqual(ap.operador_id,self.operador.pk)
        self.assertEqual(ap.produto_registrado_id,self.produto.pk)
        self.assertEqual(ap.equipamento_id,op.processo.maquina_id)

    def test_k_correcao_auditada_e_bloqueio_quantidade_com_manuseio(self):
        op=self.op('03',30);ap=self.registrar(op)
        dados=self.dados('03',20)
        corrigir_producao(ap.pk,self.operador,dados,'Erro de digitação')
        ap.refresh_from_db();self.assertEqual(ap.quantidade_realizada,20)
        hist=ap.historico_correcoes.get()
        self.assertEqual(hist.valores_anteriores['quantidade_realizada'],'27')
        self.assertEqual(hist.valores_novos['quantidade_realizada'],'20')
        self.registrar(op,self.dados('06'),extrusao_id=ap.pk,amostras=self.medidas(20))
        with self.assertRaises(ValueError):corrigir_producao(ap.pk,self.operador,self.dados('03',30),'Alterar quantidade')
        dados['temperatura']='101.2'
        corrigir_producao(ap.pk,self.operador,dados,'Parâmetro corrigido')
        self.assertEqual(ap.historico_correcoes.count(),2)

    def test_k_correcao_manuseio_audita_amostras_e_medias(self):
        op=self.op('03',30);ap=self.registrar(op,self.dados('03',30))
        man=self.registrar(op,self.dados('06'),extrusao_id=ap.pk,amostras=self.medidas(30))
        medidas=self.medidas(30);medidas[0]['diametro']='40'
        corrigir_producao(man.pk,self.operador,self.dados('06'),'Medição conferida',amostras=medidas)
        man.refresh_from_db();self.assertEqual(man.media_diametro,Decimal('38.77'))
        hist=man.historico_correcoes.get();self.assertEqual(hist.valores_anteriores['amostras'][0]['diametro'],'38.000')
        self.assertEqual(hist.valores_novos['amostras'][0]['diametro'],'40.000')

    def test_k_fechado_impede_operador_e_lider_corrige_snapshot_ledger(self):
        op=self.op('03',30);ap=self.registrar(op);self.fechar(op,27)
        with self.assertRaises(ValueError):self.registrar(op)
        with self.assertRaises(PermissionError):corrigir_producao(ap.pk,self.operador,self.dados('03',28),'Erro anterior')
        corrigir_producao(ap.pk,self.lider,self.dados('03',28),'Conferência liderança')
        op.refresh_from_db();self.assertEqual(op.quantidade_realizada,28)
        self.assertEqual(op.itens_fechamento.get().quantidade_realizada,28)
        self.assertEqual(SaldoPendenteBladder.objects.get().quantidade,2)

    def test_k_pendencia_incorporada_bloqueia_correcao_quantitativa(self):
        op=self.op('03',30);ap=self.registrar(op);self.fechar(op,27)
        SaldoPendenteBladder.objects.filter(op_origem=op).update(status='INCORPORADO',op_destino=self.op('03',3))
        with self.assertRaises(ValueError):corrigir_producao(ap.pk,self.lider,self.dados('03',28),'Conferência liderança')

    def test_k_rotas_legadas_nao_burlam_parametros_ou_fechamento(self):
        op=self.op();ap=self.registrar(op)
        with self.assertRaises(ValueError):registrar_ou_atualizar_apontamento(op.pk,self.operador,5)
        with self.assertRaises(ValueError):corrigir_apontamento_operador_ou_lider(ap.pk,5,'Burlar',self.operador)
        with self.assertRaises(ValueError):encerrar_op_parcial_ou_total(op.pk,self.lider)
        self.client.force_login(self.operador)
        response=self.client.post(reverse('bladder:operador_apontar',args=[op.pk]),{'quantidade_realizada':100,'situacao':'CONCLUIDA'})
        self.assertEqual(response.url,reverse('bladder:producao_registrar',args=[op.pk]))
        op.refresh_from_db();self.assertEqual(op.quantidade_realizada,1)

    def test_op_com_execucao_preserva_origem_e_nao_some_por_cancelamento(self):
        op=self.op('03',30);self.registrar(op)
        with self.assertRaises(ValueError):cancelar_ordem_producao(op.pk,'Cancelar programação',self.lider)
        with self.assertRaises(ValueError):reprogramar_ordem_producao(op.pk,self.hoje+datetime.timedelta(days=1),'Reprogramar execução',self.lider)
        op.refresh_from_db();self.assertEqual(op.status,'EM_EXECUCAO');self.assertEqual(op.data_programada,self.hoje)

    def test_k_admin_somente_leitura_e_sem_exclusao(self):
        op=self.op();ap=self.registrar(op)
        request=RequestFactory().get('/admin/');request.user=User.objects.create_superuser(username='super_execucao',email='')
        for model,obj in [(ApontamentoTurnoBladder,ap),(OrdemProducaoBladder,op),(HistoricoApontamentoBladder,None),(AmostraManuseioBladder,None)]:
            model_admin=admin.site._registry[model]
            self.assertFalse(model_admin.has_change_permission(request,obj))
            self.assertFalse(model_admin.has_delete_permission(request,obj))

    def test_aneis_sem_produto_e_fechamento_sem_apuracao_permanecem_consultaveis(self):
        op=self.op('05',20);op.produto=None;op.save(update_fields=['produto'])
        ap=self.registrar(op,self.dados('05'))
        self.assertIsNone(ap.produto_registrado)
        self.assertIn('Sem produto',str(op))
        self.fechar(op,0)
        self.client.force_login(self.operador)
        self.assertEqual(self.client.get(reverse('bladder:producao_detalhe',args=[ap.pk])).status_code,200)

    def test_correcao_zerando_saldo_auditada_sem_pendencia_operacional_zero(self):
        op=self.op('03',30);ap=self.registrar(op);self.fechar(op,27)
        corrigir_producao(ap.pk,self.lider,self.dados('03',30),'Conferência final da quantidade')
        item=op.itens_fechamento.get();saldo=SaldoPendenteBladder.objects.get(op_origem=op)
        self.assertEqual(item.saldo_gerado,0);self.assertIsNone(item.motivo)
        self.assertEqual(saldo.status,'CANCELADO');self.assertEqual(saldo.quantidade,0)

    def test_k_manuseio_pendente_continua_no_turno_seguinte(self):
        op=self.op('03',30);ap=self.registrar(op,self.dados('03',30));self.fechar(op,30)
        amanha=self.hoje+datetime.timedelta(days=1)
        outro=User.objects.create_user(username='operador_turno_seguinte');outro.groups.add(Group.objects.get(name='Operadores Bladder'))
        PerfilOperacionalBladder.objects.create(usuario=outro,turma='TURMA_B')
        with patch('bladder.producao.timezone.localdate',return_value=amanha):
            man,_=registrar_producao(op.pk,outro,self.dados('06'),uuid.uuid4(),extrusao_id=ap.pk,amostras=self.medidas(30))
        self.assertEqual(man.extrusao_origem_id,ap.pk)
        self.assertEqual(man.data_turno,amanha)
        op.refresh_from_db();self.assertEqual(op.quantidade_realizada,30)

    def test_formulario_erro_preserva_decimal_e_nao_aceita_classe_errada(self):
        dados=self.dados();dados['pressao']='1,250';dados['tempo_vulcanizacao']=''
        form=formulario_processo('01',dados)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.cleaned_data['pressao'],Decimal('1.250'))
        self.assertIn('value="1.250"', str(form['pressao']))
        self.assertNotIn('value="1,250"', str(form['pressao']))
        form=formulario_processo('01',initial={'pressao':Decimal('1.250')})
        self.assertIn('value="1.250"',str(form['pressao']))

    def test_fechamento_somente_manuseio_de_extrusao_do_turno_anterior(self):
        op = self.op('03', 30)
        fonte = self.registrar(op, self.dados('03', 30))
        self.fechar(op, 30)
        amanha = self.hoje + datetime.timedelta(days=1)
        outro = User.objects.create_user(username='fechamento_manuseio_b')
        outro.groups.add(Group.objects.get(name='Operadores Bladder'))
        PerfilOperacionalBladder.objects.create(usuario=outro, turma='TURMA_B')
        with patch('bladder.producao.timezone.localdate', return_value=amanha):
            manuseio, _ = registrar_producao(op.pk, outro, self.dados('06'), uuid.uuid4(),
                extrusao_id=fonte.pk, amostras=self.medidas(30))
            self.client.force_login(outro)
            url = reverse('bladder:fechamento_turno')
            tela = self.client.get(url)
            self.assertContains(tela, 'CONFIRMAR FECHAMENTO DO TURNO')
            self.assertContains(tela, f'Manuseio #{manuseio.pk}')
            self.assertFalse(tela.context['ordens'].exists())
            with self.assertRaises(PermissionError):
                executar_fechamento_turno(amanha, self.operador, [])
            resposta = self.client.post(url, {})
            self.assertEqual(resposta.status_code, 302)
            manuseio.refresh_from_db()
            self.assertIsNotNone(manuseio.fechamento_id)
            self.assertEqual(manuseio.fechamento.data_turno, amanha)
            self.assertEqual(manuseio.fechamento.itens.count(), 0)
            self.assertEqual(OrdemProducaoBladder.objects.count(), 1)
            op.refresh_from_db()
            self.assertEqual(op.quantidade_realizada, 30)
            with self.assertRaises(ValueError):
                executar_fechamento_turno(amanha, outro, [])

    def test_fechamento_sem_op_nem_manuseio_executado_continua_bloqueado(self):
        with self.assertRaises(ValueError):
            executar_fechamento_turno(self.hoje, self.operador, [])

    def test_fechamento_valida_perfil_ativo_e_apoio_na_escala_no_servico(self):
        op = self.op('03', 30)
        externo = User.objects.create_user(username='fechamento_externo', is_staff=True)
        apoio = User.objects.create_user(username='fechamento_apoio_fora')
        FuncionarioApoioBladder.objects.create(usuario=apoio, tipo_escala='DATAS_ESPECIFICAS', datas_especificas='2000-01-01')
        for usuario in [externo, apoio]:
            with self.subTest(usuario=usuario.username), self.assertRaises(PermissionError):
                executar_fechamento_turno(self.hoje, usuario, [{'ordem_id': op.pk, 'quantidade_realizada': 30}])
        self.operador.is_active = False
        with self.assertRaises(PermissionError):
            executar_fechamento_turno(self.hoje, self.operador, [{'ordem_id': op.pk, 'quantidade_realizada': 30}])
        self.operador.is_active = True
        from .models import AjusteEscalaExcepcionalBladder
        AjusteEscalaExcepcionalBladder.objects.create(data=self.hoje, turma_designada='FOLGA', motivo='Parada geral', criado_por=self.lider)
        with self.assertRaises(PermissionError):
            executar_fechamento_turno(self.hoje, self.operador, [{'ordem_id': op.pk, 'quantidade_realizada': 30}])
        self.assertFalse(op.itens_fechamento.exists())

    def test_fechamento_repete_lock_transitorio_sem_duplicar(self):
        op = self.op('03', 30)
        self.registrar(op, self.dados('03', 30))
        with patch('bladder.producao.serializar_turno', side_effect=[OperationalError('database is locked'), None]) as trava:
            fechamento = self.fechar(op, 30)
        self.assertEqual(trava.call_count, 2)
        self.assertEqual(fechamento.itens.count(), 1)
        self.assertEqual(op.apontamentos.count(), 1)

    def test_op06_sem_extrusao_nao_ganha_execucao_no_fechamento_ou_legado(self):
        op = self.op('06', 5)
        self.client.force_login(self.operador)
        resposta = self.client.post(reverse('bladder:fechamento_turno'), {
            f'qtd_realizada_{op.pk}': '5',
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'extrusão')
        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, 0)
        self.assertFalse(op.apontamentos.exists())
        self.assertFalse(op.itens_fechamento.exists())
        with self.assertRaises(ValueError):
            registrar_ou_atualizar_apontamento(op.pk, self.operador, 5)

    def test_correcao_legada06_nao_cria_producao_mas_historico_pode_ser_reduzido(self):
        op = self.op('06', 5)
        legado = ApontamentoTurnoBladder.objects.create(ordem=op, operador=self.operador,
            turma='TURMA_A', data_turno=self.hoje, data_hora_inicio=timezone.now(), quantidade_realizada=0)
        with self.assertRaises(ValueError):
            corrigir_apontamento_operador_ou_lider(legado.pk, 1, 'Não há extrusão comprovada', self.operador)
        legado.quantidade_realizada = 5
        legado.save(update_fields=['quantidade_realizada'])
        op.quantidade_realizada = 5
        op.save(update_fields=['quantidade_realizada'])
        with self.assertRaises(ValueError):
            corrigir_apontamento_operador_ou_lider(legado.pk, 6, 'Quantidade maior sem origem', self.lider)
        corrigir_apontamento_operador_ou_lider(legado.pk, 4, 'Correção redutora do histórico', self.lider)
        legado.refresh_from_db()
        self.assertEqual(legado.quantidade_realizada, 4)
        self.assertEqual(legado.historico_correcoes.count(), 1)
        fechamento = self.fechar(op, 4)
        self.assertEqual(fechamento.itens.get().quantidade_realizada, 4)

    def test_criacao_oficial_marca_processos_confirmados_e_rejeita_nova_op06(self):
        for codigo in ('01', '02', '03', '04', '05'):
            with self.subTest(codigo=codigo):
                op = criar_ordem_producao_com_saldos(self.processos[codigo], self.produto, self.hoje, 5, usuario=self.lider)
                self.assertTrue(op.exige_execucoes)
        with self.assertRaises(ValueError):
            criar_ordem_producao_com_saldos(self.processos['06'], self.produto, self.hoje, 5, usuario=self.lider)
        self.assertEqual(OrdemProducaoBladder.objects.count(), 5)

    def test_novas_prensas_fecham_somente_unidades_detalhadas(self):
        ops = [criar_ordem_producao_com_saldos(self.processos[codigo], self.produto, self.hoje, 1, usuario=self.lider) for codigo in ('01', '02')]
        itens = [{'ordem_id': op.pk, 'quantidade_realizada': 1} for op in ops]
        with self.assertRaises(ValueError):
            executar_fechamento_turno(self.hoje, self.operador, itens)
        self.assertFalse(ApontamentoTurnoBladder.objects.exists())
        for op in ops:
            self.registrar(op)
        fechamento = executar_fechamento_turno(self.hoje, self.operador, itens)
        self.assertEqual(sum(i.quantidade_realizada for i in fechamento.itens.all()), 2)
        self.assertEqual(ApontamentoTurnoBladder.objects.count(), 2)

    def test_op_marcada_impede_helpers_legados_positivos_e_corrigir_inicio(self):
        op = criar_ordem_producao_com_saldos(self.processos['01'], self.produto, self.hoje, 5, usuario=self.lider)
        inicio = registrar_ou_atualizar_apontamento(op.pk, self.operador, 0, situacao='EM_ANDAMENTO')
        with self.assertRaises(ValueError):
            registrar_ou_atualizar_apontamento(op.pk, self.operador, 5)
        with self.assertRaises(ValueError):
            corrigir_apontamento_operador_ou_lider(inicio.pk, 1, 'Sem parâmetros da unidade', self.operador)
        op.refresh_from_db()
        self.assertEqual(op.quantidade_realizada, 0)
        self.assertEqual(op.apontamentos.count(), 1)

    def test_primeira_execucao_promove_op_legada_sem_apagar_inicio(self):
        op = self.op('01', 5)
        inicio = registrar_ou_atualizar_apontamento(op.pk, self.operador, 0, situacao='EM_ANDAMENTO')
        self.assertFalse(op.exige_execucoes)
        self.registrar(op)
        op.refresh_from_db()
        self.assertTrue(op.exige_execucoes)
        self.assertTrue(op.apontamentos.filter(pk=inicio.pk, origem='LEGADO').exists())
        with self.assertRaises(ValueError):
            self.fechar(op, 5)

    def test_nova_op_http_nao_aceita_rebaixar_marcador_nem_programar06(self):
        self.client.force_login(self.lider)
        dados = {'processo': self.processos['01'].pk, 'produto': self.produto.pk,
                 'data_programada': self.hoje.isoformat(), 'quantidade_nova': 5,
                 'prioridade': 'NORMAL', 'exige_execucoes': 'false'}
        self.assertEqual(self.client.post(reverse('bladder:ordem_nova'), dados).status_code, 302)
        op = OrdemProducaoBladder.objects.get()
        self.assertTrue(op.exige_execucoes)
        self.client.force_login(self.operador)
        tela = self.client.get(reverse('bladder:fechamento_turno'))
        self.assertContains(tela, 'readonly')
        resposta = self.client.post(reverse('bladder:fechamento_turno'), {f'qtd_realizada_{op.pk}': 5, 'exige_execucoes': 'false'})
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(op.apontamentos.exists())
        self.client.force_login(self.lider)
        dados['processo'] = self.processos['06'].pk
        self.assertEqual(self.client.post(reverse('bladder:ordem_nova'), dados).status_code, 200)
        self.assertEqual(OrdemProducaoBladder.objects.count(), 1)

    def test_admin_marca_nova_op_e_oculta_marcador_e_processo06(self):
        request = RequestFactory().post('/admin/bladder/ordemproducaobladder/add/', {'exige_execucoes': False})
        request.user = User.objects.create_superuser(username='admin_marcador', email='')
        model_admin = admin.site._registry[OrdemProducaoBladder]
        form = model_admin.get_form(request)()
        self.assertNotIn('exige_execucoes', form.fields)
        with self.assertRaises(ValidationError):
            form.fields['processo'].clean(self.processos['06'].pk)
        op = OrdemProducaoBladder(numero_ordem='OP-ADMIN-NOVA', processo=self.processos['01'],
            produto=self.produto, data_programada=self.hoje, turma_prevista='TURMA_A',
            quantidade_nova=5, quantidade_planejada=5, criado_por=self.lider)
        model_admin.save_model(request, op, form, change=False)
        self.assertTrue(op.exige_execucoes)

    def test_admin_protege_realizado_status_e_processo06_antes_primeira_execucao(self):
        request = RequestFactory().post('/admin/bladder/ordemproducaobladder/add/')
        request.user = User.objects.create_superuser(username='admin_planejamento', email='')
        model_admin = admin.site._registry[OrdemProducaoBladder]
        form_novo = model_admin.get_form(request)()
        for campo in ('exige_execucoes', 'quantidade_realizada', 'quantidade_apurada', 'status'):
            self.assertNotIn(campo, form_novo.fields)
        op = criar_ordem_producao_com_saldos(self.processos['01'], self.produto, self.hoje, 5, usuario=self.lider)
        form_edicao = model_admin.get_form(request, obj=op)()
        self.assertTrue(model_admin.has_change_permission(request, op))
        self.assertIn('quantidade_nova', form_edicao.fields)
        for campo in ('exige_execucoes', 'quantidade_realizada', 'quantidade_apurada', 'status'):
            self.assertNotIn(campo, form_edicao.fields)
        with self.assertRaises(ValidationError):
            form_edicao.fields['processo'].clean(self.processos['06'].pk)


class ConcorrenciaProducaoTestCase(TransactionTestCase):
    reset_sequences=True

    def setUp(self):
        preparar_fixtures(self)
        self.op=OrdemProducaoBladder.objects.create(numero_ordem='OP-CONCORRENTE',processo=self.processos['03'],produto=self.produto,
                     data_programada=self.hoje,turma_prevista='TURMA_A',quantidade_planejada=30,quantidade_nova=30,criado_por=self.lider)

    def test_requisicoes_simultaneas_mesma_chave_salvam_uma_execucao(self):
        chave=uuid.uuid4();uid=self.operador.pk;oid=self.op.pk
        dados=ApontamentosProducaoTestCase.dados(self,'03',30)
        def gravar():
            close_old_connections()
            try:
                user=User.objects.get(pk=uid)
                return registrar_producao(oid,user,dados,chave)[0].pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(lambda _:gravar(),range(2)))
        self.assertEqual(ids[0],ids[1]);self.assertEqual(ApontamentoTurnoBladder.objects.count(),1)
        self.op.refresh_from_db();self.assertEqual(self.op.quantidade_realizada,30)

    def executar_simultaneamente(self, acoes):
        barreira = Barrier(len(acoes))
        uid = self.operador.pk
        def executar(acao):
            close_old_connections()
            try:
                user = User.objects.get(pk=uid)
                barreira.wait(timeout=10)
                try:
                    return acao(user)
                except ValueError as erro:
                    return str(erro)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(acoes)) as pool:
            return list(pool.map(executar, acoes))

    def test_chaves_distintas_preservam_duas_execucoes_e_total(self):
        oid = self.op.pk
        dados = ApontamentosProducaoTestCase.dados(self, '03', 20)
        chaves = [uuid.uuid4(), uuid.uuid4()]
        resultados = self.executar_simultaneamente([
            lambda user, chave=chave: registrar_producao(oid, user, dados, chave)[0].pk
            for chave in chaves
        ])
        self.assertTrue(all(isinstance(r, int) for r in resultados), resultados)
        self.assertEqual(len(set(resultados)), 2)
        self.op.refresh_from_db()
        self.assertEqual(self.op.quantidade_realizada, 40)
        self.assertEqual(self.op.apontamentos.count(), 2)

    def test_manuseios_simultaneos_chaves_distintas_criam_um_filho(self):
        oid = self.op.pk
        fonte, _ = registrar_producao(oid, self.operador, ApontamentosProducaoTestCase.dados(self, '03', 30), uuid.uuid4())
        dados = ApontamentosProducaoTestCase.dados(self, '06')
        medidas = ApontamentosProducaoTestCase.medidas(self, 30)
        resultados = self.executar_simultaneamente([
            lambda user: registrar_producao(oid, user, dados, uuid.uuid4(), extrusao_id=fonte.pk, amostras=medidas)[0].pk
            for _ in range(2)
        ])
        self.assertEqual(sum(isinstance(r, int) for r in resultados), 1, resultados)
        self.assertEqual(ApontamentoTurnoBladder.objects.filter(extrusao_origem=fonte).count(), 1)
        self.assertEqual(AmostraManuseioBladder.objects.count(), 3)
        self.op.refresh_from_db()
        self.assertEqual(self.op.quantidade_realizada, 30)

    def test_fechamento_simultaneo_ao_registro_nao_duplica_producao(self):
        oid = self.op.pk
        dados = ApontamentosProducaoTestCase.dados(self, '03', 30)
        resultados = self.executar_simultaneamente([
            lambda user: registrar_producao(oid, user, dados, uuid.uuid4())[0].pk,
            lambda user: executar_fechamento_turno(self.hoje, user, [dict(ordem_id=oid, quantidade_realizada=30)]).pk,
        ])
        self.assertTrue(any(isinstance(r, int) for r in resultados), resultados)
        self.op.refresh_from_db()
        self.assertEqual(self.op.quantidade_realizada, 30)
        self.assertEqual(self.op.apontamentos.count(), 1)
        self.assertEqual(self.op.itens_fechamento.count(), 1)
