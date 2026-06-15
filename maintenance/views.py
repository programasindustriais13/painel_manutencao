from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from functools import wraps
import json

from .models import Sector, Machine, Technician, Allocation
from .forms import (
    SectorForm, MachineForm, TechnicianForm, 
    StartServiceForm, PauseServiceForm, FinishServiceForm
)

# Custom decorator to check if user is Operador/Gestor or superuser
def operador_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser or request.user.is_staff or request.user.groups.filter(name='Operador').exists():
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso restrito. Apenas operadores e gestores podem acessar esta página.")
        return redirect('tv_dashboard')
    return wrapper


@login_required
def home_redirect(request):
    if request.user.is_superuser or request.user.is_staff or request.user.groups.filter(name='Operador').exists():
        return redirect('technician_management')
    return redirect('tv_dashboard')


# ----------------------------------------------------
# 1. TELA A: PAINEL INFORMATIVO DE FÁBRICA (MODO TV)
# ----------------------------------------------------
@login_required
def tv_dashboard(request):
    technicians = Technician.objects.all().order_by('nome')
    context = {
        'technicians': technicians,
        'now': timezone.now(),
    }
    return render(request, 'maintenance/tv_dashboard.html', context)


# ----------------------------------------------------
# 2. TELA C: GERENCIAMENTO DE TÉCNICOS EM TEMPO REAL (OPERADOR)
# ----------------------------------------------------
@operador_required
def technician_management(request):
    technicians = Technician.objects.all().order_by('nome')
    
    # Instantiate blank forms to render in the modals
    start_form = StartServiceForm()
    pause_form = PauseServiceForm()
    finish_form = FinishServiceForm()
    
    context = {
        'technicians': technicians,
        'start_form': start_form,
        'pause_form': pause_form,
        'finish_form': finish_form,
    }
    return render(request, 'maintenance/technician_management.html', context)


# Action: Start Service
@operador_required
def start_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)
        
        # Check if technician is already busy
        if technician.status != 'OCIOSO':
            messages.error(request, f"Técnico {technician.nome} não está ocioso.")
            return redirect('technician_management')
            
        form = StartServiceForm(request.POST)
        if form.is_valid():
            # Update technician state
            technician.status = 'EM_ATENDIMENTO'
            technician.save()
            
            # Create Allocation record
            allocation = form.save(commit=False)
            allocation.tecnico = technician
            allocation.data_inicio = timezone.now()
            allocation.save()
            
            messages.success(request, f"Serviço iniciado com sucesso para {technician.nome}.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro: {error}")
                    
    return redirect('technician_management')


# Action: Pause Service
@operador_required
def pause_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)
        
        if technician.status != 'EM_ATENDIMENTO':
            messages.error(request, f"Técnico {technician.nome} não está em atendimento ativo.")
            return redirect('technician_management')
            
        active_alloc = technician.active_allocation
        if not active_alloc:
            messages.error(request, f"Nenhuma alocação ativa encontrada para {technician.nome}.")
            return redirect('technician_management')
            
        form = PauseServiceForm(request.POST)
        if form.is_valid():
            # Save pause details in active allocation
            active_alloc.data_pausa = timezone.now()
            active_alloc.motivo_pausa = form.cleaned_data['motivo_pausa']
            active_alloc.save()
            
            # Update technician state
            technician.status = 'EM_PAUSA'
            technician.save()
            
            messages.warning(request, f"Serviço pausado para {technician.nome}.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro: {error}")
                    
    return redirect('technician_management')


# Action: Resume Service
@operador_required
def resume_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)
        
        if technician.status != 'EM_PAUSA':
            messages.error(request, f"Técnico {technician.nome} não está em pausa.")
            return redirect('technician_management')
            
        active_alloc = technician.active_allocation
        if not active_alloc:
            messages.error(request, f"Nenhuma alocação ativa encontrada para {technician.nome}.")
            return redirect('technician_management')
            
        # Resume active service: reset pause columns and toggle state
        active_alloc.data_pausa = None
        active_alloc.motivo_pausa = None
        active_alloc.save()
        
        technician.status = 'EM_ATENDIMENTO'
        technician.save()
        
        messages.success(request, f"Serviço retomado por {technician.nome}.")
        
    return redirect('technician_management')


