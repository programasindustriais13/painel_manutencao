from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse
from functools import wraps
import json
import io
from django.db.models import Prefetch
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import Sector, Machine, Technician, Allocation, HistoricoPausa, HistoricoEscala
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
    user = request.user
    if user.groups.filter(name='Visualizador').exists() or user.username == 'tv':
        return redirect('tv_dashboard')
    else:
        return redirect('dashboard')


# ----------------------------------------------------
# 1. TELA A: PAINEL INFORMATIVO DE FÁBRICA (MODO TV)
# ----------------------------------------------------
@login_required
def tv_dashboard(request):
    active_allocations = Allocation.objects.filter(
        data_fim__isnull=True,
        status='EM_ATENDIMENTO'
    ).select_related('maquina', 'maquina__setor').prefetch_related('pausas')
    
    technicians = Technician.objects.all().prefetch_related(
        Prefetch('allocations', queryset=active_allocations)
    ).order_by('nome')
    
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
        
        # Bloquear se o técnico estiver ausente/fora da fábrica.
        if technician.is_ausente:
            messages.error(request, f"Técnico {technician.nome} está marcado como '{technician.get_status_display()}' e não pode receber novas ordens. Altere a disponibilidade antes de alocar.")
            return redirect('technician_management')

        # Bloquear APENAS se o técnico já tiver uma alocação EM_ATENDIMENTO ativa.
        # Ter apenas serviços pausados é permitido — o técnico pode receber nova ordem.
        if technician.active_allocation is not None:
            messages.error(request, f"Técnico {technician.nome} já possui um atendimento ativo. Pause-o antes de iniciar outro.")
            return redirect('technician_management')
            
        form = StartServiceForm(request.POST)
        if form.is_valid():
            allocation = form.save(commit=False)
            allocation.tecnico = technician
            allocation.data_inicio = timezone.now()
            allocation.status = 'EM_ATENDIMENTO'
            allocation.save()
            
            # Status do técnico sempre reflete a alocação ativa
            technician.status = 'EM_ATENDIMENTO'
            technician.save()
            
            messages.success(request, f"Serviço iniciado com sucesso para {technician.nome}.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro: {error}")
                    
    return redirect('technician_management')


# Action: Pause Service (pausa a alocação ativa do técnico)
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
            now_time = timezone.now()
            motivo = form.cleaned_data['motivo_pausa']
            
            # Cria registro de histórico de pausa
            HistoricoPausa.objects.create(
                alocacao=active_alloc,
                data_pausa=now_time,
                motivo_pausa=motivo
            )
            
            # Marca a alocação como EM_PAUSA (mantendo campos legados)
            active_alloc.data_pausa = now_time
            active_alloc.motivo_pausa = motivo
            active_alloc.status = 'EM_PAUSA'
            active_alloc.save()
            
            # Atualiza status do técnico: EM_PAUSA se não houver outra ativa
            if technician.active_allocation is None:
                technician.status = 'EM_PAUSA'
                technician.save()
            
            messages.warning(request, f"Serviço pausado para {technician.nome}.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro: {error}")
                    
    return redirect('technician_management')


# Action: Resume Service (retoma o ÚNICO serviço pausado — caso simples)
@operador_required
def resume_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)
        
        if technician.status != 'EM_PAUSA':
            messages.error(request, f"Técnico {technician.nome} não está em pausa.")
            return redirect('technician_management')
        
        # Pega a única pausada (caso simples sem alocação ativa)
        paused_allocs = technician.paused_allocations
        if not paused_allocs.exists():
            messages.error(request, f"Nenhuma alocação pausada encontrada para {technician.nome}.")
            return redirect('technician_management')
        
        # Retoma a alocação pausada mais antiga
        alloc = paused_allocs.first()
        
        # Localiza o último registro de HistoricoPausa onde data_retorno é nulo e preenche
        pausa_aberta = alloc.pausas.filter(data_retorno__isnull=True).order_by('-data_pausa').first()
        if pausa_aberta:
            pausa_aberta.data_retorno = timezone.now()
            pausa_aberta.save()
            
        alloc.data_pausa = None
        alloc.motivo_pausa = None
        alloc.status = 'EM_ATENDIMENTO'
        alloc.save()
        
        technician.status = 'EM_ATENDIMENTO'
        technician.save()
        
        messages.success(request, f"Serviço retomado por {technician.nome}.")
        
    return redirect('technician_management')


