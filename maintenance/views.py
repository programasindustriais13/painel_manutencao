from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse
from functools import wraps
import json
import io
import datetime
from django.db.models import Prefetch
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import Sector, Machine, Technician, Allocation, HistoricoPausa, HistoricoEscala
from .forms import (
    SectorForm, MachineForm, TechnicianForm,
    StartServiceForm, PauseServiceForm, FinishServiceForm
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de permissão de grupo
# ─────────────────────────────────────────────────────────────────────────────

def _user_is_operador(user):
    """Retorna True apenas para Operadores/Administradores (grupo 'Operadores', superuser, staff, ou grupo legado 'Operador')."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=['Operadores', 'Operador']).exists()


def _user_is_lider_ou_operador(user):
    """Retorna True para Operadores e Técnicos Líderes (grupos 'Operadores', 'Tecnicos_Lideres', 'Operador', superuser, staff)."""
    if _user_is_operador(user):
        return True
    return user.groups.filter(name='Tecnicos_Lideres').exists()


def _get_technician_proprio(user):
    """Retorna o Técnico vinculado ao usuário, ou None se não houver."""
    try:
        return user.technician_profile
    except Exception:
        return None


# Decorator para views que exigem Operador/Admin COMPLETO (cadastros, etc.).
# Redireciona usuários sem acesso para /management/ com alerta.
def operador_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_is_operador(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(
            request,
            "Acesso restrito a Operadores/Administradores. Esta seção não está disponível para o seu perfil."
        )
        return redirect('technician_management')
    return wrapper


# Decorator para /dashboard/ e exportação Excel.
# Permite: Operadores e Tecnicos_Lideres. Bloqueia outros (redireciona para /management/).
def lider_ou_operador_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_is_lider_ou_operador(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(
            request,
            "Acesso restrito. Esta página requer perfil de Técnico Líder ou superior."
        )
        return redirect('technician_management')
    return wrapper


# Decorator para /management/ — acessível por todos os perfis com login vinculado ou do grupo adequado.
def tecnico_or_operador_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if (user.is_superuser or user.is_staff or 
            user.groups.filter(name__in=['Operadores', 'Tecnicos_Lideres', 'Tecnicos', 'Operador']).exists() or 
            _get_technician_proprio(user)):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. Faça login com credenciais válidas.")
        return redirect('login')
    return wrapper


@login_required
def home_redirect(request):
    user = request.user
    # Visualizador / usuário 'tv' → painel TV
    if user.groups.filter(name='Visualizador').exists() or user.username == 'tv':
        return redirect('tv_dashboard')
    # Técnico Líder → painel de controle de técnicos (/management/)
    if user.groups.filter(name='Tecnicos_Lideres').exists():
        return redirect('technician_management')
    # Técnico comum (se estiver no grupo Tecnicos) → painel de controle de técnicos
    if user.groups.filter(name='Tecnicos').exists():
        return redirect('technician_management')
        
    # Fallback para perfis legados / técnicos vinculados
    tecnico = _get_technician_proprio(user)
    if tecnico and tecnico.perfil == 'TECNICO_LIDER':
        return redirect('technician_management')
    if tecnico and tecnico.perfil == 'TECNICO':
        return redirect('technician_management')
        
    # Operadores, staff, superuser, técnicos OPERADOR → dashboard
    return redirect('dashboard')


# ----------------------------------------------------
# 1. TELA A: PAINEL INFORMATIVO DE FÁBRICA (MODO TV)
# ----------------------------------------------------
@login_required
def tv_dashboard(request):
    user = request.user
    # Permitir apenas se for Operador/Admin ou se estiver no grupo Visualizador ou username tv
    is_tv_viewer = user.groups.filter(name='Visualizador').exists() or user.username == 'tv'
    is_operador = user.is_superuser or user.is_staff or user.groups.filter(name__in=['Operadores', 'Operador']).exists()
    
    if not (is_tv_viewer or is_operador):
        messages.error(request, "Acesso negado. A TV de exibição é restrita para o seu perfil.")
        return redirect('technician_management')

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
# 2. TELA C: GERENCIAMENTO DE TÉCNICOS EM TEMPO REAL
# Acessível por Operadores (acesso total) e Técnicos vinculados (somente próprio card).
# ----------------------------------------------------
@tecnico_or_operador_required
def technician_management(request):
    technicians = Technician.objects.all().order_by('nome')

    # Instantiate blank forms to render in the modals
    start_form = StartServiceForm()
    pause_form = PauseServiceForm()
    finish_form = FinishServiceForm()

    # Determina contexto de permissão do usuário logado
    is_operador = _user_is_operador(request.user)          # True apenas para OPERADOR puro
    can_manage  = _user_is_lider_ou_operador(request.user) # True para OPERADOR e TECNICO_LIDER
    tecnico_proprio = _get_technician_proprio(request.user)
    technician_proprio_id = tecnico_proprio.id if tecnico_proprio else None

    context = {
        'technicians': technicians,
        'start_form': start_form,
        'pause_form': pause_form,
        'finish_form': finish_form,
        'user_is_operador': is_operador,   # usado apenas para o botão "Cadastros"
        'user_can_manage': can_manage,     # usado para ações dos cards e widget de escala
        'technician_proprio_id': technician_proprio_id,
    }
    return render(request, 'maintenance/technician_management.html', context)


# Action: Start Service
@login_required
def start_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)

        # Verificação de permissão: apenas TECNICO comum tem restrição ao próprio card.
        # TECNICO_LIDER e OPERADOR podem agir em qualquer card.
        if not _user_is_lider_ou_operador(request.user):
            tecnico_proprio = _get_technician_proprio(request.user)
            if not tecnico_proprio or tecnico_proprio.id != technician.id:
                messages.error(request, "Acesso negado. Você só pode iniciar serviços no seu próprio card.")
                return redirect('technician_management')

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
            allocation.usuario_operador = request.user
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
@login_required
def pause_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)

        # Verificação de permissão: apenas TECNICO comum tem restrição ao próprio card.
        if not _user_is_lider_ou_operador(request.user):
            tecnico_proprio = _get_technician_proprio(request.user)
            if not tecnico_proprio or tecnico_proprio.id != technician.id:
                messages.error(request, "Acesso negado. Você só pode pausar serviços no seu próprio card.")
                return redirect('technician_management')

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
@login_required
def resume_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)

        # Verificação de permissão: apenas TECNICO comum tem restrição ao próprio card.
        if not _user_is_lider_ou_operador(request.user):
            tecnico_proprio = _get_technician_proprio(request.user)
            if not tecnico_proprio or tecnico_proprio.id != technician.id:
                messages.error(request, "Acesso negado. Você só pode retomar serviços no seu próprio card.")
                return redirect('technician_management')

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
@login_required
def resume_paused_allocation(request, allocation_id):
    if request.method == 'POST':
        alloc_to_resume = get_object_or_404(Allocation, id=allocation_id)
        technician = alloc_to_resume.tecnico

        # Verificação de permissão: apenas TECNICO comum tem restrição ao próprio card.
        if not _user_is_lider_ou_operador(request.user):
            tecnico_proprio = _get_technician_proprio(request.user)
            if not tecnico_proprio or tecnico_proprio.id != technician.id:
                messages.error(request, "Acesso negado. Você só pode retomar alocações do seu próprio card.")
                return redirect('technician_management')

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
@login_required
def finish_service(request, technician_id):
    if request.method == 'POST':
        technician = get_object_or_404(Technician, id=technician_id)

        # Verificação de permissão: apenas TECNICO comum tem restrição ao próprio card.
        if not _user_is_lider_ou_operador(request.user):
            tecnico_proprio = _get_technician_proprio(request.user)
            if not tecnico_proprio or tecnico_proprio.id != technician.id:
                messages.error(request, "Acesso negado. Você só pode concluir serviços no seu próprio card.")
                return redirect('technician_management')
        
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
            return redirect(f'/management/?open_modal=finish_tech&tech_id={technician_id}')
                    
    return redirect('technician_management')


# Action: Finish Allocation (finaliza uma alocação específica por ID — ativa OU pausada)
@login_required
def finish_allocation(request, allocation_id):
    if request.method == 'POST':
        alloc = get_object_or_404(Allocation, id=allocation_id)
        technician = alloc.tecnico

        # Verificação de permissão: apenas TECNICO comum tem restrição ao próprio card.
        if not _user_is_lider_ou_operador(request.user):
            tecnico_proprio = _get_technician_proprio(request.user)
            if not tecnico_proprio or tecnico_proprio.id != technician.id:
                messages.error(request, "Acesso negado. Você só pode finalizar alocações do seu próprio card.")
                return redirect('technician_management')
        
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
            return redirect(f'/management/?open_modal=finish_alloc&alloc_id={allocation_id}')
                    
    return redirect('technician_management')


# Action: Set Availability / Absence status
@login_required
def set_availability(request, technician_id):
    """Permite ao OPERADOR definir o status de escala/ausência do técnico.

    Técnicos com perfil TECNICO NÃO podem alterar escalas.

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
    # OPERADOR e TECNICO_LIDER podem alterar escala. Técnico comum não.
    if not _user_is_lider_ou_operador(request.user):
        messages.error(request, "Acesso negado. Somente Técnicos Líderes e Operadores podem alterar escalas e disponibilidade.")
        return redirect('technician_management')
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
@lider_ou_operador_required
def dashboard(request):
    # ── Filtro de Período (GET) ─────────────────────────────────────────────
    # Captura parâmetros data_inicio e data_final da query string.
    # Valida o formato DD/MM/YYYY ou YYYY-MM-DD (input type="date" envia YYYY-MM-DD).
    # Fallback: últimos 30 dias se os parâmetros forem ausentes ou inválidos.
    today = timezone.localdate()
    default_inicio = today - datetime.timedelta(days=30)

    data_inicio_str = request.GET.get('data_inicio', '').strip()
    data_final_str  = request.GET.get('data_final',  '').strip()

    try:
        data_inicio = datetime.date.fromisoformat(data_inicio_str) if data_inicio_str else default_inicio
    except ValueError:
        data_inicio = default_inicio
        data_inicio_str = ''

    try:
        data_final = datetime.date.fromisoformat(data_final_str) if data_final_str else today
    except ValueError:
        data_final = today
        data_final_str = ''

    # Garante ordem correta (inicio <= fim)
    if data_inicio > data_final:
        data_inicio, data_final = data_final, data_inicio

    # Strings formatadas para popular os inputs do formulário (formato YYYY-MM-DD)
    data_inicio_str = data_inicio.isoformat()
    data_final_str  = data_final.isoformat()

    # ── KPI cards (snapshot do status ATUAL dos técnicos — sem filtro temporal) ──
    total_techs  = Technician.objects.count()
    active_techs = Technician.objects.filter(status='EM_ATENDIMENTO').count()
    paused_techs = Technician.objects.filter(status='EM_PAUSA').count()
    idle_techs   = Technician.objects.filter(status='OCIOSO').count()
    absent_techs = Technician.objects.filter(
        status__in=list(Technician.STATUS_AUSENCIA)
    ).count()

    # Distinct machines currently undergoing maintenance (data_fim is null)
    # machines_in_maintenance = Machine.objects.filter(
    #     allocations__data_fim__isnull=True
    # ).distinct().count()

    # ── Base queryset filtrado pelo período com prefetches ─────────────────
    alloc_filtrado = Allocation.objects.filter(
        data_inicio__date__range=[data_inicio, data_final]
    ).select_related('tecnico', 'maquina', 'maquina__setor').prefetch_related('pausas')

    now = timezone.now()
    
    total_bruto_segundos = 0.0
    total_liquido_segundos = 0.0
    concluidas_net_durations = []
    
    # Agrupamentos para gráficos
    maquina_segundos = {}
    maquina_chamados = {}
    criticidade_segundos = {
        'BAIXA': 0.0,
        'MEDIA': 0.0,
        'ALTA': 0.0,
    }
    
    # Para o gráfico de setores (Volume de atendimentos por setor) - mantendo compatibilidade
    sectors = Sector.objects.all()
    alloc_by_sector = {s.nome: 0 for s in sectors}
    
    for alloc in alloc_filtrado:
        # Cálculo de tempo bruto
        if alloc.data_fim:
            gross_seconds = (alloc.data_fim - alloc.data_inicio).total_seconds()
        else:
            gross_seconds = (now - alloc.data_inicio).total_seconds()
        
        gross_seconds = max(0.0, gross_seconds)
        
        # Cálculo de pausas
        pause_seconds = 0.0
        for p in alloc.pausas.all():
            if p.data_retorno:
                p_end = p.data_retorno
            else:
                p_end = alloc.data_fim or now
            
            p_dur = (p_end - p.data_pausa).total_seconds()
            p_dur = max(0.0, p_dur)
            pause_seconds += p_dur
            
        net_seconds = max(0.0, gross_seconds - pause_seconds)
        
        # Acumuladores
        total_bruto_segundos += gross_seconds
        total_liquido_segundos += net_seconds
        
        if alloc.status == 'CONCLUIDO':
            concluidas_net_durations.append(net_seconds)
            
        # Agrupamento Criticidade (horas de manutenção)
        if alloc.maquina:
            crit = alloc.maquina.criticidade
            if crit in criticidade_segundos:
                criticidade_segundos[crit] += gross_seconds
            else:
                criticidade_segundos[crit] = criticidade_segundos.get(crit, 0.0) + gross_seconds
            
            # Agrupamento Máquinas Ofensoras (Top 5 Máquinas) - ignorando projetos e fábrica
            m_nome = alloc.maquina.nome
            m_nome_lower = m_nome.lower()
            if not ('projeto' in m_nome_lower or 'fabrica' in m_nome_lower or 'fábrica' in m_nome_lower):
                maquina_segundos[m_nome] = maquina_segundos.get(m_nome, 0.0) + gross_seconds
                maquina_chamados[m_nome] = maquina_chamados.get(m_nome, 0) + 1
            
            # Volume de atendimentos por setor
            if alloc.maquina.setor:
                s_nome = alloc.maquina.setor.nome
                if s_nome in alloc_by_sector:
                    alloc_by_sector[s_nome] += 1
                else:
                    alloc_by_sector[s_nome] = alloc_by_sector.get(s_nome, 0) + 1

    # 1. MTTR por Equipamento (excluindo projetos/fábrica)
    maquina_concluidas_net = {}
    maquina_concluidas_count = {}
    for alloc in alloc_filtrado:
        if alloc.status == 'CONCLUIDO' and alloc.maquina:
            m_nome = alloc.maquina.nome
            m_nome_lower = m_nome.lower()
            if not ('projeto' in m_nome_lower or 'fabrica' in m_nome_lower or 'fábrica' in m_nome_lower):
                if alloc.data_fim:
                    gross_seconds = (alloc.data_fim - alloc.data_inicio).total_seconds()
                else:
                    gross_seconds = (now - alloc.data_inicio).total_seconds()
                gross_seconds = max(0.0, gross_seconds)
                
                pause_seconds = 0.0
                for p in alloc.pausas.all():
                    if p.data_retorno:
                        p_end = p.data_retorno
                    else:
                        p_end = alloc.data_fim or now
                    p_dur = (p_end - p.data_pausa).total_seconds()
                    pause_seconds += max(0.0, p_dur)
                    
                net_seconds = max(0.0, gross_seconds - pause_seconds)
                
                maquina_concluidas_net[m_nome] = maquina_concluidas_net.get(m_nome, 0.0) + net_seconds
                maquina_concluidas_count[m_nome] = maquina_concluidas_count.get(m_nome, 0) + 1

    mttr_equipamentos = {}
    for m_nome, net_sec in maquina_concluidas_net.items():
        count = maquina_concluidas_count[m_nome]
        if count > 0:
            mttr_equipamentos[m_nome] = round((net_sec / count) / 60.0, 1) # em minutos

    # Ordenar por MTTR decrescente
    sorted_mttr_equip = sorted(mttr_equipamentos.items(), key=lambda x: x[1], reverse=True)
    mttr_equip_labels = [item[0] for item in sorted_mttr_equip]
    mttr_equip_values = [item[1] for item in sorted_mttr_equip]

    # 2. Índice de Eficiência Operacional
    if total_bruto_segundos > 0:
        eficiencia_percent = round((total_liquido_segundos / total_bruto_segundos) * 100, 1)
        eficiencia_display = f"{eficiencia_percent}%"
    else:
        eficiencia_display = "N/A"

    # 3. Taxa de Utilização da Equipe (Simplificada)
    total_horas_liquidas = total_liquido_segundos / 3600.0
    total_dias = (data_final - data_inicio).days + 1
    capacidade_horas = total_dias * 8.0 * total_techs
    if capacidade_horas > 0:
        utilizacao_percent = round((total_horas_liquidas / capacidade_horas) * 100, 1)
        utilizacao_display = f"{utilizacao_percent}%"
    else:
        utilizacao_display = "N/A"

    # 4. Gráfico 1: Pareto de Serviços Executados (agrupado por atividade_observacao)
    servicos_segundos = {}
    for alloc in alloc_filtrado:
        if alloc.status == 'CONCLUIDO':
            desc = (alloc.atividade_observacao or 'Sem descrição').strip()
            if not desc:
                desc = 'Sem descrição'
            
            # Cálculo de tempo bruto
            if alloc.data_fim:
                gross_seconds = (alloc.data_fim - alloc.data_inicio).total_seconds()
            else:
                gross_seconds = (now - alloc.data_inicio).total_seconds()
            gross_seconds = max(0.0, gross_seconds)
            
            # Cálculo de pausas
            pause_seconds = 0.0
            for p in alloc.pausas.all():
                if p.data_retorno:
                    p_end = p.data_retorno
                else:
                    p_end = alloc.data_fim or now
                p_dur = (p_end - p.data_pausa).total_seconds()
                pause_seconds += max(0.0, p_dur)
                
            net_seconds = max(0.0, gross_seconds - pause_seconds)
            servicos_segundos[desc] = servicos_segundos.get(desc, 0.0) + net_seconds

    sorted_servicos = sorted(servicos_segundos.items(), key=lambda x: x[1], reverse=True)[:15]
    servico_labels = [item[0] for item in sorted_servicos]
    servico_values = [round(item[1] / 3600.0, 1) for item in sorted_servicos] # em horas

    # 5. Gráfico 2: Top 5 Máquinas Ofensoras (tempo bruto de manutenção)
    sorted_maquinas = sorted(maquina_segundos.items(), key=lambda x: x[1], reverse=True)[:5]
    ofensoras_labels = [item[0] for item in sorted_maquinas]
    ofensoras_durations = [round(item[1] / 3600.0, 1) for item in sorted_maquinas] # em horas
    ofensoras_counts = [maquina_chamados[item[0]] for item in sorted_maquinas]

    # 6. Gráfico 3: Distribuição por Criticidade (Horas gastas em manutenção)
    crit_labels = ['Baixa', 'Média', 'Alta']
    crit_values = [
        round(criticidade_segundos.get('BAIXA', 0.0) / 3600.0, 1),
        round(criticidade_segundos.get('MEDIA', 0.0) / 3600.0, 1),
        round(criticidade_segundos.get('ALTA', 0.0) / 3600.0, 1)
    ]

    # 7. Pie/Doughnut Chart Data: Distribution of tech status
    status_distribution = {
        'Ocioso': idle_techs,
        'Em Atendimento': active_techs,
        'Em Pausa': paused_techs,
        'Ausente/Externo': absent_techs,
    }

    context = {
        'total_techs':  total_techs,
        'active_techs': active_techs,
        'paused_techs': paused_techs,
        'idle_techs':   idle_techs,
        'absent_techs': absent_techs,

        # Datas do filtro
        'data_inicio_str': data_inicio_str,
        'data_final_str':  data_final_str,

        # Novos KPIs
        'eficiencia_display': eficiencia_display,
        'utilizacao_display': utilizacao_display,

        # Serializações para gráficos
        'status_labels': json.dumps(list(status_distribution.keys())),
        'status_values': json.dumps(list(status_distribution.values())),

        'servico_labels': json.dumps(servico_labels),
        'servico_values': json.dumps(servico_values),

        'ofensoras_labels': json.dumps(ofensoras_labels),
        'ofensoras_durations': json.dumps(ofensoras_durations),
        'ofensoras_counts': json.dumps(ofensoras_counts),

        'crit_labels': json.dumps(crit_labels),
        'crit_values': json.dumps(crit_values),

        'mttr_equip_labels': json.dumps(mttr_equip_labels),
        'mttr_equip_values': json.dumps(mttr_equip_values),

        'sector_labels': json.dumps(list(alloc_by_sector.keys())),
        'sector_values': json.dumps(list(alloc_by_sector.values())),
    }

    # 8. Desempenho por Técnico (concluídas no período)
    tech_concluidas_net = {}
    tech_concluidas_count = {}
    for alloc in alloc_filtrado:
        if alloc.status == 'CONCLUIDO' and alloc.tecnico:
            t_nome = alloc.tecnico.nome
            
            # Cálculo de tempo bruto
            if alloc.data_fim:
                gross_seconds = (alloc.data_fim - alloc.data_inicio).total_seconds()
            else:
                gross_seconds = (now - alloc.data_inicio).total_seconds()
            gross_seconds = max(0.0, gross_seconds)
            
            # Cálculo de pausas
            pause_seconds = 0.0
            for p in alloc.pausas.all():
                if p.data_retorno:
                    p_end = p.data_retorno
                else:
                    p_end = alloc.data_fim or now
                p_dur = (p_end - p.data_pausa).total_seconds()
                pause_seconds += max(0.0, p_dur)
                
            net_seconds = max(0.0, gross_seconds - pause_seconds)
            
            tech_concluidas_net[t_nome] = tech_concluidas_net.get(t_nome, 0.0) + net_seconds
            tech_concluidas_count[t_nome] = tech_concluidas_count.get(t_nome, 0) + 1

    tech_data = []
    for t_nome, count in tech_concluidas_count.items():
        net_sec = tech_concluidas_net.get(t_nome, 0.0)
        mttr_min = round((net_sec / count) / 60.0, 1) if count > 0 else 0.0
        tech_data.append((t_nome, count, mttr_min))

    # Ordenar por volume decrescente
    tech_data_sorted = sorted(tech_data, key=lambda x: x[1], reverse=True)
    tech_desempenho_labels = [item[0] for item in tech_data_sorted]
    tech_desempenho_volumes = [item[1] for item in tech_data_sorted]
    tech_desempenho_mttrs = [item[2] for item in tech_data_sorted]

    context['tech_desempenho_labels'] = json.dumps(tech_desempenho_labels)
    context['tech_desempenho_volumes'] = json.dumps(tech_desempenho_volumes)
    context['tech_desempenho_mttrs'] = json.dumps(tech_desempenho_mttrs)

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
            technician = form.save(commit=False)
            # Processa criação de usuário se username foi fornecido
            username = form.cleaned_data.get('username_login', '').strip()
            senha = form.cleaned_data.get('senha_acesso', '').strip()
            perfil = form.cleaned_data.get('perfil_acesso', 'TECNICO') or 'TECNICO'
            if username and senha:
                user = User.objects.create_user(username=username, password=senha)
                technician.user = user

            if technician.user:
                # Sincroniza grupo nativo do Django
                from django.contrib.auth.models import Group
                technician.user.groups.clear()
                if perfil == 'TECNICO':
                    technician.user.groups.add(Group.objects.get(name='Tecnicos'))
                elif perfil == 'TECNICO_LIDER':
                    technician.user.groups.add(Group.objects.get(name='Tecnicos_Lideres'))
                elif perfil == 'OPERADOR':
                    technician.user.groups.add(Group.objects.get(name='Operadores'))
            technician.perfil = perfil
            technician.save()
            messages.success(request, "Técnico cadastrado com sucesso." + (
                f" Usuário '{username}' criado e vinculado." if username and senha else ""
            ))
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
            technician = form.save(commit=False)
            # Processa criação/atualização de usuário se username foi fornecido
            username = form.cleaned_data.get('username_login', '').strip()
            senha = form.cleaned_data.get('senha_acesso', '').strip()
            perfil = form.cleaned_data.get('perfil_acesso', 'TECNICO') or 'TECNICO'
            if username:
                if technician.user:
                    # Autoriza alteração do usuário já vinculado
                    technician.user.username = username
                    if senha:
                        technician.user.set_password(senha)
                    technician.user.save()
                elif senha:
                    # Cria um novo usuário e vincula
                    user = User.objects.create_user(username=username, password=senha)
                    technician.user = user

            if technician.user:
                # Sincroniza grupo nativo do Django
                from django.contrib.auth.models import Group
                technician.user.groups.clear()
                if perfil == 'TECNICO':
                    technician.user.groups.add(Group.objects.get(name='Tecnicos'))
                elif perfil == 'TECNICO_LIDER':
                    technician.user.groups.add(Group.objects.get(name='Tecnicos_Lideres'))
                elif perfil == 'OPERADOR':
                    technician.user.groups.add(Group.objects.get(name='Operadores'))
            technician.perfil = perfil
            technician.save()
            msg_extra = ""
            if username:
                msg_extra = f" Usuário '{username}' atualizado/vinculado com perfil {perfil}."
            messages.success(request, "Técnico atualizado com sucesso." + msg_extra)
            return redirect('crud_list')
    else:
        form = TechnicianForm(instance=technician)
        # Pré-preencher username e perfil se já houver usuário vinculado
        if technician.user:
            form.initial['username_login'] = technician.user.username
        form.initial['perfil_acesso'] = technician.perfil or 'TECNICO'
    return render(request, 'maintenance/technician_form.html', {'form': form, 'title': 'Editar Técnico', 'technician': technician})

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
@lider_ou_operador_required
def exportar_relatorio_excel(request):
    """
    Gera e retorna um arquivo Excel (.xlsx) com o relatório detalhado de alocações.
    Respeita os parâmetros GET data_inicio e data_final (formato YYYY-MM-DD) para
    filtrar somente o período selecionado no Dashboard — o mesmo filtro unificado
    que restringe os gráficos da tela.

    Colunas exportadas (13 no total):
      A  Técnico          B  Matrícula        C  Setor
      D  Máquina          E  Criticidade      F  Operador
      G  Status           H  Data de Início   I  Data de Término
      J  Tempo Total(min) K  Obs. Inicial     L  Obs. de Conclusão
      M  Histórico de Pausas (pausas concatenadas, quebra de linha)

    Requer: openpyxl >= 3.1.0
    """
    # ── Filtro de Período (mesmos parâmetros GET do Dashboard) ─────────────
    today = timezone.localdate()
    default_inicio = today - datetime.timedelta(days=30)

    data_inicio_str = request.GET.get('data_inicio', '').strip()
    data_final_str  = request.GET.get('data_final',  '').strip()

    try:
        data_inicio = datetime.date.fromisoformat(data_inicio_str) if data_inicio_str else default_inicio
    except ValueError:
        data_inicio = default_inicio

    try:
        data_final = datetime.date.fromisoformat(data_final_str) if data_final_str else today
    except ValueError:
        data_final = today

    if data_inicio > data_final:
        data_inicio, data_final = data_final, data_inicio

    # ── Busca alocações do período com todos os dados relacionados ──────────
    allocations = Allocation.objects.filter(
        data_inicio__date__range=[data_inicio, data_final]
    ).select_related(
        'tecnico', 'maquina', 'maquina__setor', 'usuario_operador'
    ).prefetch_related('pausas').order_by('-data_inicio')

    # ── Workbook ──────────────────────────────────────────────────────────
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Relatório de Alocações"

    # ── Estilos ───────────────────────────────────────────────────────────
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

    CRIT_LABELS = {'BAIXA': 'Baixa', 'MEDIA': 'Média', 'ALTA': 'Alta'}
    STATUS_LABELS = {
        'EM_ATENDIMENTO': 'Em Atendimento',
        'EM_PAUSA': 'Em Pausa',
        'CONCLUIDO': 'Concluído',
    }
    BR_TZ = timezone.get_current_timezone()

    # ── Título da planilha (13 colunas: A1:M1) ────────────────────────────
    periodo_label = f"{data_inicio.strftime('%d/%m/%Y')} a {data_final.strftime('%d/%m/%Y')}"
    ws.merge_cells('A1:M1')
    title_cell = ws['A1']
    title_cell.value = (
        f"Relatório de Manutenção — Período: {periodo_label} — "
        f"Exportado em {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')}"
    )
    title_cell.font      = Font(name='Calibri', bold=True, size=13, color='1E3A5F')
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    # ── Cabeçalhos (13 colunas) ───────────────────────────────────────────
    HEADERS = [
        'Técnico', 'Matrícula', 'Setor', 'Máquina', 'Criticidade',
        'Operador', 'Status', 'Data de Início', 'Data de Término',
        'Tempo Total (min)', 'Obs. Inicial', 'Obs. de Conclusão',
        'Histórico de Pausas',
    ]
    COL_WIDTHS = [22, 14, 18, 22, 12, 20, 16, 20, 20, 18, 35, 35, 45]

    for col_idx, (header, width) in enumerate(zip(HEADERS, COL_WIDTHS), start=1):
        cell = ws.cell(row=2, column=col_idx, value=header)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = header_align
        cell.border    = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[2].height = 30

    # ── Linhas de dados ───────────────────────────────────────────────────
    for row_idx, alloc in enumerate(allocations, start=3):
        is_alt   = (row_idx % 2 == 0)
        row_fill = alt_fill if is_alt else None

        # Dados básicos derivados
        setor_nome   = alloc.maquina.setor.nome if alloc.maquina and alloc.maquina.setor else '—'
        maquina_nome = alloc.maquina.nome        if alloc.maquina else '—'
        crit_label   = CRIT_LABELS.get(alloc.maquina.criticidade, '—') if alloc.maquina else '—'
        status_label = STATUS_LABELS.get(alloc.status, alloc.status)

        # Operador responsável pela alocação
        if alloc.usuario_operador:
            nome_completo = alloc.usuario_operador.get_full_name()
            operador_label = nome_completo if nome_completo.strip() else alloc.usuario_operador.username
        else:
            operador_label = '—'

        # Datas formatadas
        data_inicio_fmt = (
            timezone.localtime(alloc.data_inicio, BR_TZ).strftime('%d/%m/%Y %H:%M')
            if alloc.data_inicio else '—'
        )
        data_fim_fmt = (
            timezone.localtime(alloc.data_fim, BR_TZ).strftime('%d/%m/%Y %H:%M')
            if alloc.data_fim else '—'
        )

        # Tempo total de atendimento (descontando pausas)
        if alloc.data_inicio:
            fim = alloc.data_fim or timezone.now()
            total_seconds = int((fim - alloc.data_inicio).total_seconds())
            for pausa in alloc.pausas.all():
                if pausa.data_retorno:
                    total_seconds -= int((pausa.data_retorno - pausa.data_pausa).total_seconds())
                else:
                    pausa_fim = alloc.data_fim or timezone.now()
                    total_seconds -= int((pausa_fim - pausa.data_pausa).total_seconds())
            tempo_min = round(max(0, total_seconds) / 60, 1)
        else:
            tempo_min = '—'

        # Observação inicial
        obs_inicial = alloc.atividade_observacao or '—'

        # Observação de conclusão
        obs_conclusao = alloc.observacao_conclusao or '—'

        # Histórico de pausas — concatenado com quebras de linha
        pausas_linhas = []
        for pausa in alloc.pausas.all().order_by('data_pausa'):
            p_inicio = timezone.localtime(pausa.data_pausa, BR_TZ).strftime('%d/%m/%Y %H:%M')
            if pausa.data_retorno:
                p_retorno = timezone.localtime(pausa.data_retorno, BR_TZ).strftime('%d/%m/%Y %H:%M')
            else:
                p_retorno = 'Em aberto'
            motivo = (pausa.motivo_pausa or '').strip()
            pausas_linhas.append(f"↓ {p_inicio}  →  {p_retorno} | {motivo}")
        historico_pausas = '\n'.join(pausas_linhas) if pausas_linhas else '—'

        row_data = [
            alloc.tecnico.nome,   # A
            alloc.tecnico.matricula,  # B
            setor_nome,           # C
            maquina_nome,         # D
            crit_label,           # E
            operador_label,       # F
            status_label,         # G
            data_inicio_fmt,      # H
            data_fim_fmt,         # I
            tempo_min,            # J
            obs_inicial,          # K
            obs_conclusao,        # L
            historico_pausas,     # M
        ]

        # Colunas de texto longo: A(1) C(3) D(4) F(6) G(7) K(11) L(12) M(13)
        LEFT_COLS = {1, 3, 4, 6, 7, 11, 12, 13}

        for col_idx, value in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            if row_fill:
                cell.fill = row_fill
            cell.alignment = left_align if col_idx in LEFT_COLS else center_align

        # Altura dinâmica: linhas com histórico de pausas recebem mais altura
        n_pausas = len(pausas_linhas)
        ws.row_dimensions[row_idx].height = max(20, 18 * max(1, n_pausas))

    # Congela cabeçalhos
    ws.freeze_panes = 'A3'

    # ── Geração do arquivo em memória ─────────────────────────────────────
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    data_str   = timezone.localtime(timezone.now()).strftime('%Y%m%d_%H%M')
    periodo_fn = f"{data_inicio.strftime('%Y%m%d')}-{data_final.strftime('%Y%m%d')}"
    filename   = f'relatorio_manutencao_{periodo_fn}_{data_str}.xlsx'

    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ─────────────────────────────────────────────────────────────────────────────
# PWA: View para servir o Service Worker a partir da raiz do site
# ─────────────────────────────────────────────────────────────────────────────
def service_worker_view(request):
    """Serve o arquivo service-worker.js com Content-Type e Service-Worker-Allowed
    adequados para que o Service Worker tenha escopo sobre toda a aplicação (/).
    
    Não requer autenticação para que o SW possa ser registrado na tela de login.
    """
    import os
    from django.conf import settings

    sw_path = os.path.join(
        settings.BASE_DIR, 'maintenance', 'static', 'maintenance', 'service-worker.js'
    )

    try:
        with open(sw_path, 'r', encoding='utf-8') as f:
            sw_content = f.read()
    except FileNotFoundError:
        return HttpResponse('// Service Worker not found', content_type='application/javascript', status=404)

    response = HttpResponse(sw_content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response