# Action: Finish Service
@operador_required
def finish_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)
        
        if technician.status not in ['EM_ATENDIMENTO', 'EM_PAUSA']:
            messages.error(request, f"Técnico {technician.nome} não possui atendimento ativo.")
            return redirect('technician_management')
            
        active_alloc = technician.active_allocation
        if not active_alloc:
            messages.error(request, f"Nenhuma alocação ativa encontrada para {technician.nome}.")
            return redirect('technician_management')
            
        form = FinishServiceForm(request.POST, request.FILES)
        if form.is_valid():
            # Update allocation end state
            active_alloc.data_fim = timezone.now()
            active_alloc.observacao_conclusao = form.cleaned_data['observacao_conclusao']
            if 'foto_anexo' in request.FILES:
                active_alloc.foto_anexo = request.FILES['foto_anexo']
            active_alloc.save()
            
            # Update technician to idle
            technician.status = 'OCIOSO'
            technician.save()
            
            messages.success(request, f"Serviço finalizado com sucesso por {technician.nome}.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro: {error}")
                    
    return redirect('technician_management')


# ----------------------------------------------------
# 3. TELA D: DASHBOARD DE ANÁLISE (GESTÃO)
# ----------------------------------------------------
@operador_required
def dashboard(request):
    # Top KPI cards
    total_techs = Technician.objects.count()
    active_techs = Technician.objects.filter(status='EM_ATENDIMENTO').count()
    paused_techs = Technician.objects.filter(status='EM_PAUSA').count()
    idle_techs = Technician.objects.filter(status='OCIOSO').count()
    
    # Distinct machines currently undergoing maintenance (data_fim is null)
    machines_in_maintenance = Machine.objects.filter(
        allocations__data_fim__isnull=True
    ).distinct().count()
    
    # 1. Pie/Doughnut Chart Data: Distribution of tech status
    status_distribution = {
        'OCIOSO': idle_techs,
        'EM_ATENDIMENTO': active_techs,
        'EM_PAUSA': paused_techs,
    }
    
    # 2. Bar Chart Data: Allocations by Criticidade
    criticidades = ['BAIXA', 'MEDIA', 'ALTA']
    alloc_by_criticidade = {
        'Baixa': Allocation.objects.filter(maquina__criticidade='BAIXA').count(),
        'Média': Allocation.objects.filter(maquina__criticidade='MEDIA').count(),
        'Alta': Allocation.objects.filter(maquina__criticidade='ALTA').count(),
    }
    
    # 3. Bar Chart Data: Allocations by Sector
    sectors = Sector.objects.all()
    alloc_by_sector = {s.nome: Allocation.objects.filter(maquina__setor=s).count() for s in sectors}

    context = {
        'total_techs': total_techs,
        'active_techs': active_techs,
        'paused_techs': paused_techs,
        'idle_techs': idle_techs,
        'machines_in_maintenance': machines_in_maintenance,
        
        # Serialize to pass safely to javascript block
        'status_labels': json.dumps(list(status_distribution.keys())),
        'status_values': json.dumps(list(status_distribution.values())),
        
        'crit_labels': json.dumps(list(alloc_by_criticidade.keys())),
        'crit_values': json.dumps(list(alloc_by_criticidade.values())),
        
        'sector_labels': json.dumps(list(alloc_by_sector.keys())),
        'sector_values': json.dumps(list(alloc_by_sector.values())),
    }
    return render(request, 'maintenance/dashboard.html', context)