# Action: Resume Paused Allocation (troca de contexto — ativa alocação específica por ID)
@operador_required
def resume_paused_allocation(request, allocation_id):
    if request.method == 'POST':
        alloc_to_resume = get_object_or_404(Allocation, id=allocation_id)
        technician = alloc_to_resume.tecnico
        
        if alloc_to_resume.status != 'EM_PAUSA' or alloc_to_resume.data_fim is not None:
            messages.error(request, "Esta alocação não está em pausa ou já foi encerrada.")
            return redirect('technician_management')
        
        # Se houver uma alocação ativa, ela vai para EM_PAUSA (troca de contexto automática)
        current_active = technician.active_allocation
        if current_active:
            now_time = timezone.now()
            motivo = "Interrompido para retomada de outro serviço."
            HistoricoPausa.objects.create(
                alocacao=current_active,
                data_pausa=now_time,
                motivo_pausa=motivo
            )
            current_active.data_pausa = now_time
            current_active.motivo_pausa = motivo
            current_active.status = 'EM_PAUSA'
            current_active.save()
        
        # Ativa a alocação selecionada
        pausa_aberta = alloc_to_resume.pausas.filter(data_retorno__isnull=True).order_by('-data_pausa').first()
        if pausa_aberta:
            pausa_aberta.data_retorno = timezone.now()
            pausa_aberta.save()
            
        alloc_to_resume.data_pausa = None
        alloc_to_resume.motivo_pausa = None
        alloc_to_resume.status = 'EM_ATENDIMENTO'
        alloc_to_resume.save()
        
        technician.status = 'EM_ATENDIMENTO'
        technician.save()
        
        messages.success(request, f"Alocação retomada: {alloc_to_resume.maquina.nome if alloc_to_resume.maquina else 'Sem máquina'} para {technician.nome}.")
        
    return redirect('technician_management')


# Action: Finish Service (finaliza a alocação ATIVA do técnico)
@operador_required
def finish_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)
        
        active_alloc = technician.active_allocation
        if not active_alloc:
            messages.error(request, f"Nenhuma alocação ativa encontrada para {technician.nome}.")
            return redirect('technician_management')
            
        form = FinishServiceForm(request.POST, request.FILES)
        if form.is_valid():
            now_time = timezone.now()
            active_alloc.data_fim = now_time
            active_alloc.observacao_conclusao = form.cleaned_data['observacao_conclusao']
            if 'foto_anexo' in request.FILES:
                active_alloc.foto_anexo = request.FILES['foto_anexo']
            active_alloc.status = 'CONCLUIDO'
            
            # Garante que se houver uma pausa aberta (sem data de retorno), preenche a data_retorno
            pausa_aberta = active_alloc.pausas.filter(data_retorno__isnull=True).order_by('-data_pausa').first()
            if pausa_aberta:
                pausa_aberta.data_retorno = now_time
                pausa_aberta.save()
                
            active_alloc.save()
            
            # Recalcula status do técnico
            if technician.active_allocation is None:
                remaining_paused = technician.paused_allocations.exists()
                technician.status = 'EM_PAUSA' if remaining_paused else 'OCIOSO'
                technician.save()
            
            messages.success(request, f"Serviço finalizado com sucesso por {technician.nome}.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro: {error}")
                    
    return redirect('technician_management')


# Action: Finish Allocation (finaliza uma alocação específica por ID — ativa OU pausada)
@operador_required
def finish_allocation(request, allocation_id):
    if request.method == 'POST':
        alloc = get_object_or_404(Allocation, id=allocation_id)
        technician = alloc.tecnico
        
        if alloc.data_fim is not None:
            messages.error(request, "Esta alocação já foi encerrada.")
            return redirect('technician_management')
        
        form = FinishServiceForm(request.POST, request.FILES)
        if form.is_valid():
            now_time = timezone.now()
            alloc.data_fim = now_time
            alloc.observacao_conclusao = form.cleaned_data['observacao_conclusao']
            if 'foto_anexo' in request.FILES:
                alloc.foto_anexo = request.FILES['foto_anexo']
                
            # Garante que se houver uma pausa aberta (sem data de retorno), preenche a data_retorno
            pausa_aberta = alloc.pausas.filter(data_retorno__isnull=True).order_by('-data_pausa').first()
            if pausa_aberta:
                pausa_aberta.data_retorno = now_time
                pausa_aberta.save()
                
            alloc.status = 'CONCLUIDO'
            alloc.save()
            
            # Recalcula status do técnico com base nas alocações abertas restantes
            if technician.active_allocation is not None:
                technician.status = 'EM_ATENDIMENTO'
            elif technician.paused_allocations.exists():
                technician.status = 'EM_PAUSA'
            else:
                technician.status = 'OCIOSO'
            technician.save()
            
            messages.success(request, f"Alocação de {alloc.maquina.nome if alloc.maquina else 'serviço'} finalizada com sucesso.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro: {error}")
                    
    return redirect('technician_management')


