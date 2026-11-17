"""Integração com DRs isolada: ORM real, Google simulado, sem escrita externa."""
import copy
import io
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms_producao import formulario_processo
from .models import (BloqueioDRBladder, HistoricoApontamentoBladder,
                     SincronizacaoDRBladder, MovimentacaoEstoqueBladder)
from .producao import registrar_producao, corrigir_producao
from .sincronizacao_drs import (DESTINOS, adquirir, enfileirar, processar_pendentes,
                               solicitar_reenvio, _canon)
from . import test_apontamentos_producao as fixtures


class PlanilhaSimulada:
    def __init__(self, destino):
        self.destino = destino
        self.title = DESTINOS[destino]['aba']
        self.row_count = 2000
        self.linhas = [list(DESTINOS[destino]['cabecalhos'])]
        self.appends = 0
        self.updates = 0
        self.timeout = False
        self.rejeitar = False
        self.ao_gravar = None
        self.opcoes = []

    def get(self, intervalo, **kwargs):
        match = re.fullmatch(r'A(\d+):[A-Z]+(\d+)', intervalo)
        return copy.deepcopy(self.linhas[int(match[1])-1:int(match[2])])

    def append_rows(self, linhas, **kwargs):
        self.appends += 1
        self.opcoes.append(kwargs)
        if self.rejeitar:
            raise TimeoutError('Sem confirmação antes da gravação')
        self.linhas.extend(copy.deepcopy(linhas))
        if self.ao_gravar:
            callback, self.ao_gravar = self.ao_gravar, None
            callback()
        if self.timeout:
            raise TimeoutError('Google gravou, mas a resposta foi perdida')
        n = len(self.linhas)
        return {'updates': {'updatedRange': f"'{self.title}'!A{n}:{DESTINOS[self.destino]['fim']}{n}"}}

    def update(self, *, range_name, values, **kwargs):
        self.updates += 1
        self.opcoes.append(kwargs)
        if self.rejeitar:
            raise TimeoutError('Sem confirmação do UPDATE')
        n = int(re.match(r'A(\d+)', range_name)[1])
        self.linhas[n-1] = copy.deepcopy(values[0])
        if self.timeout:
            raise TimeoutError('Resposta do UPDATE perdida')

    def batch_update(self, dados, **kwargs):
        self.updates += 1
        self.opcoes.append(kwargs)
        for item in dados:
            match = re.fullmatch(r'([AS])(\d+):[QU](\d+)', item['range'])
            inicio = 0 if match[1] == 'A' else 18
            valores = copy.deepcopy(item['values'][0])
            self.linhas[int(match[2])-1][inicio:inicio+len(valores)] = valores


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SincronizacaoDRTestCase(TestCase):
    op = fixtures.ApontamentosProducaoTestCase.op
    dados = fixtures.ApontamentosProducaoTestCase.dados
    registrar = fixtures.ApontamentosProducaoTestCase.registrar
    medidas = fixtures.ApontamentosProducaoTestCase.medidas

    @classmethod
    def setUpTestData(cls):
        fixtures.preparar_fixtures(cls)

    def setUp(self):
        self.planilhas = {nome: PlanilhaSimulada(nome) for nome in DESTINOS}

    def rodar(self, avancar=False, **kwargs):
        if avancar:
            SincronizacaoDRBladder.objects.update(proxima_tentativa=None)
        with patch('bladder.sincronizacao_drs._abrir', side_effect=lambda destino: self.planilhas[destino]):
            return processar_pendentes(**kwargs)

    def vulcanizar(self, codigo='01', **campos):
        return self.registrar(self.op(codigo), {**self.dados(codigo), **campos})

    def extrusar(self):
        return self.registrar(self.op('03'), self.dados('03', 20))

    def manusear(self, ap):
        dados = {**self.dados('06'), 'materia_prima': 'TORTUGA - FBB0001', 'lote_material': '000999'}
        return registrar_producao(ap.ordem_id, self.lider, dados, uuid.uuid4(), extrusao_id=ap.pk,
                                  amostras=self.medidas(ap.quantidade_realizada))[0]

    def test_novos_campos_obrigatorios_somente_no_processo_correto(self):
        for codigo, campo in [('01', 'temperatura'), ('02', 'temperatura'),
                               ('03', 'tipo_processamento'), ('03', 'resfriamento')]:
            dados = self.dados(codigo)
            dados.pop(campo)
            form = formulario_processo(codigo, dados)
            self.assertFalse(form.is_valid())
            self.assertIn(campo, form.errors)
        self.assertTrue(formulario_processo('04', self.dados('04')).is_valid())
        self.assertNotIn('tipo_processamento', formulario_processo('04').fields)
        self.assertIn('Imperfeição Aparente', str(formulario_processo('01')['condicao']))

    def test_fila_atomica_e_sem_rede_no_registro(self):
        with patch('gspread.service_account') as rede:
            ap = self.vulcanizar()
            self.assertEqual(ap.sincronizacao_dr.status, 'PENDENTE')
            rede.assert_not_called()
            try:
                with transaction.atomic():
                    self.vulcanizar()
                    raise ValueError('Rollback de produção')
            except ValueError:
                pass
        self.assertEqual(SincronizacaoDRBladder.objects.count(), 1)
        self.assertFalse(MovimentacaoEstoqueBladder.objects.exists())

    def test_dr115_mapeamento_e_zeros_sem_coluna_volume(self):
        for codigo, condicao, esperado in [('01', 'Bom', 'BOM'), ('02', 'IA', 'IMPERFEIÇÕES DE VULCANIZAÇÃO'), ('01', 'Lixo', 'LIXO')]:
            ap = self.vulcanizar(codigo, condicao=condicao, observacoes='=1+1')
            linha = ap.sincronizacao_dr.payload
            self.assertEqual(linha, [timezone.localtime(ap.data_hora_inicio).strftime('%d/%m/%Y %H:%M:%S'),
                'EXECUCAO_OPERADOR', '120.5min', '000123', 'BLA003', f'PRENSA {codigo}', '=1+1', 10.25, 190.0, esperado])
        self.rodar()
        ws = self.planilhas['DR115']
        self.assertEqual(ws.appends, 3)
        self.assertTrue(all(o['value_input_option'] == 'RAW' and o['table_range'] == 'A:J' for o in ws.opcoes))
        self.assertEqual(SincronizacaoDRBladder.objects.filter(status='SINCRONIZADO').count(), 3)
        self.rodar()
        self.assertEqual(ws.appends, 3)

    def test_dr114_aguarda_manuseio_e_usa_operador_da_extrusao(self):
        ap = self.extrusar()
        self.assertEqual(ap.sincronizacao_dr.status, 'AGUARDANDO')
        self.assertEqual(self.rodar(), 0)
        man = self.manusear(ap)
        fila = SincronizacaoDRBladder.objects.get(apontamento=ap)
        self.assertEqual(len(fila.payload), 21)
        self.assertEqual(fila.payload[1:7], ['EXECUCAO_OPERADOR', 'TORTUGA - FBB0001', '000999', '000123', 'BLA003', 'Material normal'])
        self.assertEqual(fila.payload[7:20], [3.125, 160.5, 38.05, 50.1, 50.2, 50.3, 50.4, 90.5, 35.25, 2.5, '', 'Tanque de água', 20])
        self.assertEqual(man.operador, self.lider)
        self.assertEqual(man.controle_dr.pk, fila.pk)
        self.rodar()
        self.assertEqual(self.planilhas['DR114'].appends, 1)
        ap.ordem.refresh_from_db()
        self.assertEqual(ap.ordem.quantidade_realizada, 20)

    def test_fechamento_nao_reenvia_e_parciais_sao_linhas_independentes(self):
        op = self.op('03', 50)
        aps = [self.registrar(op, self.dados('03', q)) for q in [20, 30]]
        for ap in aps:
            self.manusear(ap)
        self.rodar()
        from .services import executar_fechamento_turno
        executar_fechamento_turno(self.hoje, self.operador, [{'ordem_id': op.pk, 'quantidade_realizada': 50}])
        self.rodar()
        self.assertEqual(self.planilhas['DR114'].appends, 2)
        self.assertEqual(SincronizacaoDRBladder.objects.count(), 2)

    def test_erro_antes_da_escrita_tem_retentativa_com_intervalo(self):
        ap = self.vulcanizar()
        with patch('bladder.sincronizacao_drs._abrir', side_effect=FileNotFoundError('credentials.json')):
            processar_pendentes()
        fila = SincronizacaoDRBladder.objects.get(apontamento=ap)
        self.assertEqual(fila.status, 'ERRO')
        self.assertGreater(fila.proxima_tentativa, timezone.now())
        self.assertEqual(self.rodar(), 0)
        self.rodar(avancar=True)
        fila.refresh_from_db()
        self.assertEqual(fila.status, 'SINCRONIZADO')

    def test_cabecalho_divergente_nao_grava_nem_cria_colunas(self):
        self.vulcanizar()
        self.planilhas['DR115'].linhas[0][4] = 'Campo inesperado'
        self.rodar()
        self.assertEqual(self.planilhas['DR115'].appends, 0)
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'ERRO')

    def test_timeout_depois_de_gravar_reconcilia_sem_segundo_append(self):
        ap = self.vulcanizar()
        ws = self.planilhas['DR115']
        ws.timeout = True
        self.rodar()
        fila = SincronizacaoDRBladder.objects.get(apontamento=ap)
        self.assertEqual(fila.status, 'CONFERIR')
        self.rodar(avancar=True)
        fila.refresh_from_db()
        self.assertEqual(fila.status, 'SINCRONIZADO')
        self.assertEqual(ws.appends, 1)

    def test_timeout_sem_linha_exige_conferencia_e_justificativa(self):
        ap = self.vulcanizar()
        ws = self.planilhas['DR115']
        ws.rejeitar = True
        self.rodar()
        self.rodar(avancar=True)
        fila = SincronizacaoDRBladder.objects.get(apontamento=ap)
        self.assertEqual(fila.status, 'CONFERIR')
        self.assertEqual(ws.appends, 1)
        with self.assertRaises(ValueError):
            solicitar_reenvio(fila.pk, self.lider)
        with self.assertRaises(PermissionError):
            solicitar_reenvio(fila.pk, self.operador, True, 'Linha ausente na DR')
        solicitar_reenvio(fila.pk, self.lider, True, 'Linha ausente após conferência da planilha')
        ws.rejeitar = False
        self.rodar()
        fila.refresh_from_db()
        self.assertEqual(fila.status, 'SINCRONIZADO')
        self.assertTrue(fila.historico.filter(evento='AUSENCIA_CONFIRMADA', usuario=self.lider).exists())

    def test_reinicio_apos_append_preserva_tentativa_duravel(self):
        self.vulcanizar()
        with patch('bladder.sincronizacao_drs._confirmar', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                self.rodar()
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'ENVIANDO')
        self.rodar()
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'SINCRONIZADO')
        self.assertEqual(self.planilhas['DR115'].appends, 1)

    def test_correcao_audita_e_atualiza_linha_movida_sem_append(self):
        ap = self.vulcanizar()
        self.rodar()
        ws = self.planilhas['DR115']
        ws.linhas.insert(1, ['Registro alheio'])
        corrigir_producao(ap.pk, self.operador, {**self.dados(), 'temperatura': '195.5'}, 'Temperatura conferida')
        self.rodar()
        fila = SincronizacaoDRBladder.objects.get()
        self.assertEqual((fila.status, fila.linha_planilha, ws.appends, ws.updates), ('SINCRONIZADO', 3, 1, 1))
        self.assertEqual(ws.linhas[2][8], 195.5)
        self.assertEqual(HistoricoApontamentoBladder.objects.get().valores_novos['temperatura'], '195.5')

    def test_correcao_do_manuseio_preserva_coluna18(self):
        ap = self.extrusar()
        man = self.manusear(ap)
        self.rodar()
        ws = self.planilhas['DR114']
        ws.linhas[1][17] = 'Conteúdo alheio que não será alterado'
        corrigir_producao(man.pk, self.lider, {**self.dados('06'), 'materia_prima': 'NOVO - FBB0002'},
                          'Material conferido', amostras=self.medidas(20))
        self.rodar()
        self.assertEqual(ws.linhas[1][17], 'Conteúdo alheio que não será alterado')
        self.assertEqual(ws.linhas[1][2], 'NOVO - FBB0002')
        self.assertEqual((ws.appends, ws.updates), (1, 1))

    def test_correcao_durante_envio_nao_e_perdida(self):
        ap = self.vulcanizar()
        ws = self.planilhas['DR115']
        ws.ao_gravar = lambda: corrigir_producao(ap.pk, self.operador,
            {**self.dados(), 'pressao': '20'}, 'Pressão corrigida durante envio')
        self.rodar()
        fila = SincronizacaoDRBladder.objects.get()
        self.assertEqual((fila.status, fila.revisao, fila.revisao_enviada), ('PENDENTE', 2, 1))
        self.rodar()
        self.assertEqual(ws.linhas[1][7], 20.0)
        self.assertEqual((ws.appends, ws.updates), (1, 1))

    def test_correcao_apos_timeout_resolve_revisao_antiga_primeiro(self):
        ap = self.vulcanizar()
        ws = self.planilhas['DR115']
        ws.timeout = True
        self.rodar()
        corrigir_producao(ap.pk, self.operador, {**self.dados(), 'pressao': '22'}, 'Aferição posterior')
        self.rodar(avancar=True)
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'PENDENTE')
        self.rodar()
        self.assertEqual(ws.linhas[1][7], 22.0)
        self.assertEqual(ws.appends, 1)

    def test_duplicidade_ou_edicao_externa_bloqueia_sobrescrita(self):
        ap = self.vulcanizar()
        self.rodar()
        ws = self.planilhas['DR115']
        ws.linhas.append(copy.deepcopy(ws.linhas[1]))
        corrigir_producao(ap.pk, self.operador, {**self.dados(), 'pressao': '25'}, 'Aferição de pressão')
        self.rodar()
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'CONFERIR')
        self.assertEqual(ws.updates, 0)
        ws.linhas.pop()
        fila = SincronizacaoDRBladder.objects.get()
        solicitar_reenvio(fila.pk, self.lider, reconferir=True)
        self.rodar()
        self.assertEqual(ws.updates, 1)

    def test_conteudo_identico_preexistente_nao_e_apropriado(self):
        ap = self.vulcanizar()
        ws = self.planilhas['DR115']
        ws.linhas.append(ap.sincronizacao_dr.payload)
        self.rodar()
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'CONFERIR')
        self.assertEqual(ws.appends, 0)

    def test_identicos_apos_timeout_permanecem_em_conferencia(self):
        ap = self.vulcanizar()
        ws = self.planilhas['DR115']
        ws.timeout = True
        self.rodar()
        ws.linhas.append(copy.deepcopy(ws.linhas[1]))
        self.rodar(avancar=True)
        self.assertEqual(SincronizacaoDRBladder.objects.get(apontamento=ap).status, 'CONFERIR')
        self.assertEqual(ws.appends, 1)

    def test_historico_sem_parametros_nao_recebe_dados_ficticios(self):
        ap = self.vulcanizar()
        ap.temperatura = None
        ap.save()
        enfileirar(ap)
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'AGUARDANDO')
        self.assertEqual(self.rodar(), 0)
        self.assertEqual(self.planilhas['DR115'].appends, 0)

    def test_apex_e_aneis_nao_tem_destino(self):
        self.registrar(self.op('04'), self.dados('04'))
        self.registrar(self.op('05'), self.dados('05'))
        self.assertFalse(SincronizacaoDRBladder.objects.exists())

    def test_status_detalhes_post_permissoes_e_csrf(self):
        ap = self.vulcanizar()
        url = reverse('bladder:producao_reprocessar_dr', args=[ap.pk])
        detalhe = reverse('bladder:producao_detalhe', args=[ap.pk])
        self.client.force_login(self.operador)
        self.assertContains(self.client.get(detalhe), 'DR.115 — Pendente')
        self.assertNotContains(self.client.get(detalhe), 'Tentar novamente')
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(SincronizacaoDRBladder.objects.get().historico.exists())
        self.client.force_login(self.lider)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertTrue(SincronizacaoDRBladder.objects.get().historico.filter(usuario=self.lider).exists())
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.lider)
        self.assertEqual(csrf.post(url).status_code, 403)

    def test_comando_limite_destino_e_sem_rede_com_fila_vazia(self):
        saida = io.StringIO()
        with patch('gspread.service_account') as rede:
            call_command('sincronizar_producao_drs', destino='DR114', stdout=saida)
            rede.assert_not_called()
        self.assertIn('0 registro(s)', saida.getvalue())
        self.vulcanizar()
        self.assertEqual(self.rodar(destino='DR114'), 0)
        self.assertEqual(self.rodar(destino='DR115', limite=1), 1)

    def test_cliente_valida_gid_nome_e_timeout_sem_tocar_estrutura(self):
        from .sincronizacao_drs import _abrir
        with patch('gspread.service_account') as factory:
            cliente = factory.return_value
            cliente.open_by_key.return_value.get_worksheet_by_id.return_value = self.planilhas['DR115']
            self.assertIs(_abrir('DR115'), self.planilhas['DR115'])
            cliente.set_timeout.assert_called_once_with(30)
            cliente.open_by_key.assert_called_once_with(DESTINOS['DR115']['id'])
            cliente.open_by_key.return_value.get_worksheet_by_id.assert_called_once_with(161109830)
            self.planilhas['DR115'].title = 'Outra aba'
            with self.assertRaises(ValueError):
                _abrir('DR115')

    def test_controle_exclusivo_por_destino_e_recuperacao_apos_expirar(self):
        token = adquirir('DR115')
        self.assertIsNotNone(token)
        self.assertIsNone(adquirir('DR115'))
        self.assertIsNotNone(adquirir('DR114'))
        BloqueioDRBladder.objects.filter(destino='DR115').update(expira_em=timezone.now()-timedelta(seconds=1))
        self.assertNotEqual(adquirir('DR115'), token)

    def test_update_sem_resposta_reconcilia_sem_repetir_escrita(self):
        ap = self.vulcanizar()
        self.rodar()
        ws = self.planilhas['DR115']
        ws.timeout = True
        corrigir_producao(ap.pk, self.operador, {**self.dados(), 'pressao': '28'}, 'Pressão conferida')
        self.rodar()
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'CONFERIR')
        self.rodar(avancar=True)
        self.assertEqual(SincronizacaoDRBladder.objects.get().status, 'SINCRONIZADO')
        self.assertEqual((ws.appends, ws.updates), (1, 1))

    def test_update_nao_gravado_pode_ser_reconferido_pela_lideranca(self):
        ap = self.vulcanizar()
        self.rodar()
        ws = self.planilhas['DR115']
        ws.rejeitar = True
        corrigir_producao(ap.pk, self.operador, {**self.dados(), 'pressao': '29'}, 'Pressão conferida')
        self.rodar()
        fila = SincronizacaoDRBladder.objects.get()
        self.assertEqual(fila.status, 'CONFERIR')
        solicitar_reenvio(fila.pk, self.lider, reconferir=True)
        self.rodar()
        fila.refresh_from_db()
        self.assertEqual(fila.status, 'PENDENTE')
        ws.rejeitar = False
        self.rodar()
        fila.refresh_from_db()
        self.assertEqual(fila.status, 'SINCRONIZADO')
        self.assertEqual(ws.appends, 1)

    def test_resposta_tardia_da_revisao_liberada_nao_gera_duplicacao(self):
        ap = self.vulcanizar()
        ws = self.planilhas['DR115']
        ws.rejeitar = True
        self.rodar()
        fila = SincronizacaoDRBladder.objects.get()
        antigo = list(fila.payload_tentativa)
        corrigir_producao(ap.pk, self.operador, {**self.dados(), 'pressao': '30'}, 'Aferição posterior')
        solicitar_reenvio(fila.pk, self.lider, True, 'Registro ausente na conferência manual')
        # A gravação da tentativa antiga apareceu depois da liberação.
        ws.linhas.append(antigo)
        ws.rejeitar = False
        self.rodar()
        fila.refresh_from_db()
        self.assertEqual(fila.status, 'CONFERIR')
        self.assertEqual(ws.appends, 1)

    def test_correcao_processamento_mantem_data_autoria_e_auditoria(self):
        ap = self.extrusar()
        self.manusear(ap)
        self.rodar()
        original = self.planilhas['DR114'].linhas[1][:2]
        corrigir_producao(ap.pk, self.lider, {**self.dados('03', 20),
            'tipo_processamento': 'Reprocessamento', 'resfriamento': 'Ao ar'}, 'Conferência dos parâmetros')
        self.rodar()
        linha = self.planilhas['DR114'].linhas[1]
        self.assertEqual(linha[:2], original)
        self.assertEqual((linha[6], linha[18]), ('Reprocessamento', 'Ao ar'))
        h = HistoricoApontamentoBladder.objects.get(apontamento=ap)
        self.assertEqual(h.valores_novos['resfriamento'], 'Ao ar')

    def test_status_e_novos_campos_na_exportacao_local(self):
        ap = self.extrusar()
        self.client.force_login(self.lider)
        resposta = self.client.get(reverse('bladder:acompanhamento_exportar_excel'))
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(resposta.content), read_only=True)
        linhas = list(wb['Registros'].values)
        self.assertEqual(linhas[0][20:24], ('Tipo de processamento', 'Resfriamento', 'Temperatura', 'Situação da DR'))
        self.assertEqual(linhas[1][20:24], ('Material normal', 'Tanque de água', 90.5, 'Aguardando manuseio / dados'))

    def test_registro_idempotente_nao_recria_fila(self):
        op = self.op()
        chave = uuid.uuid4()
        ap1, criado1 = registrar_producao(op.pk, self.operador, self.dados(), chave)
        ap2, criado2 = registrar_producao(op.pk, self.operador, self.dados(), chave)
        self.assertEqual(ap1.pk, ap2.pk)
        self.assertTrue(criado1)
        self.assertFalse(criado2)
        self.assertEqual(SincronizacaoDRBladder.objects.count(), 1)

    def test_fila_em_conferencia_nao_bloqueia_registros_posteriores(self):
        self.vulcanizar()
        SincronizacaoDRBladder.objects.update(status='CONFERIR')
        outro = self.vulcanizar(pressao='30')
        self.rodar(limite=1)
        self.assertEqual(SincronizacaoDRBladder.objects.get(apontamento=outro).status, 'SINCRONIZADO')

    def test_preverificacao_nao_envia_e_rejeita_instalacao_em_desenvolvimento(self):
        from django.core.management.base import CommandError
        with override_settings(DEBUG=True):
            with self.assertRaises(CommandError):
                call_command('sincronizar_producao_drs', verificar_instalacao=True)
        with override_settings(DEBUG=False), patch('pathlib.Path.is_file', return_value=True), patch('gspread.service_account') as rede:
            call_command('sincronizar_producao_drs', verificar_instalacao=True, stdout=io.StringIO())
            rede.assert_not_called()


class ConcorrenciaDRTestCase(TransactionTestCase):
    def test_duas_conexoes_adquirem_apenas_um_trabalhador(self):
        BloqueioDRBladder.objects.create(destino='DR115')
        barreira = Barrier(2)

        def tentar(_):
            close_old_connections()
            try:
                barreira.wait(timeout=5)
                return adquirir('DR115')
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(tentar, range(2)))
        self.assertEqual(sum(r is not None for r in resultados), 1)