# ----------------------------------------------------
# 4. TELA B: CADASTRO E CONFIGURAÇÕES (CRUDs)
# ----------------------------------------------------
@operador_required
def crud_list(request):
    sectors = Sector.objects.all().order_by('nome')
    machines = Machine.objects.all().order_by('nome')
    technicians = Technician.objects.all().order_by('nome')
    
    context = {
        'sectors': sectors,
        'machines': machines,
        'technicians': technicians,
    }
    return render(request, 'maintenance/crud_list.html', context)


# Sector CRUD
@operador_required
def sector_create(request):
    if request.method == 'POST':
        form = SectorForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Setor cadastrado com sucesso.")
            return redirect('crud_list')
    else:
        form = SectorForm()
    return render(request, 'maintenance/sector_form.html', {'form': form, 'title': 'Cadastrar Setor'})

@operador_required
def sector_edit(request, pk):
    sector = get_object_or_404(Sector, pk=pk)
    if request.method == 'POST':
        form = SectorForm(request.POST, instance=sector)
        if form.is_valid():
            form.save()
            messages.success(request, "Setor atualizado com sucesso.")
            return redirect('crud_list')
    else:
        form = SectorForm(instance=sector)
    return render(request, 'maintenance/sector_form.html', {'form': form, 'title': 'Editar Setor'})

@operador_required
def sector_delete(request, pk):
    sector = get_object_or_404(Sector, pk=pk)
    if request.method == 'POST':
        sector.delete()
        messages.success(request, "Setor excluído com sucesso.")
        return redirect('crud_list')
    return render(request, 'maintenance/crud_confirm_delete.html', {'object': sector, 'type': 'Setor'})


# Machine CRUD
@operador_required
def machine_create(request):
    if request.method == 'POST':
        form = MachineForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Máquina cadastrada com sucesso.")
            return redirect('crud_list')
    else:
        form = MachineForm()
    return render(request, 'maintenance/machine_form.html', {'form': form, 'title': 'Cadastrar Máquina'})

@operador_required
def machine_edit(request, pk):
    machine = get_object_or_404(Machine, pk=pk)
    if request.method == 'POST':
        form = MachineForm(request.POST, instance=machine)
        if form.is_valid():
            form.save()
            messages.success(request, "Máquina atualizada com sucesso.")
            return redirect('crud_list')
    else:
        form = MachineForm(instance=machine)
    return render(request, 'maintenance/machine_form.html', {'form': form, 'title': 'Editar Máquina'})

@operador_required
def machine_delete(request, pk):
    machine = get_object_or_404(Machine, pk=pk)
    if request.method == 'POST':
        machine.delete()
        messages.success(request, "Máquina excluída com sucesso.")
        return redirect('crud_list')
    return render(request, 'maintenance/crud_confirm_delete.html', {'object': machine, 'type': 'Máquina'})


# Technician CRUD
@operador_required
def technician_create(request):
    if request.method == 'POST':
        form = TechnicianForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Técnico cadastrado com sucesso.")
            return redirect('crud_list')
    else:
        form = TechnicianForm()
    return render(request, 'maintenance/technician_form.html', {'form': form, 'title': 'Cadastrar Técnico'})

@operador_required
def technician_edit(request, pk):
    technician = get_object_or_404(Technician, pk=pk)
    if request.method == 'POST':
        form = TechnicianForm(request.POST, instance=technician)
        if form.is_valid():
            form.save()
            messages.success(request, "Técnico atualizado com sucesso.")
            return redirect('crud_list')
    else:
        form = TechnicianForm(instance=technician)
    return render(request, 'maintenance/technician_form.html', {'form': form, 'title': 'Editar Técnico'})

@operador_required
def technician_delete(request, pk):
    technician = get_object_or_404(Technician, pk=pk)
    if request.method == 'POST':
        technician.delete()
        messages.success(request, "Técnico excluído com sucesso.")
        return redirect('crud_list')
    return render(request, 'maintenance/crud_confirm_delete.html', {'object': technician, 'type': 'Técnico'})




