import json
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta


from .models import (
    Sector, 
    Machine, 
    Technician, 
    OrdemServico, 
    OrdemServicoPeca,
    Allocation, 
    HistoricoPausa, 
    HistoricoEscala, 
    WhatsAppGroup, 
    AllocationProgressUpdate
)
from .forms import OrdemServicoCreateForm


class MaintenanceSystemTestCase(TestCase):
    def setUp(self):
        # Create groups
        self.operator_group, _ = Group.objects.get_or_create(name='Operadores')
        self.viewer_group, _ = Group.objects.get_or_create(name='Visualizador')
        self.tech_group, _ = Group.objects.get_or_create(name='Tecnicos')
        self.lider_group, _ = Group.objects.get_or_create(name='Tecnicos_Lideres')
        
        # Create users
        self.admin_user = User.objects.create_superuser('admin_test', 'admin@test.com', 'pwd123')
        self.operador_user = User.objects.create_user('operador_test', 'operador@test.com', 'pwd123')
        self.operador_user.groups.add(self.operator_group)
        
        self.viewer_user = User.objects.create_user('viewer_test', 'viewer@test.com', 'pwd123')
        self.viewer_user.groups.add(self.viewer_group)
        
        # Create domain data
        self.sector = Sector.objects.create(nome="Usinagem")
        
        self.machine_low = Machine.objects.create(nome="Torno CNC", setor=self.sector, criticidade="BAIXA")
        self.machine_high = Machine.objects.create(nome="Prensa Hidráulica", setor=self.sector, criticidade="ALTA")
        
        self.tech = Technician.objects.create(nome="Carlos Souza", matricula="TEC-001", status="OCIOSO")

    def test_machine_properties(self):
        """Test bootstrap color property returns correct values based on criticality."""
        self.assertEqual(self.machine_low.bootstrap_color, 'success')
        self.assertEqual(self.machine_high.bootstrap_color, 'danger')

    def test_allocation_properties(self):
        """Test active allocation and duration calculator logic."""
        now = timezone.now()
        alloc = Allocation.objects.create(
            tecnico=self.tech,
            maquina=self.machine_low,
            atividade_observacao="Checking belts",
            data_inicio=now - timedelta(minutes=45)
        )
        self.tech.status = 'EM_ATENDIMENTO'
        self.tech.save()
        
        # Test active allocation resolver
        self.assertEqual(self.tech.active_allocation, alloc)
        
        # Test active elapsed time string (between 40m and 50m)
        self.assertIn("m", alloc.tempo_decorrido_str)
        
        # Test paused elapsed time calculation
        alloc.data_pausa = now - timedelta(minutes=15)
        alloc.save()
        # Active time was from start (now-45m) to pause (now-15m) = 30 minutes
        self.assertEqual(alloc.tempo_decorrido_str, "30m")
        
        # Test completed elapsed time calculation
        alloc.data_pausa = None
        alloc.data_fim = now
        alloc.save()
        self.assertEqual(alloc.tempo_decorrido_str, "45m")

    def test_auth_guards(self):
        """Test access control for tv board vs management panel."""
        client = Client()
        
        # Anonymous user redirected to login
        response = client.get(reverse('tv_dashboard'))
        self.assertEqual(response.status_code, 302)
        
        # Viewer user can access TV panel, but is blocked from operator controls
        client.force_login(self.viewer_user)
        response = client.get(reverse('tv_dashboard'))
        self.assertEqual(response.status_code, 200)
        
        response = client.get(reverse('technician_management'))
        # Custom decorator redirects to login on access violations
        self.assertRedirects(response, reverse('login'))
        
        # Operator user can access both
        client.force_login(self.operador_user)
        response = client.get(reverse('tv_dashboard'))
        self.assertEqual(response.status_code, 200)
        
        response = client.get(reverse('technician_management'))
        self.assertEqual(response.status_code, 200)

    def test_state_transitions(self):
        """Test full operational workflow (Start -> Pause -> Resume -> Finish)."""
        client = Client()
        client.force_login(self.operador_user)
        
        # 1. Start Service
        response = client.post(
            reverse('start_service', args=[self.tech.id]),
            data={'maquina': self.machine_low.id, 'atividade_observacao': 'Troca de óleo'}
        )
        self.assertRedirects(response, reverse('technician_management'))
        
        # Refresh tech from database
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.status, 'EM_ATENDIMENTO')
        
        active_alloc = self.tech.active_allocation
        self.assertIsNotNone(active_alloc)
        self.assertEqual(active_alloc.maquina, self.machine_low)
        self.assertEqual(active_alloc.atividade_observacao, 'Troca de óleo')
        self.assertIsNone(active_alloc.data_pausa)
        
        # 2. Pause Service
        response = client.post(
            reverse('pause_service', args=[self.tech.id]),
            data={'motivo_pausa': 'Falta de peças no estoque'}
        )
        self.assertRedirects(response, reverse('technician_management'))
        
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.status, 'EM_PAUSA')
        
        active_alloc.refresh_from_db()
        self.assertIsNotNone(active_alloc.data_pausa)
        self.assertEqual(active_alloc.motivo_pausa, 'Falta de peças no estoque')
        
        # 3. Resume Service
        response = client.post(reverse('resume_service', args=[self.tech.id]))
        self.assertRedirects(response, reverse('technician_management'))
        
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.status, 'EM_ATENDIMENTO')
        
        active_alloc.refresh_from_db()
        self.assertIsNone(active_alloc.data_pausa)
        self.assertIsNone(active_alloc.motivo_pausa)
        
        # 4. Finish Service
        response = client.post(
            reverse('finish_service', args=[self.tech.id]),
            data={'observacao_conclusao': 'Serviço executado perfeitamente'}
        )
        self.assertRedirects(response, reverse('technician_management'))
        
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.status, 'OCIOSO')
        
        # Ensure active allocation is closed
        active_alloc.refresh_from_db()
        self.assertIsNotNone(active_alloc.data_fim)
        self.assertEqual(active_alloc.status, 'CONCLUIDO')
        self.assertEqual(active_alloc.observacao_conclusao, 'Serviço executado perfeitamente')
        self.assertIsNone(self.tech.active_allocation)

    def test_multiple_pauses_relational(self):
        """Test multiple pause/resume relational history and automatic closure on completion."""
        client = Client()
        client.force_login(self.operador_user)
        
        # 1. Start Service
        client.post(
            reverse('start_service', args=[self.tech.id]),
            data={'maquina': self.machine_low.id, 'atividade_observacao': 'Conserto Geral'}
        )
        self.tech.refresh_from_db()
        alloc = self.tech.active_allocation
        self.assertIsNotNone(alloc)
        self.assertEqual(alloc.pausas.count(), 0)

        # 2. First Pause
        client.post(
            reverse('pause_service', args=[self.tech.id]),
            data={'motivo_pausa': 'Pausa 1'}
        )
        self.assertEqual(alloc.pausas.count(), 1)
        pausa1 = alloc.pausas.first()
        self.assertEqual(pausa1.motivo_pausa, 'Pausa 1')
        self.assertIsNone(pausa1.data_retorno)

        # 3. Resume
        client.post(reverse('resume_service', args=[self.tech.id]))
        pausa1.refresh_from_db()
        self.assertIsNotNone(pausa1.data_retorno)

        # 4. Second Pause
        client.post(
            reverse('pause_service', args=[self.tech.id]),
            data={'motivo_pausa': 'Pausa 2'}
        )
        self.assertEqual(alloc.pausas.count(), 2)
        pausas = alloc.pausas.order_by('data_pausa')
        pausa2 = pausas[1]
        self.assertEqual(pausa2.motivo_pausa, 'Pausa 2')
        self.assertIsNone(pausa2.data_retorno)

        # 5. Finish directly while paused
        client.post(
            reverse('finish_allocation', args=[alloc.id]),
            data={'observacao_conclusao': 'Feito'}
        )
        alloc.refresh_from_db()
        self.assertIsNotNone(alloc.data_fim)
        self.assertEqual(alloc.status, 'CONCLUIDO')
        
        # Check that the open pause is automatically closed at data_fim
        pausa2.refresh_from_db()
        self.assertEqual(pausa2.data_retorno, alloc.data_fim)

    def test_start_service_form_custom_label(self):
        """Test StartServiceForm queryset optimization and label formatting."""
        from .forms import StartServiceForm
        form = StartServiceForm()
        # Ensure 'maquina' field's queryset uses select_related('setor')
        self.assertTrue(form.fields['maquina'].queryset.query.select_related)
        
        # Test label_from_instance custom output format
        label = form.fields['maquina'].label_from_instance(self.machine_low)
        self.assertEqual(label, f"{self.machine_low.nome} [Setor: {self.sector.nome}]")

    def test_post_login_redirect(self):
        """Test redirection after login and for home_redirect view based on roles."""
        client = Client()
        
        # 1. User with Visualizador group -> tv_dashboard
        client.force_login(self.viewer_user)
        response = client.get(reverse('home_redirect'))
        self.assertRedirects(response, reverse('tv_dashboard'))
        client.logout()

        # 2. User named 'tv' -> tv_dashboard
        tv_user = User.objects.create_user('tv', 'tv@test.com', 'pwd123')
        client.force_login(tv_user)
        response = client.get(reverse('home_redirect'))
        self.assertRedirects(response, reverse('tv_dashboard'))
        client.logout()

        # 3. User with Tecnicos_Lideres group -> technician_management
        lider_user = User.objects.create_user('lider_test', 'lider@test.com', 'pwd123')
        lider_user.groups.add(self.lider_group)
        client.force_login(lider_user)
        response = client.get(reverse('home_redirect'))
        self.assertRedirects(response, reverse('technician_management'))
        client.logout()
        
        # 4. User with dual access (like operador_user or admin) -> portal_select
        client.force_login(self.operador_user)
        response = client.get(reverse('home_redirect'))
        self.assertRedirects(response, reverse('portal_select'))
        client.logout()

        # 5. User with Production access only -> production:dashboard
        prod_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        prod_user = User.objects.create_user('prod_leader_test', 'prod@test.com', 'pwd123')
        prod_user.groups.add(prod_group)
        client.force_login(prod_user)
        response = client.get(reverse('home_redirect'))
        self.assertRedirects(response, reverse('production:dashboard'))
        client.logout()

    def test_portal_select_view(self):
        """Test portal_select view permissions, rendering and automatic bypass."""
        client = Client()

        # 1. Dual-access user (operador_user) can access portal_select with 200 OK
        client.force_login(self.operador_user)
        response = client.get(reverse('portal_select'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manutenção Industrial")
        self.assertContains(response, "Produção & PCP")
        self.assertContains(response, "Selecione o Módulo de Trabalho")
        client.logout()

        # 2. Pure technician gets bypassed directly to technician_management
        tech_group, _ = Group.objects.get_or_create(name="Tecnicos")
        pure_tech = User.objects.create_user('pure_tech_test', 'ptech@test.com', 'pwd123')
        pure_tech.groups.add(tech_group)
        client.force_login(pure_tech)
        response = client.get(reverse('portal_select'))
        self.assertRedirects(response, reverse('technician_management'))
        client.logout()

        # 3. Pure production leader gets bypassed directly to production:dashboard
        prod_group, _ = Group.objects.get_or_create(name="Liderança de Produção")
        prod_user = User.objects.create_user('prod_user_bypass', 'pby@test.com', 'pwd123')
        prod_user.groups.add(prod_group)
        client.force_login(prod_user)
        response = client.get(reverse('portal_select'))
        self.assertRedirects(response, reverse('production:dashboard'))
        client.logout()

    def test_finish_service_validation_failure_redirect(self):
        """Test that validation failure in finish_service redirects back with query parameters."""
        client = Client()
        client.force_login(self.operador_user)
        
        # Start a service first
        client.post(
            reverse('start_service', args=[self.tech.id]),
            data={'maquina': self.machine_low.id, 'atividade_observacao': 'Conserto'}
        )
        self.tech.refresh_from_db()
        self.assertEqual(self.tech.status, 'EM_ATENDIMENTO')
        
        # Post to finish_service with invalid form (missing observacao_conclusao)
        response = client.post(
            reverse('finish_service', args=[self.tech.id]),
            data={}
        )
        expected_redirect = f'/management/?open_modal=finish_tech&tech_id={self.tech.id}'
        self.assertRedirects(response, expected_redirect, target_status_code=200)

    def test_finish_allocation_validation_failure_redirect(self):
        """Test that validation failure in finish_allocation redirects back with query parameters."""
        client = Client()
        client.force_login(self.operador_user)
        
        # Start a service first
        client.post(
            reverse('start_service', args=[self.tech.id]),
            data={'maquina': self.machine_low.id, 'atividade_observacao': 'Conserto'}
        )
        self.tech.refresh_from_db()
        alloc = self.tech.active_allocation
        
        # Post to finish_allocation with invalid form (missing observacao_conclusao)
        response = client.post(
            reverse('finish_allocation', args=[alloc.id]),
            data={}
        )
        expected_redirect = f'/management/?open_modal=finish_alloc&alloc_id={alloc.id}'
        self.assertRedirects(response, expected_redirect, target_status_code=200)

    def test_shift_report_view(self):
        """Test shift report view access and compilation logic."""
        client = Client()
        
        # 1. Anonymous user redirected to login
        response = client.get(reverse('relatorio_turno'))
        self.assertEqual(response.status_code, 302)
        
        # 2. Logged in user without technician profile is redirected
        client.force_login(self.operador_user)
        response = client.get(reverse('relatorio_turno'))
        self.assertRedirects(response, reverse('technician_management'))
        
        # 3. Create technician profile with linked user
        tech_user = User.objects.create_user('tech_user', 'tech@test.com', 'pwd123')
        tech_user.groups.add(self.tech_group)
        self.tech.user = tech_user
        # Add whatsapp number
        self.tech.whatsapp = "5511999999999"
        self.tech.save()
        
        # 4. Access shift report as the technician
        client.force_login(tech_user)
        response = client.get(reverse('relatorio_turno'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passagem de Turno")
        
        # 5. Verify pre-compiled report (initially no allocations, so "Sem pendências")
        self.assertIn("Técnico: Carlos Souza", response.context['texto_precompilado'])
        self.assertIn("Sem pendências para o próximo turno", response.context['texto_precompilado'])
        
        # 6. Create concluded allocation for today
        now = timezone.now()
        Allocation.objects.create(
            tecnico=self.tech,
            maquina=self.machine_low,
            atividade_observacao="CheckingTorne",
            status="CONCLUIDO",
            data_inicio=now - timedelta(hours=2),
            data_fim=now - timedelta(hours=1),
            observacao_conclusao="Troca de correia efetuada"
        )
        
        # 7. Create paused allocation for today
        Allocation.objects.create(
            tecnico=self.tech,
            maquina=self.machine_high,
            atividade_observacao="Prensa reparo",
            status="EM_PAUSA",
            data_inicio=now - timedelta(hours=1),
            data_pausa=now - timedelta(minutes=30),
            motivo_pausa="Aguardando peça"
        )

        # 7b. Create an allocation older than 12 hours (should be excluded)
        Allocation.objects.create(
            tecnico=self.tech,
            maquina=self.machine_low,
            atividade_observacao="ServicoAntigo",
            status="CONCLUIDO",
            data_inicio=now - timedelta(hours=14),
            data_fim=now - timedelta(hours=13),
            observacao_conclusao="Servico antigo concluido"
        )

        # 7c. Create an allocation started 14 hours ago but finished 10 hours ago (should be included because data_fim >= now - 12h)
        Allocation.objects.create(
            tecnico=self.tech,
            maquina=self.machine_low,
            atividade_observacao="ServicoCruzouJanela",
            status="CONCLUIDO",
            data_inicio=now - timedelta(hours=14),
            data_fim=now - timedelta(hours=10),
            observacao_conclusao="Servico que cruzou a janela"
        )

        response = client.get(reverse('relatorio_turno'))
        self.assertEqual(response.status_code, 200)
        report_text = response.context['texto_precompilado']
        self.assertIn("* Torno CNC - Troca de correia efetuada", report_text)
        self.assertIn("* Prensa Hidráulica - Em Pausa - Aguardando peça", report_text)
        self.assertIn("Servico que cruzou a janela", report_text)
        self.assertNotIn("Servico antigo concluido", report_text)
        
        # 8. Post form submission simulates success with mocked requests
        from unittest.mock import patch, MagicMock
        
        # Create test whatsapp group in database
        WhatsAppGroup.objects.create(nome="Grupo Geral", jid="123456789@g.us", is_active=True)
        
        # Test case: WhatsApp microservice returns HTTP 202 (standard queued success)
        mock_response_success = MagicMock()
        mock_response_success.status_code = 202
        
        with patch('requests.post', return_value=mock_response_success) as mock_post:
            response = client.post(reverse('relatorio_turno'), data={
                'texto_relatorio': report_text,
                'destino': 'meu_numero'
            })
            self.assertRedirects(response, reverse('relatorio_turno'))
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(kwargs['json']['numero'], "5511999999999")
            self.assertEqual(kwargs['json']['mensagem'], report_text)

        # Test case: WhatsApp group JID destination
        with patch('requests.post', return_value=mock_response_success) as mock_post:
            response = client.post(reverse('relatorio_turno'), data={
                'texto_relatorio': report_text,
                'destino': '123456789@g.us'
            })
            self.assertRedirects(response, reverse('relatorio_turno'))
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(kwargs['json']['numero'], "123456789@g.us")

        # Test case: WhatsApp microservice returns HTTP 429 (Rate Limit)
        mock_response_rate_limit = MagicMock()
        mock_response_rate_limit.status_code = 429
        
        with patch('requests.post', return_value=mock_response_rate_limit) as mock_post:
            response = client.post(reverse('relatorio_turno'), data={
                'texto_relatorio': report_text,
                'destino': 'meu_numero'
            })
            self.assertRedirects(response, reverse('relatorio_turno'))
            mock_post.assert_called_once()

        # Test case: WhatsApp microservice returns HTTP 503 (Circuit Breaker Tripped)
        mock_response_cb = MagicMock()
        mock_response_cb.status_code = 503
        mock_response_cb.json.return_value = {'error': 'Serviço temporariamente indisponível'}
        
        with patch('requests.post', return_value=mock_response_cb) as mock_post:
            response = client.post(reverse('relatorio_turno'), data={
                'texto_relatorio': report_text,
                'destino': 'meu_numero'
            })
            self.assertRedirects(response, reverse('relatorio_turno'))
            mock_post.assert_called_once()

        # Test case: WhatsApp microservice returns HTTP 503/error (General)
        mock_response_error = MagicMock()
        mock_response_error.status_code = 503
        mock_response_error.json.side_effect = ValueError()
        
        with patch('requests.post', return_value=mock_response_error) as mock_post:
            response = client.post(reverse('relatorio_turno'), data={
                'texto_relatorio': report_text,
                'destino': 'meu_numero'
            })
            self.assertRedirects(response, reverse('relatorio_turno'))
            mock_post.assert_called_once()

        # Test case: Connection timeout/error raises RequestException
        import requests
        with patch('requests.post', side_effect=requests.exceptions.ConnectionError("Connection refused")) as mock_post:
            response = client.post(reverse('relatorio_turno'), data={
                'texto_relatorio': report_text,
                'destino': 'meu_numero'
            })
            self.assertRedirects(response, reverse('relatorio_turno'))
            mock_post.assert_called_once()

    def test_dashboard_access_restriction(self):
        """Test that only operators/admins can access dashboard and excel export, while lideres are blocked."""
        client = Client()
        
        # Create a leader user
        lider_user = User.objects.create_user('lider_test_dash', 'lider_dash@test.com', 'pwd123')
        lider_user.groups.add(self.lider_group)
        
        # 1. Anonymous user redirected to login
        response = client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        
        response = client.get(reverse('exportar_relatorio_excel'))
        self.assertEqual(response.status_code, 302)
        
        # 2. Leader user (Tecnico Lider) is blocked and redirected to technician_management
        client.force_login(lider_user)
        response = client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('technician_management'))
        
        response = client.get(reverse('exportar_relatorio_excel'))
        self.assertRedirects(response, reverse('technician_management'))
        client.logout()
        
        # 3. Operator user can access both dashboard and export
        client.force_login(self.operador_user)
        response = client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        response = client.get(reverse('exportar_relatorio_excel'))
        self.assertEqual(response.status_code, 200)

    def test_elapsed_time_with_multiple_pauses(self):
        """Test that net elapsed time correctly subtracts relational pause durations."""
        now = timezone.now()
        # Create allocation started 60 minutes ago
        alloc = Allocation.objects.create(
            tecnico=self.tech,
            maquina=self.machine_low,
            atividade_observacao="Test multiple pauses",
            data_inicio=now - timedelta(minutes=60)
        )
        
        # Initially, no pauses, elapsed time should be 60m
        self.assertEqual(alloc.tempo_decorrido_str, "1h 0m")
        
        # Add a completed pause: from 45m ago to 15m ago (duration = 30m)
        HistoricoPausa.objects.create(
            alocacao=alloc,
            data_pausa=now - timedelta(minutes=45),
            data_retorno=now - timedelta(minutes=15),
            motivo_pausa="First pause completed"
        )
        
        # Brute: 60m. Pauses: 30m. Net should be 30m.
        self.assertEqual(alloc.tempo_decorrido_str, "30m")
        
        # Add another active pause: started 10 minutes ago
        p_active = HistoricoPausa.objects.create(
            alocacao=alloc,
            data_pausa=now - timedelta(minutes=10),
            motivo_pausa="Second pause active"
        )
        
        # Since it is currently active, duration is now - p_active.data_pausa = 10m.
        # Total pauses: 30m + 10m = 40m.
        # Net should be 60m - 40m = 20m.
        self.assertEqual(alloc.tempo_decorrido_str, "20m")
        
        # Close the second pause (resumed 5 minutes ago)
        p_active.data_retorno = now - timedelta(minutes=5)
        p_active.save()
        
        # Pause 1: 30m. Pause 2: 5m. Total pauses: 35m.
        # Net should be 60m - 35m = 25m.
        self.assertEqual(alloc.tempo_decorrido_str, "25m")


import tempfile
import shutil
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

class ProtectedMediaTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.mkdtemp()

        # Groups
        self.operator_group, _ = Group.objects.get_or_create(name='Operadores')
        self.tech_group, _ = Group.objects.get_or_create(name='Tecnicos')
        self.lider_group, _ = Group.objects.get_or_create(name='Tecnicos_Lideres')
        self.prod_group, _ = Group.objects.get_or_create(name='Liderança de Produção')

        # Users
        self.operador_user = User.objects.create_user('op_media', 'op@test.com', 'pwd123')
        self.operador_user.groups.add(self.operator_group)

        self.tech1_user = User.objects.create_user('tech1_media', 't1@test.com', 'pwd123')
        self.tech1_user.groups.add(self.tech_group)

        self.tech2_user = User.objects.create_user('tech2_media', 't2@test.com', 'pwd123')
        self.tech2_user.groups.add(self.tech_group)

        self.prod_user = User.objects.create_user('prod_media', 'prod@test.com', 'pwd123')
        self.prod_user.groups.add(self.prod_group)

        # Domain data
        self.sector = Sector.objects.create(nome="Linha 01")
        self.machine = Machine.objects.create(nome="Prensa", setor=self.sector)

        # Technicians
        self.tech1 = Technician.objects.create(nome="Tecnico 1", matricula="T-01", status="OCIOSO", user=self.tech1_user, perfil="TECNICO")
        self.tech2 = Technician.objects.create(nome="Tecnico 2", matricula="T-02", status="OCIOSO", user=self.tech2_user, perfil="TECNICO")

        # Fake image file for upload testing
        self.dummy_image = SimpleUploadedFile(
            "test_photo.png",
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4",
            content_type="image/png"
        )

        # Allocation with valid photo
        self.alloc_with_photo = Allocation.objects.create(
            tecnico=self.tech1,
            maquina=self.machine,
            atividade_observacao="Manutenção com foto",
            data_inicio=timezone.now(),
            foto_anexo=self.dummy_image
        )

        # Allocation without photo
        self.alloc_no_photo = Allocation.objects.create(
            tecnico=self.tech1,
            maquina=self.machine,
            atividade_observacao="Manutenção sem foto",
            data_inicio=timezone.now()
        )

    def tearDown(self):
        if hasattr(self, 'alloc_with_photo') and self.alloc_with_photo.foto_anexo:
            try:
                self.alloc_with_photo.foto_anexo.close()
            except Exception:
                pass
            try:
                self.alloc_with_photo.foto_anexo.delete(save=False)
            except Exception:
                pass
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_anonymous_access_redirects_to_login(self):
        """1. Usuário anônimo deve ser redirecionado para o login."""
        client = Client()
        url = reverse('serve_allocation_attachment', args=[self.alloc_with_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_authorized_tech_can_access_attachment(self):
        """2, 9, 10, 11. Técnico dono da alocação acessa anexo com cabeçalhos corretos."""
        client = Client()
        client.force_login(self.tech1_user)
        url = reverse('serve_allocation_attachment', args=[self.alloc_with_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('inline;', response['Content-Disposition'])
        response.close()

    def test_unauthorized_tech_cannot_access_attachment(self):
        """3. Técnico tentando acessar foto de outro técnico recebe HTTP 403."""
        client = Client()
        client.force_login(self.tech2_user)
        url = reverse('serve_allocation_attachment', args=[self.alloc_with_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_operator_can_access_any_attachment(self):
        """4. Operador pode acessar anexo de qualquer alocação."""
        client = Client()
        client.force_login(self.operador_user)
        url = reverse('serve_allocation_attachment', args=[self.alloc_with_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_production_user_blocked(self):
        """5. Usuário da Produção é bloqueado (HTTP 403)."""
        client = Client()
        client.force_login(self.prod_user)
        url = reverse('serve_allocation_attachment', args=[self.alloc_with_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_nonexistent_allocation_404(self):
        """6. Alocação inexistente retorna HTTP 404."""
        client = Client()
        client.force_login(self.operador_user)
        url = reverse('serve_allocation_attachment', args=[999999])
        response = client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_allocation_without_photo_404(self):
        """7. Registro sem foto em foto_anexo retorna HTTP 404."""
        client = Client()
        client.force_login(self.operador_user)
        url = reverse('serve_allocation_attachment', args=[self.alloc_no_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_missing_file_on_storage_404(self):
        """8. Foto registrada no banco mas com arquivo ausente em disco retorna HTTP 404 sem 500."""
        client = Client()
        client.force_login(self.operador_user)
        if self.alloc_with_photo.foto_anexo.storage.exists(self.alloc_with_photo.foto_anexo.name):
            self.alloc_with_photo.foto_anexo.storage.delete(self.alloc_with_photo.foto_anexo.name)
        url = reverse('serve_allocation_attachment', args=[self.alloc_with_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 404)

    @override_settings(DEBUG=False)
    def test_media_url_returns_404_when_debug_false(self):
        """12. A rota pública /media/... retorna 404 quando DEBUG=False."""
        client = Client()
        response = client.get("/media/alocacoes/qualquer_foto.jpg")
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_prevention(self):
        """13. Impossibilidade de path traversal (rota usa apenas ID numérico do ORM)."""
        client = Client()
        client.force_login(self.operador_user)
        response = client.get("/anexos/alocacoes/../1/")
        self.assertEqual(response.status_code, 404)

    def test_scada_db_unmodified(self):
        """14. Nenhuma consulta ou alteração ocorre na base de dados SCADA durante o acesso à mídia."""
        client = Client()
        client.force_login(self.operador_user)
        url = reverse('serve_allocation_attachment', args=[self.alloc_with_photo.id])
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        from django.db import connections
        scada_queries = connections['scada'].queries
        self.assertEqual(len(scada_queries), 0)
        response.close()


class FaltasETecnicosInativosTestCase(TestCase):
    def setUp(self):
        self.operator_group, _ = Group.objects.get_or_create(name='Operadores')
        self.operador_user = User.objects.create_user('operador_test_spec', 'op@test.com', 'pwd123')
        self.operador_user.groups.add(self.operator_group)

        self.sector = Sector.objects.create(nome="Usinagem")
        self.machine = Machine.objects.create(nome="Torno 01", setor=self.sector, criticidade="BAIXA")

        self.tech_ativo = Technician.objects.create(
            nome="Tecnico Ativo",
            matricula="TEC-ACT-01",
            status="OCIOSO",
            is_active=True
        )

    def test_novos_status_ausencia_choices_and_properties(self):
        """Verifica se os novos status de falta estão presentes nas choices e em STATUS_AUSENCIA."""
        status_dict = dict(Technician.STATUS_CHOICES)
        self.assertIn('AUSENTE_FALTA_JUSTIFICADA', status_dict)
        self.assertIn('AUSENTE_FALTA_NAO_JUSTIFICADA', status_dict)
        self.assertEqual(status_dict['AUSENTE_FALTA_JUSTIFICADA'], 'Ausente – Falta Justificada')
        self.assertEqual(status_dict['AUSENTE_FALTA_NAO_JUSTIFICADA'], 'Ausente – Falta Não Justificada')

        tech = Technician(nome="Test Absence", matricula="T-ABS", status="AUSENTE_FALTA_JUSTIFICADA")
        self.assertTrue(tech.is_ausente)

        tech.status = "AUSENTE_FALTA_NAO_JUSTIFICADA"
        self.assertTrue(tech.is_ausente)

    def test_bloqueio_alocacao_novos_status(self):
        """Técnicos marcados com falta não podem receber novas ordens de serviço."""
        client = Client()
        client.force_login(self.operador_user)

        for status_falta in ['AUSENTE_FALTA_JUSTIFICADA', 'AUSENTE_FALTA_NAO_JUSTIFICADA']:
            self.tech_ativo.status = status_falta
            self.tech_ativo.save()

            response = client.post(
                reverse('start_service', args=[self.tech_ativo.id]),
                {'maquina': self.machine.id, 'atividade_observacao': 'Manutenção preventiva'}
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(Allocation.objects.filter(tecnico=self.tech_ativo).count(), 0)

    def test_set_availability_novos_status_e_historico_escala(self):
        """Altera disponibilidade para Falta Justificada/Não Justificada e verifica HistoricoEscala e retorno a OCIOSO."""
        client = Client()
        client.force_login(self.operador_user)

        # Definição para Falta Justificada
        response = client.post(
            reverse('set_availability', args=[self.tech_ativo.id]),
            {'novo_status': 'AUSENTE_FALTA_JUSTIFICADA'}
        )
        self.assertEqual(response.status_code, 302)
        self.tech_ativo.refresh_from_db()
        self.assertEqual(self.tech_ativo.status, 'AUSENTE_FALTA_JUSTIFICADA')

        hist = HistoricoEscala.objects.filter(tecnico=self.tech_ativo).first()
        self.assertIsNotNone(hist)
        self.assertEqual(hist.status_definido, 'AUSENTE_FALTA_JUSTIFICADA')
        self.assertEqual(hist.usuario_responsavel, self.operador_user)

        # Definição para Falta Não Justificada
        response = client.post(
            reverse('set_availability', args=[self.tech_ativo.id]),
            {'novo_status': 'AUSENTE_FALTA_NAO_JUSTIFICADA'}
        )
        self.assertEqual(response.status_code, 302)
        self.tech_ativo.refresh_from_db()
        self.assertEqual(self.tech_ativo.status, 'AUSENTE_FALTA_NAO_JUSTIFICADA')

        # Retorno para Disponível (Ocioso)
        response = client.post(
            reverse('set_availability', args=[self.tech_ativo.id]),
            {'novo_status': 'OCIOSO'}
        )
        self.assertEqual(response.status_code, 302)
        self.tech_ativo.refresh_from_db()
        self.assertEqual(self.tech_ativo.status, 'OCIOSO')

    def test_technician_is_active_default(self):
        """Garante que novos técnicos possuem is_active=True por padrão."""
        new_tech = Technician.objects.create(nome="Novo Tec", matricula="TEC-DEF-01")
        self.assertTrue(new_tech.is_active)

    def test_listagem_operacional_apenas_tecnicos_ativos(self):
        """Técnicos inativos não aparecem em /management/ nem em /tv/."""
        tech_inativo = Technician.objects.create(
            nome="Tecnico Desligado",
            matricula="TEC-OFF-01",
            is_active=False
        )

        client = Client()
        client.force_login(self.operador_user)

        # Verificação no /management/
        res_mgmt = client.get(reverse('technician_management'))
        self.assertEqual(res_mgmt.status_code, 200)
        self.assertContains(res_mgmt, self.tech_ativo.nome)
        self.assertNotContains(res_mgmt, tech_inativo.nome)

        # Verificação no /tv/
        res_tv = client.get(reverse('tv_dashboard'))
        self.assertEqual(res_tv.status_code, 200)
        self.assertContains(res_tv, self.tech_ativo.nome)
        self.assertNotContains(res_tv, tech_inativo.nome)

    def test_bloqueio_atribuicao_tecnico_inativo(self):
        """Tentativa de iniciar ordem para técnico inativo via backend é bloqueada."""
        tech_inativo = Technician.objects.create(
            nome="Tecnico Inativo POST",
            matricula="TEC-OFF-02",
            is_active=False
        )

        client = Client()
        client.force_login(self.operador_user)

        response = client.post(
            reverse('start_service', args=[tech_inativo.id]),
            {'maquina': self.machine.id, 'atividade_observacao': 'Tentativa em inativo'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Allocation.objects.filter(tecnico=tech_inativo).count(), 0)

    def test_bloqueio_inativacao_tecnico_com_atendimento_ativo(self):
        """Impossibilita marcar técnico como inativo enquanto possuir atendimento EM_ATENDIMENTO."""
        now = timezone.now()
        Allocation.objects.create(
            tecnico=self.tech_ativo,
            maquina=self.machine,
            atividade_observacao="Serviço Ativo Teste",
            data_inicio=now,
            status='EM_ATENDIMENTO'
        )
        self.tech_ativo.status = 'EM_ATENDIMENTO'
        self.tech_ativo.save()

        self.tech_ativo.is_active = False
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.tech_ativo.clean()

    def test_bloqueio_inativacao_tecnico_com_atendimento_pausado(self):
        """Impossibilita marcar técnico como inativo enquanto possuir atendimento EM_PAUSA."""
        now = timezone.now()
        Allocation.objects.create(
            tecnico=self.tech_ativo,
            maquina=self.machine,
            atividade_observacao="Serviço Pausado Teste",
            data_inicio=now - timedelta(hours=1),
            data_pausa=now - timedelta(minutes=30),
            motivo_pausa="Aguardando peça",
            status='EM_PAUSA'
        )
        self.tech_ativo.status = 'EM_PAUSA'
        self.tech_ativo.save()

        self.tech_ativo.is_active = False
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.tech_ativo.clean()

    def test_inativacao_e_reativacao_sucesso(self):
        """Técnico sem atendimentos em aberto pode ser inativado e reativado com sucesso."""
        self.tech_ativo.is_active = False
        self.tech_ativo.save()
        self.tech_ativo.refresh_from_db()
        self.assertFalse(self.tech_ativo.is_active)

        self.tech_ativo.is_active = True
        self.tech_ativo.save()
        self.tech_ativo.refresh_from_db()
        self.assertTrue(self.tech_ativo.is_active)

    def test_preservacao_dados_historicos(self):
        """Técnicos inativos mantêm suas alocações históricas e aparecem nos relatórios de período."""
        now = timezone.now()
        tech_historico = Technician.objects.create(
            nome="Tecnico Antigo",
            matricula="TEC-HIST-01",
            is_active=True
        )
        alloc = Allocation.objects.create(
            tecnico=tech_historico,
            maquina=self.machine,
            atividade_observacao="Reparo histórico concluído",
            data_inicio=now - timedelta(days=2),
            data_fim=now - timedelta(days=2, hours=-2),
            observacao_conclusao="Encerrado com sucesso",
            status='CONCLUIDO'
        )

        # Inativa o técnico após a conclusão da Ordem de Serviço
        tech_historico.is_active = False
        tech_historico.save()

        # A alocação histórica continua vinculada intacta
        alloc.refresh_from_db()
        self.assertEqual(alloc.tecnico.nome, "Tecnico Antigo")
        self.assertFalse(alloc.tecnico.is_active)

        # Verifica acesso ao dashboard/relatórios de período
        client = Client()
        client.force_login(self.operador_user)
        res = client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 200)

    def test_admin_tecnico_list_display_and_filter(self):
        """Valida que o admin do Técnico registra is_active em list_display e list_filter."""
        from maintenance.admin import TecnicoAdmin
        self.assertIn('is_active', TecnicoAdmin.list_display)
        self.assertIn('is_active', TecnicoAdmin.list_filter)


class AllocationProgressUpdateTestCase(TestCase):
    def setUp(self):
        self.operator_group, _ = Group.objects.get_or_create(name='Operadores')
        self.tech_group, _ = Group.objects.get_or_create(name='Técnicos')

        self.user_op = User.objects.create_user('operator_06c', 'op06c@test.com', 'pwd123')
        self.user_op.groups.add(self.operator_group)

        self.user_tech1 = User.objects.create_user('tech1_06c', 't106c@test.com', 'pwd123')
        self.user_tech1.groups.add(self.tech_group)

        self.user_tech2 = User.objects.create_user('tech2_06c', 't206c@test.com', 'pwd123')
        self.user_tech2.groups.add(self.tech_group)

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 01", setor=self.sector)

        self.tech1 = Technician.objects.create(nome="Técnico 1", matricula="M01", status="EM_ATENDIMENTO", user=self.user_tech1, perfil="TECNICO")
        self.tech2 = Technician.objects.create(nome="Técnico 2", matricula="M02", status="EM_ATENDIMENTO", user=self.user_tech2, perfil="TECNICO")

        self.alloc1 = Allocation.objects.create(
            tecnico=self.tech1,
            maquina=self.machine,
            atividade_observacao="Manutenção de Prensa",
            data_inicio=timezone.now(),
            status="EM_ATENDIMENTO"
        )
        self.alloc2 = Allocation.objects.create(
            tecnico=self.tech2,
            maquina=self.machine,
            atividade_observacao="Troca de válvula",
            data_inicio=timezone.now(),
            status="EM_ATENDIMENTO"
        )

    def test_tech1_can_add_progress_update_to_own_allocation(self):
        """Técnico adiciona nota de progresso parcial em sua própria alocação."""
        client = Client()
        client.force_login(self.user_tech1)
        url = reverse('add_allocation_progress_update', kwargs={'allocation_id': self.alloc1.id})
        res = client.post(url, {'descricao': 'Substituída primeira vedação.'})

        self.assertEqual(res.status_code, 302)
        self.assertEqual(AllocationProgressUpdate.objects.filter(allocation=self.alloc1).count(), 1)
        pu = AllocationProgressUpdate.objects.get(allocation=self.alloc1)
        self.assertEqual(pu.descricao, 'Substituída primeira vedação.')
        self.assertEqual(pu.autor, self.user_tech1)

        # Garante que o status da alocação não foi alterado
        self.alloc1.refresh_from_db()
        self.assertEqual(self.alloc1.status, 'EM_ATENDIMENTO')

    def test_tech1_cannot_add_progress_update_to_other_tech_allocation(self):
        """Técnico tenta adicionar nota na alocação de outro técnico e é bloqueado."""
        client = Client()
        client.force_login(self.user_tech1)
        url = reverse('add_allocation_progress_update', kwargs={'allocation_id': self.alloc2.id})
        res = client.post(url, {'descricao': 'Tentativa não autorizada.'})

        self.assertEqual(res.status_code, 302)
        self.assertEqual(AllocationProgressUpdate.objects.filter(allocation=self.alloc2).count(), 0)

    def test_blank_description_is_rejected(self):
        """Descrição vazia ou contendo apenas espaços deve ser rejeitada."""
        client = Client()
        client.force_login(self.user_tech1)
        url = reverse('add_allocation_progress_update', kwargs={'allocation_id': self.alloc1.id})
        res = client.post(url, {'descricao': '   '})

        self.assertEqual(res.status_code, 302)
        self.assertEqual(AllocationProgressUpdate.objects.filter(allocation=self.alloc1).count(), 0)

    def test_operator_can_add_progress_update_to_any_allocation(self):
        """Operador/Admin pode incluir notas de progresso em qualquer alocação."""
        client = Client()
        client.force_login(self.user_op)
        url = reverse('add_allocation_progress_update', kwargs={'allocation_id': self.alloc2.id})
        res = client.post(url, {'descricao': 'Operador registrou prioridade.'})

        self.assertEqual(res.status_code, 302)
        self.assertEqual(AllocationProgressUpdate.objects.filter(allocation=self.alloc2).count(), 1)
        pu = AllocationProgressUpdate.objects.get(allocation=self.alloc2)
        self.assertEqual(pu.autor, self.user_op)


class OrdemServicoModelAndAdminTestCase(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser('admin_os', 'admin_os@test.com', 'pwd123')
        self.operator_user = User.objects.create_user('operador_os', 'operador_os@test.com', 'pwd123')
        
        self.sector = Sector.objects.create(nome="Estamparia")
        self.machine = Machine.objects.create(nome="Prensa Hidráulica 500T", setor=self.sector, criticidade="ALTA")
        
        self.tech1 = Technician.objects.create(nome="Lucas Silva", matricula="TEC-101", status="OCIOSO")
        self.tech2 = Technician.objects.create(nome="Mariana Costa", matricula="TEC-102", status="OCIOSO")
        
        self.os = OrdemServico.objects.create(
            numero_os="OS-1001",
            maquina=self.machine,
            setor=self.sector,
            solicitante="Líder Roberto",
            tipo_manutencao="CORRETIVA",
            criticidade="ALTA",
            descricao_falha="Vazamento hidráulico no pistão principal.",
            status="PENDENTE",
            criado_por=self.operator_user,
            tecnico_designado=self.tech1
        )

    def test_ordem_servico_creation_and_uniqueness(self):
        """Valida criação correta e bloqueio de número de OS duplicado."""
        self.assertEqual(self.os.numero_os, "OS-1001")
        self.assertEqual(self.os.maquina, self.machine)
        self.assertEqual(self.os.setor, self.sector)
        self.assertIn("OS #OS-1001", str(self.os))

        # Tentar cadastrar outra OS com o mesmo número deve levantar IntegrityError
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            OrdemServico.objects.create(
                numero_os="OS-1001",
                solicitante="Outro Líder",
                descricao_falha="Falha duplicada",
            )

    def test_ordem_servico_multiple_technicians_allocations(self):
        """Valida que múltiplos técnicos e alocações podem ser vinculados à mesma OS."""
        now = timezone.now()
        alloc1 = Allocation.objects.create(
            ordem_servico=self.os,
            tecnico=self.tech1,
            maquina=self.machine,
            atividade_observacao="Desmontagem da válvula",
            status="CONCLUIDO",
            data_inicio=now - timedelta(hours=2),
            data_fim=now - timedelta(hours=1)
        )
        alloc2 = Allocation.objects.create(
            ordem_servico=self.os,
            tecnico=self.tech2,
            maquina=self.machine,
            atividade_observacao="Troca de retentores",
            status="CONCLUIDO",
            data_inicio=now - timedelta(hours=1),
            data_fim=now
        )

        self.assertEqual(self.os.allocations.count(), 2)
        tecnicos = self.os.tecnicos_envolvidos
        self.assertEqual(len(tecnicos), 2)
        self.assertIn(self.tech1, tecnicos)
        self.assertIn(self.tech2, tecnicos)

    def test_ordem_servico_properties_and_time_calculation(self):
        """Valida cálculo de homem-hora, status de inicialização e tempo total de intervenção."""
        now = timezone.now()
        
        # 1. pode_ser_iniciada
        self.os.status = "PENDENTE"
        self.assertTrue(self.os.pode_ser_iniciada)
        self.os.status = "EM_ANDAMENTO"
        self.assertTrue(self.os.pode_ser_iniciada)
        self.os.status = "CONCLUIDA"
        self.assertFalse(self.os.pode_ser_iniciada)
        self.os.status = "CANCELADA"
        self.assertFalse(self.os.pode_ser_iniciada)

        # 2. Homem-hora acumulado com pausas
        # Alocação 1: 60 minutos contínuos (1h = 3600s)
        alloc1 = Allocation.objects.create(
            ordem_servico=self.os,
            tecnico=self.tech1,
            maquina=self.machine,
            atividade_observacao="Serviço 1",
            status="CONCLUIDO",
            data_inicio=now - timedelta(minutes=120),
            data_fim=now - timedelta(minutes=60)
        )
        # Alocação 2: 60 minutos brutos com pausa de 20 minutos (líquido = 40 min = 2400s)
        alloc2 = Allocation.objects.create(
            ordem_servico=self.os,
            tecnico=self.tech2,
            maquina=self.machine,
            atividade_observacao="Serviço 2",
            status="CONCLUIDO",
            data_inicio=now - timedelta(minutes=60),
            data_fim=now
        )
        HistoricoPausa.objects.create(
            alocacao=alloc2,
            data_pausa=now - timedelta(minutes=40),
            data_retorno=now - timedelta(minutes=20),
            motivo_pausa="Aguardando peça do almoxarifado"
        )

        # Total HH: 3600 + 2400 = 6000s = 1h 40m
        self.assertEqual(self.os.tempo_total_homem_hora_segundos, 6000)
        self.assertEqual(self.os.tempo_total_homem_hora_str, "1h 40m")

        # Tempo total de intervenção dicionário
        info = self.os.tempo_total_intervencao
        self.assertEqual(info['homem_hora_segundos'], 6000)
        self.assertEqual(info['homem_hora_str'], "1h 40m")
        self.assertIn('tempo_parada_segundos', info)
        self.assertIn('tempo_parada_str', info)

    def test_allocation_backwards_compatibility(self):
        """Valida que alocações sem Ordem de Serviço (ordem_servico=None) continuam 100% funcionais."""
        now = timezone.now()
        alloc = Allocation.objects.create(
            tecnico=self.tech1,
            maquina=self.machine,
            atividade_observacao="Atendimento legado sem OS",
            status="CONCLUIDO",
            data_inicio=now - timedelta(minutes=30),
            data_fim=now
        )
        self.assertIsNone(alloc.ordem_servico)
        self.assertEqual(alloc.tempo_decorrido_liquido, "30m")
        self.assertIn("Lucas Silva em Prensa Hidráulica 500T", str(alloc))

    def test_admin_ordem_servico_and_inlines(self):
        """Valida registro no Django Admin, inlines, métodos auxiliares e list_display."""
        from django.contrib import admin
        from maintenance.admin import OrdemServicoAdmin, AlocacaoAdmin, AllocationInline, OrdemServicoPecaInline

        # Verifica se OrdemServico está registrada no admin
        self.assertIn(OrdemServico, admin.site._registry)
        model_admin = admin.site._registry[OrdemServico]
        self.assertIsInstance(model_admin, OrdemServicoAdmin)

        # Valida campos de listagem, busca e filtro
        self.assertIn('numero_os', OrdemServicoAdmin.list_display)
        self.assertIn('status', OrdemServicoAdmin.list_filter)
        self.assertIn('numero_os', OrdemServicoAdmin.search_fields)
        self.assertEqual(OrdemServicoAdmin.date_hierarchy, 'data_abertura')

        # Valida presença dos Inlines
        self.assertIn(AllocationInline, OrdemServicoAdmin.inlines)
        self.assertIn(OrdemServicoPecaInline, OrdemServicoAdmin.inlines)

        # Valida métodos utilitários do Admin (miniaturas e tempos)
        thumb_abertura = model_admin.exibir_foto_abertura_thumb(self.os)
        self.assertIn("Sem foto", str(thumb_abertura))
        thumb_conclusao = model_admin.exibir_foto_conclusao_thumb(self.os)
        self.assertIn("Sem foto", str(thumb_conclusao))

        hh_display = model_admin.tempo_total_homem_hora_display(self.os)
        self.assertEqual(hh_display, "0m")

        parada_display = model_admin.tempo_liquido_parada_display(self.os)
        self.assertIn("m", parada_display)

        # Valida AlocacaoAdmin exibindo ordem_servico
        self.assertIn('ordem_servico', AlocacaoAdmin.list_display)
        self.assertIn('ordem_servico', AlocacaoAdmin.list_filter)

    def test_physical_form_fields_and_pecas_utilizadas(self):
        """Valida todos os campos da folha física real e relacionamento com peças utilizadas."""
        now = timezone.now()
        os_fisica = OrdemServico.objects.create(
            numero_os="10216",
            tag="PREN-01",
            descricao_equipamento="Prensa Vulcanizadora 10",
            motivo="Vazamento de vapor no cabeçote",
            tipo_manutencao="CORRETIVA",
            parou_maquina=True,
            descricao_falha="Trocar junta de vedação e reapertar prisioneiros",
            data_hora_inicio_ocorrencia=now - timedelta(hours=3),
            causa="Desgaste prematuro da junta térmica",
            descricao_servico_realizado="Substituída junta térmica e calibrada pressão",
            data_hora_inicio_conserto=now - timedelta(hours=2),
            data_hora_fim_conserto=now - timedelta(hours=1),
            data_hora_fim_ocorrencia=now - timedelta(minutes=30),
            visto_executante_nome="Carlos Técnico",
            visto_executante_data=(now - timedelta(hours=1)).date(),
            visto_responsavel_nome="Roberto Líder",
            visto_responsavel_data=now.date(),
            status="CONCLUIDA"
        )

        # Criação de peças utilizadas
        p1 = OrdemServicoPeca.objects.create(
            ordem_servico=os_fisica,
            codigo="JUN-001",
            descricao="Junta Térmica 3/4",
            quantidade=2
        )
        p2 = OrdemServicoPeca.objects.create(
            ordem_servico=os_fisica,
            codigo="VED-005",
            descricao="Fita Teflon Alta Temperatura",
            quantidade=1
        )

        self.assertEqual(os_fisica.pecas_utilizadas.count(), 2)
        self.assertIn("Junta Térmica 3/4", str(p1))
        self.assertEqual(os_fisica.tempo_conserto_str, "1h 0m")
        self.assertEqual(os_fisica.tempo_liquido_parada_str, "2h 30m")
        self.assertTrue(os_fisica.parou_maquina)


class OrdemServicoOCRTestCase(TestCase):
    def setUp(self):
        from unittest.mock import patch
        self.user = User.objects.create_user('operador_ocr', 'ocr@test.com', 'pwd123')
        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa Vulcanizadora 10", setor=self.sector, criticidade="ALTA")

    def test_os_ocr_fallback_when_key_missing(self):
        """Valida que sem GEMINI_API_KEY a função retorna erro amigável sem lançar exceção."""
        from maintenance.services.os_ocr_service import extrair_dados_os_por_foto
        res = extrair_dados_os_por_foto(b"fake_image_bytes", api_key="")
        self.assertFalse(res["sucesso"])
        self.assertEqual(res["motivo"], "CHAVE_NAO_CONFIGURADA")
        self.assertIn("não configurada", res["mensagem"])

    def test_casar_maquina_e_setor(self):
        """Valida o algoritmo de casamento de máquina e setor com variações de texto."""
        from maintenance.services.os_ocr_service import casar_maquina_e_setor
        
        # 1. Casamento com nome aproximado / minúsculas
        maq, sec = casar_maquina_e_setor(maquina_texto="prensa vulcanizadora 10", setor_texto="vulcanizacao")
        self.assertEqual(maq, self.machine)
        self.assertEqual(sec, self.sector)

        # 2. Casamento com TAG
        Machine.objects.create(nome="PREN-05", setor=self.sector)
        maq2, sec2 = casar_maquina_e_setor(tag_texto="PREN-05")
        self.assertEqual(maq2.nome, "PREN-05")
        self.assertEqual(sec2, self.sector)

    def test_os_ocr_success_mock(self):
        """Valida extração bem-sucedida mockando a resposta da API do Gemini Vision."""
        from unittest.mock import patch, MagicMock
        from maintenance.services.os_ocr_service import extrair_dados_os_por_foto

        mock_gemini_json = {
            "numero_os": "10216",
            "tag": "PREN-10",
            "descricao_equipamento": "Prensa Vulcanizadora 10",
            "motivo": "Vazamento de vapor",
            "tipo_manutencao": "CORRETIVA",
            "parou_maquina": True,
            "descricao_falha": "Troca de junta da tubulação",
            "data_inicio_ocorrencia": "2026-08-20",
            "hora_inicio_ocorrencia": "08:30",
            "solicitante": "Líder Carlos",
            "causa": "Junta rompida por fadiga",
            "descricao_servico_realizado": "Instalada nova junta e testada estanqueidade",
            "pecas_utilizadas": [
                {"codigo": "JUN-001", "descricao": "Junta de Vedação", "quantidade": 1.0}
            ],
            "confianca_leitura": "ALTA"
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": json.dumps(mock_gemini_json)}
                        ]
                    }
                }
            ]
        }

        with patch("requests.post", return_value=mock_resp):
            res = extrair_dados_os_por_foto(b"fake_image_bytes", api_key="valid_test_key")
            self.assertTrue(res["sucesso"])
            self.assertEqual(res["dados"]["numero_os"], "10216")
            self.assertEqual(res["dados"]["motivo"], "Vazamento de vapor")
            self.assertEqual(res["dados"]["tipo_manutencao"], "CORRETIVA")
            self.assertTrue(res["dados"]["parou_maquina"])
            self.assertEqual(res["maquina_sugerida_id"], self.machine.id)
            self.assertEqual(res["setor_sugerido_id"], self.sector.id)

    def test_os_ocr_network_failure_mock(self):
        """Valida captura de falhas de conexão de rede sem crash."""
        from unittest.mock import patch
        import requests
        from maintenance.services.os_ocr_service import extrair_dados_os_por_foto

        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Erro DNS")):
            res = extrair_dados_os_por_foto(b"fake_image_bytes", api_key="valid_test_key")
            self.assertFalse(res["sucesso"])
            self.assertEqual(res["motivo"], "FALHA_CONEXAO")

    def test_api_extrair_dados_os_foto_endpoint(self):
        """Valida o endpoint HTTP /api/os/extrair-foto/."""
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile

        client = Client()

        # 1. Bloqueio para usuário não logado
        res_anon = client.post(reverse('api_extrair_dados_os_foto'))
        self.assertEqual(res_anon.status_code, 302)

        # 2. Usuário autenticado enviando GET
        client.force_login(self.user)
        res_get = client.get(reverse('api_extrair_dados_os_foto'))
        self.assertEqual(res_get.status_code, 405)

        # 3. Usuário autenticado sem arquivo
        res_nofile = client.post(reverse('api_extrair_dados_os_foto'))
        self.assertEqual(res_nofile.status_code, 400)
        data_nofile = json.loads(res_nofile.content)
        self.assertFalse(data_nofile["sucesso"])

        # 4. Usuário autenticado enviando imagem com sucesso
        fake_file = SimpleUploadedFile("os_scan.jpg", b"\xff\xd8\xff\xe0fake_jpeg", content_type="image/jpeg")
        
        mock_ret = {
            "sucesso": True,
            "dados": {"numero_os": "10216", "motivo": "Pressão baixa"},
            "maquina_sugerida_id": self.machine.id,
            "setor_sugerido_id": self.sector.id
        }
        with patch("maintenance.services.os_ocr_service.extrair_dados_os_por_foto", return_value=mock_ret):
            res_post = client.post(reverse('api_extrair_dados_os_foto'), {"foto_os": fake_file})
            self.assertEqual(res_post.status_code, 200)
            data_post = json.loads(res_post.content)
            self.assertTrue(data_post["sucesso"])
            self.assertEqual(data_post["dados"]["numero_os"], "10216")


class OrdemServicoCreationTestCase(TestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.operator_group, _ = Group.objects.get_or_create(name='Operadores')
        self.lider_prod_group, _ = Group.objects.get_or_create(name='Liderança de Produção')
        self.viewer_group, _ = Group.objects.get_or_create(name='Visualizador')

        self.user_op = User.objects.create_user('op_os', 'op@test.com', 'pwd123')
        self.user_op.groups.add(self.operator_group)

        self.user_lider = User.objects.create_user('lider_os', 'lider@test.com', 'pwd123')
        self.user_lider.groups.add(self.lider_prod_group)

        self.user_viewer = User.objects.create_user('view_os', 'view@test.com', 'pwd123')
        self.user_viewer.groups.add(self.viewer_group)

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa 01", setor=self.sector, criticidade="ALTA")
        self.technician = Technician.objects.create(nome="João Mecânico", is_active=True)

        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (10, 10), color='white').save(buf, format='JPEG')
        self.valid_photo_bytes = buf.getvalue()

    def test_form_validation_and_duplicity(self):
        """Valida obrigatoriedade da foto e rejeição estrita de duplicidade no Form."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        # 1. Cria uma OS existente no banco
        OrdemServico.objects.create(
            numero_os="10216",
            maquina=self.machine,
            setor=self.sector,
            solicitante="Carlos",
            descricao_falha="Vazamento"
        )

        photo = SimpleUploadedFile("abertura_1.jpg", self.valid_photo_bytes, content_type="image/jpeg")
        data = {
            'numero_os': '10216', # Duplicada
            'solicitante': 'Carlos',
            'descricao_falha': 'Outro vazamento',
            'tipo_manutencao': 'CORRETIVA',
            'parou_maquina': 'True',
            'criticidade': 'ALTA',
            'data_hora_inicio_ocorrencia': timezone.now().strftime('%Y-%m-%dT%H:%M')
        }
        form = OrdemServicoCreateForm(data=data, files={'foto_abertura': photo})
        self.assertFalse(form.is_valid())
        self.assertIn("já está cadastrada", form.errors['numero_os'][0])

        # 2. Form sem foto de abertura deve ser inválido
        data_nova = data.copy()
        data_nova['numero_os'] = '10217'
        form_nofoto = OrdemServicoCreateForm(data=data_nova)
        self.assertFalse(form_nofoto.is_valid())
        self.assertIn("foto da folha física de abertura da OS é obrigatória", form_nofoto.errors['foto_abertura'][0])

    def test_api_verificar_numero_os(self):
        """Valida endpoint de verificação instantânea anti-duplicidade."""
        client = Client()
        # 1. Acesso anônimo
        res_anon = client.get(reverse('api_verificar_numero_os') + '?numero=10216')
        self.assertEqual(res_anon.status_code, 302)

        # 2. Acesso autenticado com número inexistente
        client.force_login(self.user_op)
        res_non = client.get(reverse('api_verificar_numero_os') + '?numero=99999')
        self.assertEqual(res_non.status_code, 200)
        self.assertFalse(json.loads(res_non.content)["existe"])

        # 3. Cria OS e checa se endpoint acusa existência
        OrdemServico.objects.create(
            numero_os="88888",
            maquina=self.machine,
            descricao_equipamento="Prensa 01",
            solicitante="Marcos Líder",
            descricao_falha="Falha sensor"
        )
        res_exist = client.get(reverse('api_verificar_numero_os') + '?numero=88888')
        self.assertEqual(res_exist.status_code, 200)
        data = json.loads(res_exist.content)
        self.assertTrue(data["existe"])
        self.assertEqual(data["os"]["numero"], "88888")

    def test_os_create_view_permissions_and_flow(self):
        """Valida permissões da view os_create e fluxo de criação com upload."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        client = Client()

        # 1. Usuário sem permissão (Viewer)
        client.force_login(self.user_viewer)
        res_view = client.get(reverse('os_create'))
        self.assertEqual(res_view.status_code, 302) # Redireciona com alerta

        # 2. Usuário de Liderança de Produção (Acesso Autorizado)
        client.force_login(self.user_lider)
        res_get = client.get(reverse('os_create'))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "Abertura de Ordem de Serviço")

        # 3. POST criando OS com foto
        photo = SimpleUploadedFile("folha_10216.jpg", self.valid_photo_bytes, content_type="image/jpeg")
        post_data = {
            'numero_os': '55443',
            'tag': 'PREN-01',
            'descricao_equipamento': 'Prensa 01',
            'maquina': self.machine.id,
            'setor': self.sector.id,
            'solicitante': 'Líder Roberto',
            'motivo': 'Barulho anormal',
            'tipo_manutencao': 'CORRETIVA',
            'parou_maquina': 'True',
            'criticidade': 'ALTA',
            'descricao_falha': 'Verificar rolamento do motor principal',
            'data_hora_inicio_ocorrencia': timezone.now().strftime('%Y-%m-%dT%H:%M'),
            'tecnico_designado': self.technician.id,
            'foto_abertura': photo,
        }
        res_post = client.post(reverse('os_create'), data=post_data)
        self.assertEqual(res_post.status_code, 302)



        # 4. Verifica se OS foi criada no banco com status PENDENTE e foto gravada
        os_criada = OrdemServico.objects.get(numero_os='55443')
        self.assertEqual(os_criada.criado_por, self.user_lider)
        self.assertEqual(os_criada.status, 'PENDENTE')
        self.assertEqual(os_criada.tecnico_designado, self.technician)
        self.assertTrue(bool(os_criada.foto_abertura))
        self.assertTrue(os_criada.parou_maquina)


class OrdemServicoBoardAndMultiTechTestCase(TestCase):
    """
    Testes unitários e de integração para a Fase 5:
    - Quadro de OSs (/ordens-servico/)
    - Atribuição de técnico por operadores/líderes
    - Início de atendimento com criação de alocação vinculada
    - Concorrência estrita (1 atendimento ativo por técnico)
    - Bloqueio de técnicos ausentes
    - Suporte a múltiplos técnicos na mesma OS (trabalho em equipe)
    - Cancelamento de OS
    """
    def setUp(self):
        self.op_group, _ = Group.objects.get_or_create(name='Operadores')
        self.lider_group, _ = Group.objects.get_or_create(name='Liderança de Produção')
        self.viewer_group, _ = Group.objects.get_or_create(name='Visualizador')

        self.user_op = User.objects.create_user('operador_os', 'op@test.com', 'pwd123')
        self.user_op.groups.add(self.op_group)

        self.user_lider = User.objects.create_user('lider_os_5', 'lider5@test.com', 'pwd123')
        self.user_lider.groups.add(self.lider_group)

        self.user_viewer = User.objects.create_user('viewer_os_5', 'view5@test.com', 'pwd123')
        self.user_viewer.groups.add(self.viewer_group)

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.sector_outro = Sector.objects.create(nome="PCP")
        self.machine = Machine.objects.create(nome="Prensa 05", setor=self.sector, criticidade="ALTA")
        self.machine_2 = Machine.objects.create(nome="Extrusora 02", setor=self.sector, criticidade="MEDIA")

        self.tech_1 = Technician.objects.create(nome="Marcos Mecânico", matricula="M001", is_active=True, status="OCIOSO")
        self.tech_2 = Technician.objects.create(nome="Lucas Eletricista", matricula="E002", is_active=True, status="OCIOSO")
        self.tech_ausente = Technician.objects.create(nome="Roberto Ausente", matricula="A003", is_active=True, status="AUSENTE_FERIAS")

        self.os_pendente = OrdemServico.objects.create(
            numero_os="7001",
            maquina=self.machine,
            setor=self.sector,
            solicitante="Líder João",
            motivo="Vazamento de óleo",
            descricao_falha="Trocar retentor",
            status="PENDENTE",
            criticidade="ALTA"
        )

    def test_os_board_view_and_filtering(self):
        """Valida renderização do quadro de OSs e filtros de status/setor."""
        client = Client()
        client.force_login(self.user_op)

        # 1. Acesso à aba pendentes
        res = client.get(reverse('os_board') + '?tab=pendentes')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "7001")
        self.assertContains(res, "Prensa 05")

        # 2. Busca por número de OS
        res_search = client.get(reverse('os_board') + '?busca=7001')
        self.assertEqual(res_search.status_code, 200)
        self.assertContains(res_search, "7001")

        # 3. Busca que não retorna nada
        res_none = client.get(reverse('os_board') + '?busca=999999')
        self.assertEqual(res_none.status_code, 200)
        self.assertNotContains(res_none, "7001")

    def test_os_assign_technician_flow(self):
        """Valida atribuição de técnico por operador e bloqueio de ausentes."""
        client = Client()

        # 1. Bloqueia usuário sem permissão (Viewer)
        client.force_login(self.user_viewer)
        res_view = client.post(reverse('os_assign_technician', args=[self.os_pendente.id]), data={'technician_id': self.tech_1.id})
        self.assertEqual(res_view.status_code, 302)
        self.os_pendente.refresh_from_db()
        self.assertIsNone(self.os_pendente.tecnico_designado)

        # 2. Operador atribui técnico disponível
        client.force_login(self.user_op)
        res_op = client.post(reverse('os_assign_technician', args=[self.os_pendente.id]), data={'technician_id': self.tech_1.id})
        self.assertEqual(res_op.status_code, 302)
        self.os_pendente.refresh_from_db()
        self.assertEqual(self.os_pendente.tecnico_designado, self.tech_1)

        # 3. Tenta atribuir técnico ausente -> Bloqueia
        res_ausente = client.post(reverse('os_assign_technician', args=[self.os_pendente.id]), data={'technician_id': self.tech_ausente.id})
        self.assertEqual(res_ausente.status_code, 302)
        self.os_pendente.refresh_from_db()
        self.assertEqual(self.os_pendente.tecnico_designado, self.tech_1) # Não alterou

        # 4. Remove atribuição
        res_clear = client.post(reverse('os_assign_technician', args=[self.os_pendente.id]), data={'technician_id': ''})
        self.assertEqual(res_clear.status_code, 302)
        self.os_pendente.refresh_from_db()
        self.assertIsNone(self.os_pendente.tecnico_designado)

    def test_os_start_service_flow_and_concurrency(self):
        """Valida início de atendimento, criação de alocação e bloqueio de concorrência."""
        client = Client()
        client.force_login(self.user_op)

        # 1. Inicia atendimento da OS com tech_1
        res_start = client.post(reverse('os_start_service', args=[self.os_pendente.id]), data={'technician_id': self.tech_1.id})
        self.assertEqual(res_start.status_code, 302)

        self.os_pendente.refresh_from_db()
        self.tech_1.refresh_from_db()

        self.assertEqual(self.os_pendente.status, 'EM_ANDAMENTO')
        self.assertEqual(self.tech_1.status, 'EM_ATENDIMENTO')
        self.assertEqual(self.os_pendente.allocations.count(), 1)

        alloc = self.os_pendente.allocations.first()
        self.assertEqual(alloc.tecnico, self.tech_1)
        self.assertEqual(alloc.maquina, self.machine)
        self.assertEqual(alloc.status, 'EM_ATENDIMENTO')
        self.assertIsNotNone(alloc.data_inicio)

        # 2. Tenta iniciar uma SEGUNDA OS com o mesmo técnico que já está EM_ATENDIMENTO -> Bloqueia por concorrência
        os_2 = OrdemServico.objects.create(
            numero_os="7002",
            maquina=self.machine_2,
            solicitante="Líder Pedro",
            descricao_falha="Falha motor",
            status="PENDENTE"
        )
        res_concurr = client.post(reverse('os_start_service', args=[os_2.id]), data={'technician_id': self.tech_1.id})
        self.assertEqual(res_concurr.status_code, 302)

        os_2.refresh_from_db()
        self.assertEqual(os_2.status, 'PENDENTE') # Continua pendente
        self.assertEqual(os_2.allocations.count(), 0)

        # 3. Tenta iniciar com técnico ausente -> Bloqueia
        res_ausente = client.post(reverse('os_start_service', args=[os_2.id]), data={'technician_id': self.tech_ausente.id})
        self.assertEqual(res_ausente.status_code, 302)
        os_2.refresh_from_db()
        self.assertEqual(os_2.status, 'PENDENTE')

    def test_os_join_team_multi_technician_flow(self):
        """Valida suporte a múltiplos técnicos na mesma OS e controle individual de alocações."""
        client = Client()
        client.force_login(self.user_op)

        # 1. Tech 1 inicia a OS
        client.post(reverse('os_start_service', args=[self.os_pendente.id]), data={'technician_id': self.tech_1.id})
        self.os_pendente.refresh_from_db()
        self.assertEqual(self.os_pendente.allocations.count(), 1)

        # 2. Tech 2 junta-se à equipe da mesma OS
        res_join = client.post(reverse('os_join_team', args=[self.os_pendente.id]), data={'technician_id': self.tech_2.id})
        self.assertEqual(res_join.status_code, 302)

        self.os_pendente.refresh_from_db()
        self.tech_2.refresh_from_db()

        self.assertEqual(self.tech_2.status, 'EM_ATENDIMENTO')
        self.assertEqual(self.os_pendente.allocations.count(), 2)

        techs_na_os = [a.tecnico for a in self.os_pendente.allocations.all()]
        self.assertIn(self.tech_1, techs_na_os)
        self.assertIn(self.tech_2, techs_na_os)

        # 3. Tentar adicionar o Tech 2 novamente na mesma OS -> Bloqueia duplicata
        res_dup = client.post(reverse('os_join_team', args=[self.os_pendente.id]), data={'technician_id': self.tech_2.id})
        self.assertEqual(res_dup.status_code, 302)
        self.assertEqual(self.os_pendente.allocations.count(), 2)

    def test_os_cancel_flow(self):
        """Valida cancelamento de OS pendente e bloqueio de cancelamento com atendimentos ativos."""
        client = Client()
        client.force_login(self.user_op)

        # 1. Cancela OS pendente com sucesso
        res_cancel = client.post(reverse('os_cancel', args=[self.os_pendente.id]))
        self.assertEqual(res_cancel.status_code, 302)
        self.os_pendente.refresh_from_db()
        self.assertEqual(self.os_pendente.status, 'CANCELADA')

        # 2. OS em andamento com alocação ativa não pode ser cancelada
        os_andamento = OrdemServico.objects.create(
            numero_os="7003",
            maquina=self.machine,
            status="EM_ANDAMENTO"
        )
        Allocation.objects.create(
            tecnico=self.tech_1,
            maquina=self.machine,
            ordem_servico=os_andamento,
            status='EM_ATENDIMENTO',
            data_inicio=timezone.now(),
            usuario_operador=self.user_op
        )
        res_block_cancel = client.post(reverse('os_cancel', args=[os_andamento.id]))
        self.assertEqual(res_block_cancel.status_code, 302)
        os_andamento.refresh_from_db()
        self.assertEqual(os_andamento.status, 'EM_ANDAMENTO')


class OrdemServicoEndToEndQATestCase(TestCase):
    """
    Testes integrados de ponta a ponta (QA Fase 7):
    - Roteamento e Portal (/portal/, /management/, /producao/)
    - Vínculo emergencial de atendimento avulso a uma folha de OS física
    - Conclusão completa de OS com anexo de foto assinada, líder e peças
    - Tela de Detalhes e Auditoria (/ordens-servico/<pk>/)
    - Fallbacks seguros
    """
    def setUp(self):
        import io
        from PIL import Image
        self.op_group, _ = Group.objects.get_or_create(name='Operadores')
        self.lider_prod_group, _ = Group.objects.get_or_create(name='Liderança de Produção')
        self.tecnico_group, _ = Group.objects.get_or_create(name='Técnico')

        # Usuários com diferentes perfis de acesso
        self.user_tech = User.objects.create_user('tech_qa', 'tech@qa.com', 'pwd123')
        self.user_tech.groups.add(self.tecnico_group)

        self.user_prod = User.objects.create_user('prod_qa', 'prod@qa.com', 'pwd123')
        self.user_prod.groups.add(self.lider_prod_group)

        self.user_dual = User.objects.create_user('dual_qa', 'dual@qa.com', 'pwd123')
        self.user_dual.groups.add(self.op_group)
        self.user_dual.groups.add(self.lider_prod_group)

        self.sector = Sector.objects.create(nome="Vulcanização")
        self.machine = Machine.objects.create(nome="Prensa QA 01", setor=self.sector, criticidade="ALTA")
        self.technician = Technician.objects.create(nome="Carlos QA", matricula="QA99", is_active=True, status="OCIOSO", user=self.user_tech)


        buf = io.BytesIO()
        Image.new('RGB', (20, 20), color='blue').save(buf, format='JPEG')
        self.valid_jpeg = buf.getvalue()

    def test_qa_routing_and_portal_access(self):
        """Valida roteamento correto pós-login e acesso aos módulos."""
        client = Client()

        # 1. Técnico comum acessa portal_select -> redireciona direto para management
        client.force_login(self.user_tech)
        res_tech = client.get(reverse('portal_select'))
        self.assertEqual(res_tech.status_code, 302)
        self.assertIn('/management/', res_tech.url)

        # 2. Usuário de produção acessa portal_select -> redireciona direto para produção
        client.force_login(self.user_prod)
        res_prod = client.get(reverse('portal_select'))
        self.assertEqual(res_prod.status_code, 302)
        self.assertIn('/producao/', res_prod.url)

        # 3. Usuário com duplo acesso -> exibe a tela de portal para escolher
        client.force_login(self.user_dual)
        res_dual = client.get(reverse('portal_select'))
        self.assertEqual(res_dual.status_code, 200)
        self.assertContains(res_dual, "card-manutencao")
        self.assertContains(res_dual, "card-producao")



    def test_qa_emergency_link_and_finalization_flow(self):
        """Valida fluxo de atendimento emergencial, vínculo à OS física e fechamento com foto assinada."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        client = Client()
        client.force_login(self.user_dual)

        # 1. Inicia atendimento avulso sem OS prévia
        alloc = Allocation.objects.create(
            tecnico=self.technician,
            maquina=self.machine,
            atividade_observacao="Manutenção de emergência - vazamento de óleo",
            data_inicio=timezone.now(),
            status='EM_ATENDIMENTO',
            usuario_operador=self.user_dual
        )
        self.technician.status = 'EM_ATENDIMENTO'
        self.technician.save()

        # 2. Folha física chega: cria OS pendente
        os_obj = OrdemServico.objects.create(
            numero_os="99101",
            maquina=self.machine,
            setor=self.sector,
            solicitante="Líder Fernando",
            descricao_falha="Vazamento grave de óleo hidráulico",
            status="PENDENTE"
        )

        # 3. Vincula atendimento à OS física via link_allocation_os
        res_link = client.post(reverse('link_allocation_os', args=[alloc.id]), data={'os_id': os_obj.id})
        self.assertEqual(res_link.status_code, 302)

        alloc.refresh_from_db()
        os_obj.refresh_from_db()
        self.assertEqual(alloc.ordem_servico, os_obj)
        self.assertEqual(os_obj.status, 'EM_ANDAMENTO')

        # 4. Finaliza a alocação enviando foto da OS concluída, visto do líder e peças
        photo_conc = SimpleUploadedFile("os_concluida_assinada.jpg", self.valid_jpeg, content_type="image/jpeg")
        post_data = {
            'observacao_conclusao': 'Troca do retentor principal e teste de vedação OK.',
            'lider_assinatura_nome': 'Líder Fernando Ramos',
            'causa': 'Desgaste natural do anel o-ring',
            'descricao_servico_realizado': 'Substituição de anel de vedação e reaperto dos flanges',
            'pecas_utilizadas_texto': '1x Anel O-ring Viton 50mm\n2L Óleo ISO 68',
            'foto_conclusao': photo_conc,
        }
        res_finish = client.post(reverse('finish_allocation', args=[alloc.id]), data=post_data)
        self.assertEqual(res_finish.status_code, 302)

        alloc.refresh_from_db()
        os_obj.refresh_from_db()
        self.technician.refresh_from_db()

        # Verificações de conclusão
        self.assertEqual(alloc.status, 'CONCLUIDO')
        self.assertEqual(self.technician.status, 'OCIOSO')
        self.assertEqual(os_obj.status, 'CONCLUIDA')
        self.assertEqual(os_obj.lider_assinatura_nome, 'Líder Fernando Ramos')
        self.assertEqual(os_obj.causa, 'Desgaste natural do anel o-ring')
        self.assertTrue(bool(os_obj.foto_conclusao))
        self.assertEqual(os_obj.pecas_utilizadas.count(), 2)

        # 5. Valida tela de auditoria / detalhes da OS (/ordens-servico/<pk>/)
        res_detail = client.get(reverse('os_detail', args=[os_obj.id]))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "99101")
        self.assertContains(res_detail, "Líder Fernando Ramos")
        self.assertContains(res_detail, "Carlos QA")
        self.assertContains(res_detail, "Anel O-ring Viton 50mm")










