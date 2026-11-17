"""Consulta do líder: período real, filtros, paginação, exportação e autorização."""

import io
import datetime
import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from .models import (
    AmostraManuseioBladder,
    ApontamentoTurnoBladder,
    HistoricoApontamentoBladder,
    OrdemProducaoBladder,
)
from .test_apontamentos_producao import preparar_fixtures
from .producao import registrar_producao
from .services import executar_fechamento_turno


class AcompanhamentoLiderTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        preparar_fixtures(cls)

    def setUp(self):
        self.client.force_login(self.lider)

    def op(self, codigo='01'):
        return OrdemProducaoBladder.objects.create(
            numero_ordem=f'OP-CONS-{uuid.uuid4().hex[:10]}', processo=self.processos[codigo],
            produto=self.produto, data_programada=self.hoje, turma_prevista='TURMA_A',
            quantidade_nova=30, quantidade_planejada=30, criado_por=self.lider,
        )

    def apontar(self, op, condicao='Bom'):
        return registrar_producao(op.pk, self.operador, {
            'tempo_vulcanizacao': '120', 'pressao': '10', 'condicao': condicao,
            'lote_produto': '000123', 'volume': '00001',
        }, uuid.uuid4())[0]

    def test_data_do_registro_e_op_filtrada_sem_depender_da_programacao(self):
        op = self.op()
        registro = self.apontar(op)
        op.data_programada = self.hoje - datetime.timedelta(days=3)
        op.save(update_fields=['data_programada'])
        outra_op = self.op('02')
        self.apontar(outra_op)
        resposta = self.client.get(reverse('bladder:dashboard'), {'op': op.numero_ordem})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['total_registros_producao'], 1)
        self.assertEqual(resposta.context['pagina_registros'][0].pk, registro.pk)
        self.assertContains(resposta, 'Ver detalhes')
        self.assertContains(resposta, 'Exportar Excel')

    def test_legado_fica_identificado_e_fora_da_consulta_padrao(self):
        op = self.op()
        self.apontar(op)
        ApontamentoTurnoBladder.objects.create(
            origem='LEGADO', ordem=op, operador=self.operador, turma='TURMA_A',
            data_turno=self.hoje, data_hora_inicio=timezone.now(), quantidade_realizada=30,
        )
        url = reverse('bladder:dashboard')
        self.assertEqual(self.client.get(url).context['total_registros_producao'], 1)
        resposta = self.client.get(url, {'incluir_legados': 'on'})
        self.assertEqual(resposta.context['total_registros_producao'], 2)
        self.assertContains(resposta, 'Legado')
        self.assertEqual(self.client.get(url, {'incluir_legados': 'on', 'processo': '01'}).context['total_registros_producao'], 1)

    def test_link_da_op_abre_todo_o_historico_mesmo_em_ano_anterior(self):
        op = self.op()
        registro = self.apontar(op)
        data_antiga = self.hoje - datetime.timedelta(days=400)
        ApontamentoTurnoBladder.objects.filter(pk=registro.pk).update(data_turno=data_antiga)
        resposta = self.client.get(reverse('bladder:dashboard'), {'op': op.numero_ordem, 'periodo': 'op'})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['total_registros_producao'], 1)
        self.assertEqual(resposta.context['filtro_producao'].cleaned_data['data_inicial'], data_antiga)
        self.assertEqual(self.client.get(reverse('bladder:acompanhamento_exportar_excel'), {'op': op.numero_ordem, 'periodo': 'op'}).status_code, 200)

    def test_condicao_e_fechamento_distinguem_registros(self):
        op = self.op()
        self.apontar(op, 'Bom')
        self.apontar(op, 'Lixo')
        url = reverse('bladder:dashboard')
        self.assertEqual(self.client.get(url, {'condicao': 'Lixo'}).context['total_registros_producao'], 1)
        self.assertEqual(self.client.get(url, {'fechamento': 'ABERTO'}).context['total_registros_producao'], 2)
        executar_fechamento_turno(self.hoje, self.operador, [{
            'ordem_id': op.pk, 'quantidade_realizada': 2,
            'categorias': [self.categoria.pk], 'descricao_desvio': 'Equipamento indisponível',
        }])
        self.assertEqual(self.client.get(url, {'fechamento': 'ABERTO'}).context['total_registros_producao'], 0)
        self.assertEqual(self.client.get(url, {'fechamento': 'FECHADO'}).context['total_registros_producao'], 2)

    def test_exportacao_usa_todos_os_resultados_e_preserva_amostras_e_correcoes(self):
        op = self.op()
        registros = [self.apontar(op) for _ in range(21)]
        ApontamentoTurnoBladder.objects.filter(pk=registros[0].pk).update(observacoes='=1+1')
        HistoricoApontamentoBladder.objects.create(
            apontamento=registros[0], quantidade_anterior=1, quantidade_nova=1,
            usuario=self.lider, motivo_correcao='Correção de parâmetro',
            valores_anteriores={'pressao': '10'}, valores_novos={'pressao': '11'},
        )
        extrusao_op = self.op('03')
        fonte = registrar_producao(extrusao_op.pk, self.operador, {
            'quantidade_realizada': 10, 'temperatura': '90', 'velocidade_esteira': '2',
            'velocidade_fuso': '35', 'temperatura_tcu_1': '50', 'temperatura_tcu_2': '50',
            'temperatura_tcu_3': '50', 'temperatura_tcu_4': '50',
        }, uuid.uuid4())[0]
        manuseio = registrar_producao(extrusao_op.pk, self.operador, {
            'lote_produto': '000123', 'materia_prima': 'Composto', 'lote_material': '000999',
        }, uuid.uuid4(), extrusao_id=fonte.pk, amostras=[{'diametro': '38', 'comprimento': '160', 'peso': '3'}])[0]
        self.assertTrue(AmostraManuseioBladder.objects.filter(apontamento=manuseio).exists())
        tela = self.client.get(reverse('bladder:dashboard'))
        self.assertEqual(len(tela.context['pagina_registros']), 20)
        resposta = self.client.get(reverse('bladder:acompanhamento_exportar_excel'))
        self.assertEqual(resposta.status_code, 200)
        workbook = load_workbook(io.BytesIO(resposta.content), read_only=True)
        self.assertEqual(workbook.sheetnames, ['Consulta', 'Registros', 'Amostras', 'Correções'])
        linhas = list(workbook['Registros'].values)
        self.assertEqual(len(linhas), 24)
        por_id = {linha[0]: linha for linha in linhas[1:]}
        self.assertEqual(por_id[registros[0].pk][19], "'=1+1")
        self.assertEqual(por_id[fonte.pk][10], 10)
        self.assertIsNone(por_id[manuseio.pk][10])
        self.assertEqual(sum(1 for _ in workbook['Amostras'].values), 2)
        self.assertEqual(sum(1 for _ in workbook['Correções'].values), 2)
        filtrado = self.client.get(reverse('bladder:acompanhamento_exportar_excel'), {'processo': '02'})
        self.assertEqual(sum(1 for _ in load_workbook(io.BytesIO(filtrado.content), read_only=True)['Registros'].values), 1)

    def test_periodo_invalido_e_permissao_de_exportacao(self):
        parametros = {'data_inicial': '2026-11-17', 'data_final': '2026-11-16'}
        resposta = self.client.get(reverse('bladder:dashboard'), parametros)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'data final deve ser igual ou posterior')
        self.assertEqual(self.client.get(reverse('bladder:acompanhamento_exportar_excel'), parametros).status_code, 400)
        self.client.force_login(self.operador)
        self.assertEqual(self.client.get(reverse('bladder:acompanhamento_exportar_excel')).status_code, 302)
        self.client.force_login(User.objects.create_user(username='externo_consulta'))
        self.assertEqual(self.client.get(reverse('bladder:dashboard')).status_code, 302)
