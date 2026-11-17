"""Ensaio Edge opcional; cria dados exclusivamente no banco temporário Django.

Executar: .venv/Scripts/python.exe scripts/validar_apontamentos_bladder.py
Requer Playwright e Edge já instalados; não usa estoque, DR-201 ou WhatsApp.
"""
import os
from pathlib import Path
import sys
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maintenance_project.settings')
if 'test' not in sys.argv:
    sys.argv.append('test')

import django
django.setup()

from django.conf import settings
from django.db import close_old_connections
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.test.runner import DiscoverRunner
from playwright.sync_api import sync_playwright, expect

from bladder.test_apontamentos_producao import preparar_fixtures, ApontamentosProducaoTestCase
from bladder.models import ApontamentoTurnoBladder, OrdemProducaoBladder, MovimentacaoEstoqueBladder, SaldoPendenteBladder
from bladder.services import criar_ordem_producao_com_saldos


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False,
                   ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'])
class ApontamentosBrowserTest(StaticLiveServerTestCase):
    def test_fluxo_processos_celular_tablet(self):
        preparar_fixtures(self)
        ops = {codigo: criar_ordem_producao_com_saldos(self.processos[codigo], self.produto, self.hoje, meta, usuario=self.lider)
               for codigo, meta in [('01', 2), ('02', 1), ('03', 61), ('04', 7), ('05', 20)]}
        self.client.force_login(self.operador)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = PROJECT_DIR / 'logs' / 'apontamentos_bladder'
        artifacts.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(viewport={'width': 375, 'height': 900})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda erro: errors.append(str(erro)))

            def banco(consulta):
                # Sync Playwright mantém um event loop: ORM fica fora dele.
                def executar():
                    close_old_connections()
                    try:
                        return consulta()
                    finally:
                        close_old_connections()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    return executor.submit(executar).result()

            def abrir(caminho):
                resposta = page.goto(self.live_server_url + caminho, wait_until='networkidle')
                self.assertEqual(resposta.status, 200, caminho)
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'), caminho)

            def formulario(codigo):
                abrir(f'/bladder/operador/producao/{ops[codigo].pk}/registrar/')

            def preencher(dados):
                for nome, valor in dados.items():
                    campo = page.locator('#id_' + nome)
                    if campo.evaluate('el => el.tagName') == 'SELECT':
                        campo.select_option(str(valor))
                    else:
                        campo.fill(str(valor))

            def salvar():
                page.locator('#salvar-producao').click()
                page.wait_for_url('**/bladder/operador/?producao=*')

            abrir('/bladder/operador/')
            self.assertEqual(page.get_by_role('link', name='REGISTRAR MANUSEIO', exact=True).count(), 0)
            # OPs novas não podem fabricar produção no fechamento antes dos detalhes.
            abrir('/bladder/operador/fechar-turno/')
            for op in ops.values():
                self.assertTrue(op.exige_execucoes)
                quantidade = page.locator(f'#qtd_realizada_{op.pk}')
                self.assertEqual(quantidade.input_value(), '0')
                self.assertFalse(quantidade.is_editable())
            abrir('/bladder/operador/')
            card = page.locator(f'#op-{ops["01"].pk}')
            self.assertEqual(card.get_by_role('link', name='REGISTRAR PRODUÇÃO', exact=True).count(), 1)
            card.locator('button[data-bs-target^="#modalDetalhes"]').click()
            modal = page.locator(f'#modalDetalhes{ops["01"].pk}')
            expect(modal).to_be_visible()
            modal.locator('.btn-close').click()
            expect(modal).not_to_be_visible()
            card.locator('button[onclick^="abrirModalRecadoContextual"]').click()
            recado = page.locator('#modalNovoRecado')
            expect(recado).to_be_visible()
            recado.locator('.btn-close').click()
            expect(recado).not_to_be_visible()

            # Inspeção dos cinco contextos nas duas larguras, sem campos alheios.
            for largura in (375, 768):
                page.set_viewport_size({'width': largura, 'height': 900})
                abrir('/bladder/operador/')
                page.screenshot(path=str(artifacts / f'quadro-{largura}.png'), full_page=True)
                for codigo in ops:
                    formulario(codigo)
                    if codigo in ('01', '02'):
                        self.assertEqual(page.locator('#id_tempo_vulcanizacao').input_value(), '')
                        self.assertEqual(page.locator('#id_pressao').input_value(), '')
                        self.assertEqual(page.locator('#id_temperatura').input_value(), '')
                        self.assertIn('Imperfeição Aparente', page.locator('#id_condicao').inner_text())
                        self.assertEqual(page.locator('#id_temperatura_tcu_1').count(), 0)
                    elif codigo in ('03', '04'):
                        self.assertEqual(page.locator('#id_temperatura_tcu_4').count(), 1)
                        self.assertEqual(page.locator('#id_pressao').count(), 0)
                        self.assertEqual(page.locator('#id_tipo_processamento').count(), 1 if codigo == '03' else 0)
                        self.assertEqual(page.locator('#id_resfriamento').count(), 1 if codigo == '03' else 0)
                    else:
                        self.assertEqual(page.locator('#id_quantidade_realizada').count(), 0)
                        self.assertIn('Parcialmente Bons', page.locator('#id_condicao').inner_text())
                    page.screenshot(path=str(artifacts / f'processo-{codigo}-{largura}.png'), full_page=True)

            # POST inválido com vírgula: render deve preservar decimal HTML válido.
            formulario('01')
            dados = ApontamentosProducaoTestCase.dados(self, '01')
            preencher(dados)
            page.locator('#id_tempo_vulcanizacao').fill('')
            page.locator('#id_pressao').evaluate('el => el.type="text"')
            page.locator('#id_pressao').fill('1,250')
            page.locator('#form-producao').evaluate('el => el.noValidate=true')
            page.locator('#salvar-producao').click()
            expect(page.locator('.errorlist').first).to_be_visible()
            self.assertEqual(page.locator('#id_pressao').input_value(), '1.250')
            self.assertEqual(page.locator('#id_lote_produto').input_value(), '000123')
            page.locator('#id_tempo_vulcanizacao').fill('120.5')
            salvar()
            self.assertIn('1 de 2 unidades', page.locator('body').inner_text())
            formulario('01')
            self.assertEqual(page.locator('#id_tempo_vulcanizacao').input_value(), '')
            self.assertEqual(page.locator('#id_pressao').input_value(), '')
            formulario('02'); preencher(ApontamentosProducaoTestCase.dados(self, '02')); salvar()

            for quantidade, amostras in [(30, 3), (31, 4)]:
                formulario('03'); preencher(ApontamentosProducaoTestCase.dados(self, '03', quantidade)); salvar()
                fonte_id = banco(lambda: ApontamentoTurnoBladder.objects.get(ordem=ops['03'], quantidade_realizada=quantidade).pk)
                self.assertEqual(banco(lambda: OrdemProducaoBladder.objects.count()), 5)
                abrir(f'/bladder/operador/extrusoes/{fonte_id}/manuseio/')
                self.assertEqual(page.locator('.amostra').count(), amostras)
                self.assertIn('Equipamento 06', page.locator('body').inner_text())
                preencher(ApontamentosProducaoTestCase.dados(self, '06'))
                for n in range(amostras):
                    diametro = ['38.0', '38.2', '37.9', '38.1'][n]
                    page.locator(f'#id_amostras-{n}-diametro').fill(diametro)
                    page.locator(f'#id_amostras-{n}-comprimento').fill('160')
                    page.locator(f'#id_amostras-{n}-peso').fill('3.125')
                if quantidade == 30:
                    self.assertEqual(page.locator('#media-diametro').inner_text(), '38,03')
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                page.screenshot(path=str(artifacts / f'manuseio-{quantidade}.png'), full_page=True)
                salvar()
                manuseio_id, total_amostras, media = banco(lambda: (
                    ApontamentoTurnoBladder.objects.get(extrusao_origem_id=fonte_id).pk,
                    ApontamentoTurnoBladder.objects.get(extrusao_origem_id=fonte_id).amostras.count(),
                    ApontamentoTurnoBladder.objects.get(extrusao_origem_id=fonte_id).media_diametro))
                self.assertEqual(total_amostras, amostras)
                if quantidade == 30:
                    self.assertEqual(media, Decimal('38.03'))
                abrir(f'/bladder/operador/producao/{manuseio_id}/')
                self.assertIn('Amostras preservadas', page.locator('body').inner_text())
                self.assertIn('DR.114 — Pendente', page.locator('body').inner_text())
                self.assertEqual(page.get_by_role('link', name='Abrir DR', exact=True).count(), 1)
                self.assertEqual(page.get_by_role('button', name='Tentar novamente', exact=True).count(), 0)
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                page.screenshot(path=str(artifacts / f'dr114-detalhe-{quantidade}.png'), full_page=True)

            formulario('04'); preencher(ApontamentosProducaoTestCase.dados(self, '04', 7)); salvar()
            self.assertEqual(page.get_by_role('link', name='REGISTRAR MANUSEIO', exact=True).count(), 0)
            formulario('05'); preencher(ApontamentosProducaoTestCase.dados(self, '05')); salvar()
            self.assertIn('Quantidade não apurada', page.locator('body').inner_text())
            for largura in (375, 768):
                page.set_viewport_size({'width': largura, 'height': 900})
                abrir('/bladder/operador/')
                self.assertIn('META ATINGIDA', page.locator(f'#op-{ops["03"].pk}').inner_text())
                self.assertIn('META ATINGIDA', page.locator(f'#op-{ops["04"].pk}').inner_text())
                self.assertIn('Faltam 1 un', page.locator(f'#op-{ops["01"].pk}').inner_text())
                self.assertNotIn('META ATINGIDA', page.locator(f'#op-{ops["05"].pk}').inner_text())
                page.locator(f'#op-{ops["03"].pk}').screenshot(path=str(artifacts / f'meta-atingida-{largura}.png'))
            self.assertEqual(banco(lambda: MovimentacaoEstoqueBladder.objects.count()), 0)
            self.assertEqual(banco(lambda: OrdemProducaoBladder.objects.get(pk=ops['03'].pk).quantidade_realizada), 61)
            abrir('/bladder/operador/fechar-turno/')
            self.assertEqual(page.locator(f'#qtd_realizada_{ops["03"].pk}').input_value(), '61')
            self.assertTrue(page.locator(f'#qtd_realizada_{ops["03"].pk}').is_editable() is False)
            page.locator(f'input[name="categorias_{ops["01"].pk}"]').first.check(force=True)
            page.locator(f'#descricao_desvio_{ops["01"].pk}').fill('Prensa indisponível no fim do turno')
            page.locator('#btn-submit-fechamento').click()
            page.wait_for_url('**/bladder/operador/')
            self.assertEqual(banco(lambda: SaldoPendenteBladder.objects.get().quantidade), 1)
            self.assertEqual(banco(lambda: ApontamentoTurnoBladder.objects.filter(origem='PROCESSO').count()), 6)
            self.assertEqual(banco(lambda: ApontamentoTurnoBladder.objects.filter(origem='LEGADO').count()), 0)
            self.assertEqual(errors, [])

            # Smoke das áreas existentes com administrador do banco temporário.
            def sessao_admin():
                admin = User.objects.create_superuser(username='qa_browser_admin', email='')
                self.client.force_login(admin)
                return self.client.cookies[settings.SESSION_COOKIE_NAME].value
            admin_session = banco(sessao_admin)
            context.clear_cookies()
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME,
                                 'value': admin_session,
                                 'url': self.live_server_url}])
            for caminho in ('/management/', '/dashboard/'):
                self.assertEqual(page.goto(self.live_server_url+caminho, wait_until='domcontentloaded').status, 200)
            for largura in (375, 768):
                page.set_viewport_size({'width': largura, 'height': 900})
                abrir('/bladder/')
                expect(page.get_by_role('heading', name='Acompanhamento da produção')).to_be_visible()
                self.assertEqual(page.get_by_role('link', name='Exportar Excel').count(), 1)
                self.assertGreater(page.locator('article').count(), 0)
                page.screenshot(path=str(artifacts / f'acompanhamento-{largura}.png'), full_page=True)
            browser.close()
        print('QA Edge: 375px/768px, apontamentos, acompanhamento do líder, fechamento e regressões: OK')


if __name__ == '__main__':
    sys.exit(bool(DiscoverRunner(verbosity=1, interactive=False).run_tests([
        'scripts.validar_apontamentos_bladder.ApontamentosBrowserTest'
    ])))