# Action: Set Availability / Absence status
@operador_required
def set_availability(request, technician_id):
    """Permite ao operador definir o status de escala/ausência do técnico.

    Status aceitos:
        OCIOSO          → retorna o técnico ao fluxo normal
        AUSENTE_FOLGA   → Folga/Escala
        AUSENTE_FERIAS  → Férias
        AUSENTE_MEDICO  → Licença Médica/Afastamento
        EXTERNO_PLANTAO → Plantão fora da fábrica

    Regras de negócio:
        - Ao marcar ausência, o técnico NÃO recebe novas ordens.
        - Serviços pausados existentes são MANTIDOS congelados no histórico.
        - O status EM_ATENDIMENTO não pode ser definido manualmente aqui;
          ele é controlado exclusivamente pelas views start/pause/finish.
    """
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)
        novo_status = request.POST.get('novo_status', '').strip()

        STATUS_PERMITIDOS = {'OCIOSO', 'AUSENTE_FOLGA', 'AUSENTE_FERIAS', 'AUSENTE_MEDICO', 'EXTERNO_PLANTAO'}

        if novo_status not in STATUS_PERMITIDOS:
            messages.error(request, "Status de disponibilidade inválido.")
            return redirect('technician_management')

        # Impede alterar técnico que está EM_ATENDIMENTO para ausência diretamente.
        # O operador deve primeiro pausar/encerrar o serviço ativo.
        if technician.status == 'EM_ATENDIMENTO' and novo_status != 'OCIOSO':
            messages.error(
                request,
                f"{technician.nome} está em atendimento ativo. Pause ou finalize o serviço antes de marcar ausência."
            )
            return redirect('technician_management')

        # Se o técnico tem apenas pausados e está voltando para OCIOSO, mantém pausados
        # (não alteramos as alocações — apenas o status do técnico)
        label_novo = dict(Technician.STATUS_CHOICES).get(novo_status, novo_status)
        technician.status = novo_status
        technician.save()

        # Registra a alteração de escala no histórico de auditoria
        HistoricoEscala.objects.create(
            tecnico=technician,
            status_definido=novo_status,
            usuario_responsavel=request.user if request.user.is_authenticated else None,
        )

        if novo_status == 'OCIOSO':
            messages.success(request, f"{technician.nome} retornou como Disponível (Ocioso).")
        else:
            messages.warning(request, f"{technician.nome} marcado como '{label_novo}'. Não receberá novas ordens até retornar como Ocioso.")

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
    absent_techs = Technician.objects.filter(
        status__in=list(Technician.STATUS_AUSENCIA)
    ).count()

    # Distinct machines currently undergoing maintenance (data_fim is null)
    # machines_in_maintenance = Machine.objects.filter(
    #     allocations__data_fim__isnull=True
    # ).distinct().count()

    # 1. Pie/Doughnut Chart Data: Distribution of tech status (inclui ausências)
    status_distribution = {
        'Ocioso': idle_techs,
        'Em Atendimento': active_techs,
        'Em Pausa': paused_techs,
        'Ausente/Externo': absent_techs,
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
        'absent_techs': absent_techs,
        # 'machines_in_maintenance': machines_in_maintenance,  # commented out to optimize performance
        
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


# ----------------------------------------------------
# 5. EXPORTAÇÃO DE RELATÓRIO EXCEL
# ----------------------------------------------------
@operador_required
def exportar_relatorio_excel(request):
    """
    Gera e retorna um arquivo Excel (.xlsx) com o relatório completo de alocações.
    Inclui: Técnico, Matrícula, Setor, Máquina, Criticidade, Status, Data de Início,
    Data de Fim, Quantidade de Pausas e Tempo Total de Atendimento (em minutos).
    Requer: openpyxl >= 3.1.0
    """
    # Busca todas as alocações com dados relacionados
    allocations = Allocation.objects.select_related(
        'tecnico', 'maquina', 'maquina__setor'
    ).prefetch_related('pausas').order_by('-data_inicio')

    # ── Workbook ──────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Relatório de Alocações"

    # ── Estilos ───────────────────────────────────────────
    header_font  = Font(name='Calibri', bold=True, color='FFFFFF', size=11)
    header_fill  = PatternFill(start_color='1E3A5F', end_color='1E3A5F', fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    alt_fill     = PatternFill(start_color='EBF0F8', end_color='EBF0F8', fill_type='solid')
    center_align = Alignment(horizontal='center', vertical='center')
    left_align   = Alignment(horizontal='left',   vertical='center', wrap_text=True)

    thin_border  = Border(
        left=Side(style='thin', color='CCCCCC'),
        right=Side(style='thin', color='CCCCCC'),
        top=Side(style='thin', color='CCCCCC'),
        bottom=Side(style='thin', color='CCCCCC'),
    )

    # Mapa de criticidade → rótulo
    CRIT_LABELS = {'BAIXA': 'Baixa', 'MEDIA': 'Média', 'ALTA': 'Alta'}
    STATUS_LABELS = {
        'EM_ATENDIMENTO': 'Em Atendimento',
        'EM_PAUSA': 'Em Pausa',
        'CONCLUIDO': 'Concluído',
    }

    # ── Título da planilha ────────────────────────────────
    ws.merge_cells('A1:J1')
    title_cell = ws['A1']
    title_cell.value = f"Relatório de Manutenção — Exportado em {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')}"
    title_cell.font  = Font(name='Calibri', bold=True, size=13, color='1E3A5F')
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    # ── Cabeçalhos ────────────────────────────────────────
    HEADERS = [
        'Técnico', 'Matrícula', 'Setor', 'Máquina', 'Criticidade',
        'Status', 'Data de Início', 'Data de Fim',
        'Qtd. Pausas', 'Tempo Total (min)',
    ]
    COL_WIDTHS = [22, 14, 18, 22, 12, 16, 20, 20, 12, 18]

    for col_idx, (header, width) in enumerate(zip(HEADERS, COL_WIDTHS), start=1):
        cell = ws.cell(row=2, column=col_idx, value=header)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = header_align
        cell.border    = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[2].height = 30

    # ── Linhas de dados ───────────────────────────────────
    BR_TZ = timezone.get_current_timezone()

    for row_idx, alloc in enumerate(allocations, start=3):
        is_alt = (row_idx % 2 == 0)
        row_fill = alt_fill if is_alt else None

        # Dados derivados
        setor_nome = alloc.maquina.setor.nome if alloc.maquina and alloc.maquina.setor else '—'
        maquina_nome = alloc.maquina.nome if alloc.maquina else '—'
        crit_label = CRIT_LABELS.get(alloc.maquina.criticidade, '—') if alloc.maquina else '—'
        status_label = STATUS_LABELS.get(alloc.status, alloc.status)

        data_inicio = timezone.localtime(alloc.data_inicio, BR_TZ).strftime('%d/%m/%Y %H:%M') if alloc.data_inicio else '—'
        data_fim    = timezone.localtime(alloc.data_fim, BR_TZ).strftime('%d/%m/%Y %H:%M') if alloc.data_fim else '—'

        qtd_pausas = alloc.pausas.count()

        # Tempo total de atendimento (descontando pausas)
        if alloc.data_inicio:
            fim = alloc.data_fim or timezone.now()
            total_delta = fim - alloc.data_inicio
            total_seconds = int(total_delta.total_seconds())

            # Subtrai o tempo somado de cada pausa registrada
            for pausa in alloc.pausas.all():
                if pausa.data_retorno:
                    pausa_delta = pausa.data_retorno - pausa.data_pausa
                    total_seconds -= int(pausa_delta.total_seconds())
                else:
                    # Pausa ainda aberta: desconta até agora ou até data_fim
                    pausa_fim = alloc.data_fim or timezone.now()
                    pausa_delta = pausa_fim - pausa.data_pausa
                    total_seconds -= int(pausa_delta.total_seconds())

            total_seconds = max(0, total_seconds)
            tempo_min = round(total_seconds / 60, 1)
        else:
            tempo_min = '—'

        row_data = [
            alloc.tecnico.nome,
            alloc.tecnico.matricula,
            setor_nome,
            maquina_nome,
            crit_label,
            status_label,
            data_inicio,
            data_fim,
            qtd_pausas,
            tempo_min,
        ]

        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            if row_fill:
                cell.fill = row_fill
            # Colunas de texto longo ficam alinhadas à esquerda
            if col_idx in (1, 3, 4, 6):
                cell.alignment = left_align
            else:
                cell.alignment = center_align

        ws.row_dimensions[row_idx].height = 20

    # Congela cabeçalhos
    ws.freeze_panes = 'A3'

    # ── Geração do arquivo em memória ─────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    data_str = timezone.localtime(timezone.now()).strftime('%Y%m%d_%H%M')
    filename = f'relatorio_manutencao_{data_str}.xlsx'

    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
