"""Ensaio opcional em navegador: usa somente o banco temporário de testes.

Executar com o Python do .venv: scripts/validar_dashboard_matrizaria.py
Requer Playwright no ambiente de desenvolvimento e Microsoft Edge instalado.
Não faz parte das dependências da aplicação nem da suíte padrão.
"""
import os
from pathlib import Path
import sys
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maintenance_project.settings")
if "test" not in sys.argv:
    sys.argv.append("test")

import django
django.setup()

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.test.runner import DiscoverRunner
from playwright.sync_api import sync_playwright

from matrizaria.test_dashboard import MatrizariaDashboardTestCase


@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False,
                   ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class DashboardBrowserSmokeTest(StaticLiveServerTestCase):
    def test_desktop_mobile_filters_and_drilldown(self):
        fixture = MatrizariaDashboardTestCase
        fixture.setUpTestData()
        self.client.force_login(fixture.technical_leader)
        artifacts = PROJECT_DIR / "logs" / "dashboard_matrizaria"
        artifacts.mkdir(parents=True, exist_ok=True)
        session = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        admin = fixture.lider_user.__class__.objects.create_superuser(username="browser_admin", email="", password="test")
        admin_client = Client()
        admin_client.force_login(admin)
        admin_session = admin_client.cookies[settings.SESSION_COOKIE_NAME].value
        with patch("matrizaria.dashboard.timezone.now", return_value=fixture.now), sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            context.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": session,
                                 "url": self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            target = self.live_server_url + "/matrizaria/dashboard/?periodo=personalizado&data_inicio=2026-11-12&data_fim=2026-11-13"
            response = page.goto(target, wait_until="networkidle")
            self.assertEqual(response.status, 200)
            self.assertTrue(page.get_by_role("heading", name="Dashboard da Matrizaria", exact=True).is_visible())
            self.assertEqual(page.locator("svg.dashboard-svg").count(), 2)
            self.assertEqual(page.locator(".dashboard-kpi").count(), 8)
            self.assertEqual(page.locator(".dashboard-chart").count(), 5)
            self.assertTrue(page.locator(".dashboard-bars .fill").first.evaluate("element => element.getBoundingClientRect().width > 0"))
            self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
            page.screenshot(path=str(artifacts / "desktop.png"), full_page=True)
            page.locator('svg a[aria-label*="concluídas"]').last.click()
            page.wait_for_url("**/dashboard/detalhes/**")
            self.assertTrue(page.get_by_role("heading", name="Serviços concluídos", exact=True).first.is_visible())
            self.assertIn("SM #" + str(fixture.completed.pk), page.locator("tbody").inner_text())
            page.goto(target, wait_until="networkidle")
            page.locator("#id_prioridade").select_option("URGENTE")
            page.get_by_role("button", name="Aplicar filtros").click()
            page.wait_for_url("**prioridade=URGENTE**")
            self.assertIn("SM #" + str(fixture.waiting.pk), page.locator("#lista tbody").inner_text())
            self.assertNotIn("SM #" + str(fixture.internal.pk), page.locator("#lista tbody").inner_text())
            for width in (375, 768):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(target, wait_until="networkidle")
                self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                self.assertTrue(page.get_by_role("heading", name="Dashboard da Matrizaria", exact=True).is_visible())
                page.screenshot(path=str(artifacts / f"mobile-{width}.png"), full_page=True)
            page.locator("#id_data_inicio").fill("2026-11-14")
            self.assertEqual(page.locator("#id_periodo").input_value(), "personalizado")
            page.get_by_role("button", name="Aplicar filtros").click()
            self.assertTrue(page.get_by_role("alert").first.is_visible())
            self.assertEqual(errors, [])
            # As duas telas existentes continuam acessíveis ao administrador.
            context.clear_cookies()
            context.add_cookies([{"name": settings.SESSION_COOKIE_NAME,
                                 "value": admin_session,
                                 "url": self.live_server_url}])
            for url in ("/management/", "/dashboard/"):
                self.assertEqual(page.goto(self.live_server_url + url, wait_until="domcontentloaded").status, 200)
            browser.close()
        print("Desktop, 375px, 768px, filtros, detalhamento e telas existentes: OK")


if __name__ == "__main__":
    failures = DiscoverRunner(verbosity=1, interactive=False).run_tests(
        ["scripts.validar_dashboard_matrizaria.DashboardBrowserSmokeTest"])
    sys.exit(bool(failures))
