from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import Sector, Machine, Technician, Allocation, HistoricoPausa, WhatsAppGroup

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
        
        # 4. Other users (like operador_user or admin) -> dashboard
        client.force_login(self.operador_user)
        response = client.get(reverse('home_redirect'))
        self.assertRedirects(response, reverse('dashboard'))
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
        response = client.get(reverse('relatorio_turno'))
        self.assertEqual(response.status_code, 200)
        report_text = response.context['texto_precompilado']
        self.assertIn("* Torno CNC - Troca de correia efetuada", report_text)
        self.assertIn("* Prensa Hidráulica - Em Pausa - Aguardando peça", report_text)
        
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





