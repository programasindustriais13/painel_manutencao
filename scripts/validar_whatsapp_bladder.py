"""Ensaio opcional no Edge: banco temporário e transporte simulado, sem envio real."""
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maintenance_project.settings')
if 'test' not in sys.argv:
    sys.argv.append('test')

import django
django.setup()

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.test.runner import DiscoverRunner
from playwright.sync_api import sync_playwright

from bladder.models import ConfiguracaoWhatsAppBladder, EnvioWhatsAppBladder


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, WHATSAPP_DRY_RUN=False,
                   ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'])
class WhatsAppBrowserTest(StaticLiveServerTestCase):
    def test_salvar_teste_confirmar_e_impedir_repeticao(self):
        config = ConfiguracaoWhatsAppBladder.objects.create(numero_destino='5585999999999')
        admin = User.objects.create_superuser('browser_whatsapp', email='', password='test')
        self.client.force_login(admin)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        artifacts = PROJECT_DIR / 'logs' / 'whatsapp_bladder'
        artifacts.mkdir(parents=True, exist_ok=True)
        with patch('bladder.whatsapp.requests.get') as get, patch('bladder.whatsapp.requests.post') as post, sync_playwright() as playwright:
            get.return_value = Mock(status_code=200)
            get.return_value.json.return_value = {'connected': True, 'tracking_version': 2, 'circuitTripped': False}
            post.return_value = Mock(status_code=202)
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': session, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            response = page.goto(f'{self.live_server_url}/admin/bladder/configuracaowhatsappbladder/{config.pk}/change/', wait_until='networkidle')
            self.assertEqual(response.status, 200)
            self.assertTrue(page.locator('input[name="_enviar_teste"]').is_visible())
            post.assert_not_called()
            page.locator('#id_numero_destino').fill('5585999998888')
            page.locator('input[name="_enviar_teste"]').click()
            page.wait_for_load_state('networkidle')
            post.assert_called_once()
            self.assertEqual(post.call_args.kwargs['json']['numero'], '5585999998888')
            self.assertIn('Mensagem aceita na fila', page.locator('body').inner_text())
            page.locator('input[name="_enviar_teste"]').click()
            page.wait_for_load_state('networkidle')
            self.assertIn('Aguarde ao menos dez minutos', page.locator('body').inner_text())
            self.assertEqual(post.call_count, 1)
            get.return_value.json.return_value = {'status': 'submitted', 'whatsapp_message_id': 'WA-TESTE', 'resolved_jid': '5585999998888@s.whatsapp.net'}
            page.locator('input[name="_consultar_envios"]').click()
            page.wait_for_load_state('networkidle')
            self.assertIn('Aguardando confirmação do WhatsApp', page.locator('fieldset table').inner_text())
            get.return_value.json.return_value = {'status': 'server_ack'}
            page.locator('input[name="_consultar_envios"]').click()
            page.wait_for_load_state('networkidle')
            self.assertIn('Aceito pelo servidor WhatsApp', page.locator('fieldset table').inner_text())
            get.return_value.json.return_value = {'status': 'delivered'}
            page.locator('input[name="_consultar_envios"]').click()
            page.wait_for_load_state('networkidle')
            self.assertIn('Entrega confirmada', page.locator('fieldset table').inner_text())
            page.screenshot(path=str(artifacts / 'admin-envio-confirmado.png'), full_page=True)
            for url in ('/management/', '/dashboard/'):
                self.assertEqual(page.goto(self.live_server_url + url, wait_until='domcontentloaded').status, 200)
            self.assertEqual(errors, [])
            browser.close()
        envio = EnvioWhatsAppBladder.objects.get()
        self.assertEqual(envio.solicitado_por_id, admin.pk)
        self.assertEqual(envio.status, 'ENTREGUE')
        print('Admin: salvar, enviar, bloquear repetição, confirmar status; /management/ e /dashboard/: OK')


if __name__ == '__main__':
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests(['scripts.validar_whatsapp_bladder.WhatsAppBrowserTest'])
    sys.exit(bool(failures))
