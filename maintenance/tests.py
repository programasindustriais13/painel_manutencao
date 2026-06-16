from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import Sector, Machine, Technician, Allocation, HistoricoPausa

class MaintenanceSystemTestCase(TestCase):
    def setUp(self):
        # Create groups
        self.operator_group = Group.objects.create(name='Operador')
        self.viewer_group = Group.objects.create(name='Visualizador')
        
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
        # Custom decorator redirects to tv_dashboard on access violations
        self.assertRedirects(response, reverse('tv_dashboard'))
        
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



