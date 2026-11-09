import json
from urllib.parse import urlencode
from datetime import timedelta, datetime, timezone as dt_timezone
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse, FileResponse, Http404
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger, Page
from django.db import transaction
from django.db.models import Q
from maintenance.models import Machine
from .decorators import lider_producao_required, lider_ou_pcp_required, superuser_required
from .services import ProductionStateService, PCPCalculationService, BladderTrackingService, scada_reader
from .services_calandra import CalandraHistoricalService
from .services_caldeira import CaldeiraHistoricalService, CALDEIRA_VARIABLES_CONFIG
from .services_caldeira_fast import CaldeiraFastReader
from .services_caldeira_insights import CaldeiraInsightsService, PRESS_STATUS_XIDS, DOOR_XID
from .caldeira_insights_jobs import job_key as caldeira_insights_job_key, read_result as read_caldeira_insights_result, read_state as read_caldeira_insights_state, ensure_job as ensure_caldeira_insights_job
from .caldeira_insights_excel import build_insights_excel
from .caldeira_export_jobs import start_job as start_caldeira_export_job, read_job as read_caldeira_export_job, output_path as caldeira_export_output_path
from .xid_configuration import XIDRegistry, XIDDiagnosticsService, XIDTestService
from .models import (

    ProductionTarget,
    ProductionMatrixCatalog,
    ProductionShift,
    ProductionPCPPlan,
    ProductionBladderUsage,
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    CaldeiraAnalysisSettings,
)
from .forms import (
    ProductionTargetForm,
    ProductionMatrixCatalogForm,
    ProductionPCPPlanForm,
    ProductionMachineConfigForm,
    ProductionCavityConfigForm,
    get_cavity_formset,
    ProductionGlobalParameterForm,
    ProductionGlobalAlarmForm,
    CaldeiraAnalysisSettingsForm,
)




@lider_producao_required
def production_dashboard(request):
    """
    Renderiza o dashboard geral do módulo de produção.
    """
    data_inicio = request.GET.get("data_inicio", "").strip()
    data_final = request.GET.get("data_final", "").strip()
    periodo = request.GET.get("periodo", "").strip()

    state = ProductionStateService.get_dashboard_state(
        data_inicio_str=data_inicio if data_inicio else None,
        data_final_str=data_final if data_final else None,
        periodo=periodo if periodo else None
    )
    return render(request, "production/dashboard.html", state)


@lider_producao_required
def machine_detail(request, pk):
    """
    Renderiza os detalhes e histórico de paradas de uma máquina específica.
    """
    inicio = request.GET.get("inicio", "").strip()
    fim = request.GET.get("fim", "").strip()
    data_inicio = request.GET.get("data_inicio", "").strip()
    data_final = request.GET.get("data_final", "").strip()
    periodo = request.GET.get("periodo", "").strip()
    page = request.GET.get("page", "1").strip()

    detail_state = ProductionStateService.get_machine_detail(
        config_id=pk,
        inicio_str=inicio if inicio else None,
        fim_str=fim if fim else None,
        data_inicio_str=data_inicio if data_inicio else None,
        data_final_str=data_final if data_final else None,
        periodo=periodo if periodo else None,
        page=page
    )

    # Histórico Integrado da Prensa: [ Todos | Manutenção | Matrizaria ]
    from maintenance.views import _user_can_access_maintenance, _user_can_access_matrizaria
    from matrizaria.services import MatrizariaService

    origem_filtro = request.GET.get("origem_filtro", "TODOS").upper()
    can_view_maint = _user_can_access_maintenance(request.user)
    can_view_matriz = _user_can_access_matrizaria(request.user)

    historico_unificado = MatrizariaService.get_unified_press_timeline(
        machine_id=detail_state["machine"].id,
        can_view_maintenance=can_view_maint,
        can_view_matrizaria=can_view_matriz,
        origem_filtro=origem_filtro,
    )
    detail_state["historico_unificado"] = historico_unificado
    detail_state["origem_filtro"] = origem_filtro
    detail_state["can_view_maint"] = can_view_maint
    detail_state["can_view_matriz"] = can_view_matriz

    return render(request, "production/machine_detail.html", detail_state)


@lider_producao_required
def cavity_detail(request, machine_id, cavity_id):
    """
    Renderiza os detalhes completos de uma cavidade específica (13 atributos da SPEC 06F).
    """
    context = ProductionStateService.get_cavity_detail(
        machine_id=machine_id,
        cavity_id=cavity_id
    )
    if not context:
        from django.http import Http404
        raise Http404("Cavidade não encontrada.")
    return render(request, "production/cavity_detail.html", context)


@lider_ou_pcp_required
def target_list(request):
    """
    Área de gestão de metas da produção (/producao/metas/). Redireciona para o PCP novo.
    """
    return pcp_plan_list(request)


@lider_ou_pcp_required
def target_create(request):
    """
    Criação de meta de produção. Redireciona para a nova Programação PCP.
    """
    return redirect("production:pcp_plan_create")


@lider_ou_pcp_required
def target_edit(request, pk):
    """
    Edição de meta de produção existente.
    """
    target = get_object_or_404(ProductionTarget, pk=pk)
    if request.method == "POST":
        form = ProductionTargetForm(request.POST, instance=target)
        if form.is_valid():
            t = form.save(commit=False)
            t.updated_by = request.user
            t.save()
            messages.success(request, "Meta de produção atualizada com sucesso!")
            return redirect("production:target_list")
        else:
            messages.error(request, "Erro ao atualizar meta.")
    else:
        form = ProductionTargetForm(instance=target)

    return render(request, "production/target_form.html", {
        "form": form,
        "target": target,
    })


@lider_ou_pcp_required
def target_cancel(request, pk):
    """
    Cancela uma meta de produção (status = CANCELADO).
    """
    target = get_object_or_404(ProductionTarget, pk=pk)
    if request.method == "POST":
        target.status = "CANCELADO"
        target.updated_by = request.user
        target.save(update_fields=["status", "updated_by", "updated_at"])
        messages.success(request, f"Meta #{target.id} cancelada com sucesso.")
    return redirect("production:target_list")


@lider_ou_pcp_required
def catalog_list(request):
    """
    Gestão do Catálogo Local de Matrizes e Produtos (/producao/catalogos/matrizes/).
    """
    catalogs = ProductionMatrixCatalog.objects.all().order_by("codigo")
    if request.method == "POST":
        form = ProductionMatrixCatalogForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Matriz cadastrada no catálogo com sucesso!")
            return redirect("production:catalog_list")
        else:
            messages.error(request, "Erro ao cadastrar matriz no catálogo.")
    else:
        form = ProductionMatrixCatalogForm()

    return render(request, "production/catalog_list.html", {
        "catalogs": catalogs,
        "form": form,
    })


@lider_ou_pcp_required
def pcp_plan_list(request):
    """
    Listagem de todas as Programações PCP com suporte a filtros, progresso e ações.
    """
    plans_qs = ProductionPCPPlan.objects.select_related("matriz", "bladder").order_by("-id")

    matriz_filter = request.GET.get("matriz_id", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if matriz_filter and matriz_filter.isdigit():
        plans_qs = plans_qs.filter(matriz_id=int(matriz_filter))
    if status_filter:
        plans_qs = plans_qs.filter(status=status_filter)

    now = timezone.now()
    plans_list = list(plans_qs)

    for plan in plans_list:
        realized = PCPCalculationService.get_plan_realized_quantity(plan)
        plan.realized_total = realized
        plan.progress_pct = round((realized / plan.quantidade_programada * 100), 1) if plan.quantidade_programada > 0 else 0.0
        plan.can_delete = (plan.status == "PLANEJADO" and plan.data_hora_inicio > now and realized == 0)
        plan.can_cancel = (not plan.can_delete and plan.status not in ["CANCELADO", "ATINGIDA"])

    max_cavities = PCPCalculationService.get_available_cavities_limit()
    matrices = ProductionMatrixCatalog.objects.filter(ativo=True).order_by("nome_exibicao", "codigo_scada")

    return render(request, "production/pcp_plan_list.html", {
        "plans": plans_list,
        "matrices": matrices,
        "max_cavities": max_cavities,
        "filters": {
            "matriz_id": matriz_filter,
            "status": status_filter,
        }
    })


@lider_ou_pcp_required
def pcp_plan_create(request):
    """
    Formulário e criação de nova Programação PCP (/production/pcp/nova/).
    """
    from .forms import ProductionPCPPlanForm

    if request.method == "POST":
        form = ProductionPCPPlanForm(request.POST)
        if form.is_valid():
            matriz = form.cleaned_data["matriz"]
            start_dt = form.cleaned_data["data_hora_inicio"]
            if start_dt and timezone.is_naive(start_dt):
                start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())

            quantity = form.cleaned_data["quantidade_programada"]
            shift_choice = form.cleaned_data["turno_opcao"]
            cavities = form.cleaned_data["cavidades_disponiveis"]

            try:
                plan = PCPCalculationService.save_pcp_plan(
                    matrix_catalog=matriz,
                    start_dt=start_dt,
                    quantity=quantity,
                    shift_choice=shift_choice,
                    cavities=cavities,
                    user=request.user,
                )
                messages.success(request, f"Programação PCP #{plan.id} cadastrada e calculada com sucesso!")
                return redirect("production:pcp_plan_detail", pk=plan.pk)
            except Exception as e:
                messages.error(request, f"Erro ao calcular/salvar programação PCP: {e}")
        else:
            messages.error(request, "Por favor, corrija os erros do formulário.")
    else:
        initial_dt = timezone.localtime().replace(minute=0, second=0, microsecond=0)
        max_cavities = PCPCalculationService.get_available_cavities_limit()
        form = ProductionPCPPlanForm(initial={
            "data_hora_inicio": initial_dt,
            "turno_opcao": "AMBOS",
            "cavidades_disponiveis": min(4, max_cavities)
        })

    max_cavities = PCPCalculationService.get_available_cavities_limit()
    matrices = ProductionMatrixCatalog.objects.filter(ativo=True).order_by("nome_exibicao", "codigo_scada")

    return render(request, "production/pcp_plan_form.html", {
        "form": form,
        "matrices": matrices,
        "max_cavities": max_cavities,
    })


@lider_ou_pcp_required
def pcp_plan_edit(request, pk):
    """
    Formulário de edição de Programação PCP (em andamento ou não iniciada).
    """
    from .forms import ProductionPCPPlanForm

    plan = get_object_or_404(ProductionPCPPlan.objects.select_related("matriz", "bladder"), pk=pk)
    now = timezone.now()
    realized = PCPCalculationService.get_plan_realized_quantity(plan)
    is_started = (plan.status != "PLANEJADO" or plan.data_hora_inicio <= now or realized > 0)

    if request.method == "POST":
        form = ProductionPCPPlanForm(request.POST, instance=plan)
        reason = request.POST.get("reason", "").strip()

        if form.is_valid():
            matriz = form.cleaned_data["matriz"]
            start_dt = form.cleaned_data["data_hora_inicio"]
            if start_dt and timezone.is_naive(start_dt):
                start_dt = timezone.make_aware(start_dt, timezone.get_current_timezone())

            quantity = form.cleaned_data["quantidade_programada"]
            shift_choice = form.cleaned_data["turno_opcao"]
            cavities = form.cleaned_data["cavidades_disponiveis"]

            try:
                if is_started:
                    edited_plan = PCPCalculationService.edit_started_pcp_plan(
                        plan=plan,
                        new_quantity=quantity,
                        new_shift_choice=shift_choice,
                        new_cavities=cavities,
                        user=request.user,
                        reason=reason
                    )
                    messages.success(request, f"Programação PCP #{edited_plan.id} (em andamento) atualizada com sucesso!")
                else:
                    edited_plan = PCPCalculationService.edit_unstarted_pcp_plan(
                        plan=plan,
                        matrix_catalog=matriz,
                        start_dt=start_dt,
                        quantity=quantity,
                        shift_choice=shift_choice,
                        cavities=cavities,
                        user=request.user,
                        reason=reason
                    )
                    messages.success(request, f"Programação PCP #{edited_plan.id} recalculada e atualizada com sucesso!")
                return redirect("production:pcp_plan_detail", pk=edited_plan.pk)
            except Exception as e:
                messages.error(request, f"Erro ao atualizar programação PCP: {e}")
        else:
            messages.error(request, "Por favor, corrija os erros do formulário.")
    else:
        form = ProductionPCPPlanForm(instance=plan)

    max_cavities = PCPCalculationService.get_available_cavities_limit()
    matrices = ProductionMatrixCatalog.objects.filter(ativo=True).order_by("nome_exibicao", "codigo_scada")

    return render(request, "production/pcp_plan_form.html", {
        "form": form,
        "plan": plan,
        "is_edit": True,
        "is_started": is_started,
        "realized_qty": realized,
        "matrices": matrices,
        "max_cavities": max_cavities,
    })


@lider_ou_pcp_required
def pcp_plan_cancel(request, pk):
    """
    Cancela uma programação PCP em andamento com auditoria de motivo.
    """
    plan = get_object_or_404(ProductionPCPPlan, pk=pk)

    if request.method == "POST":
        reason = request.POST.get("reason", "Cancelamento via interface").strip()
        try:
            PCPCalculationService.cancel_pcp_plan(plan, user=request.user, reason=reason)
            messages.success(request, f"Programação PCP #{plan.id} foi cancelada com sucesso. O histórico foi preservado.")
        except Exception as e:
            messages.error(request, f"Erro ao cancelar programação PCP #{plan.id}: {e}")

    return redirect("production:pcp_plan_list")


@lider_ou_pcp_required
def pcp_plan_delete(request, pk):
    """
    Exclui fisicamente uma programação PCP não iniciada e sem produção associada.
    """
    plan = get_object_or_404(ProductionPCPPlan, pk=pk)

    if request.method == "POST":
        try:
            PCPCalculationService.delete_pcp_plan(plan, user=request.user)
            messages.success(request, f"Programação PCP #{plan.id} excluída com sucesso.")
        except Exception as e:
            messages.error(request, f"Não foi possível excluir a programação PCP #{plan.id}: {e}")

    return redirect("production:pcp_plan_list")


@lider_ou_pcp_required
def pcp_plan_detail(request, pk):
    """
    Detalhes e detalhamento por turno de uma Programação PCP (#id) com histórico de auditoria.
    """
    plan = get_object_or_404(ProductionPCPPlan.objects.select_related("matriz", "bladder", "created_by"), pk=pk)
    shift_targets = plan.shift_targets.select_related("shift", "target_legado").order_by("date", "shift__ordem_exibicao")
    history_entries = plan.history_entries.select_related("user").order_by("-created_at")

    realized = PCPCalculationService.get_plan_realized_quantity(plan)
    progress_pct = round((realized / plan.quantidade_programada * 100), 1) if plan.quantidade_programada > 0 else 0.0
    now = timezone.now()

    can_delete = (plan.status == "PLANEJADO" and plan.data_hora_inicio > now and realized == 0)
    can_cancel = (not can_delete and plan.status not in ["CANCELADO", "ATINGIDA"])

    return render(request, "production/pcp_plan_detail.html", {
        "plan": plan,
        "shift_targets": shift_targets,
        "history_entries": history_entries,
        "realized_total": realized,
        "progress_pct": progress_pct,
        "can_delete": can_delete,
        "can_cancel": can_cancel,
    })


def _parse_datetime_input(dt_str):
    from datetime import datetime
    from django.utils.dateparse import parse_datetime

    if not dt_str or not dt_str.strip():
        return timezone.localtime()

    dt_str = dt_str.strip()

    # 1. ISO format parse
    dt = parse_datetime(dt_str)

    # 2. Formats common in inputs (HTML datetime-local, BR format)
    if not dt:
        for fmt in (
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
        ):
            try:
                dt = datetime.strptime(dt_str, fmt)
                break
            except ValueError:
                pass

    if not dt:
        dt = timezone.localtime()
    elif timezone.is_naive(dt):
        tz = timezone.get_current_timezone()
        dt = timezone.make_aware(dt, tz)

    return dt


@lider_ou_pcp_required
def pcp_api_calculate(request):
    """
    Endpoint JSON AJAX para prévia dinâmica em tempo real no formulário PCP.
    """
    from django.http import JsonResponse

    matriz_id = request.GET.get("matriz_id") or request.POST.get("matriz_id")
    start_dt_str = request.GET.get("data_hora_inicio") or request.POST.get("data_hora_inicio")
    quantity_str = request.GET.get("quantidade") or request.POST.get("quantidade")
    shift_choice = request.GET.get("turno_opcao") or request.POST.get("turno_opcao") or "AMBOS"
    cavities_str = request.GET.get("cavidades") or request.POST.get("cavidades") or "1"

    if not matriz_id or not matriz_id.isdigit():
        return JsonResponse({"success": False, "error": "Selecione uma matriz válida."})

    matriz = ProductionMatrixCatalog.objects.filter(pk=int(matriz_id)).first()
    if not matriz:
        return JsonResponse({"success": False, "error": "Matriz não encontrada."})

    try:
        quantity = int(quantity_str) if quantity_str and quantity_str.isdigit() else 0
    except ValueError:
        quantity = 0

    if quantity <= 0:
        return JsonResponse({"success": False, "error": "Informe uma quantidade válida maior que zero."})

    try:
        cavities = int(cavities_str) if cavities_str and cavities_str.isdigit() else 1
    except ValueError:
        cavities = 1

    start_dt = _parse_datetime_input(start_dt_str)

    try:
        calc = PCPCalculationService.calculate_plan(
            matrix_catalog=matriz,
            start_dt=start_dt,
            quantity=quantity,
            shift_choice=shift_choice,
            cavities=cavities
        )

        shifts_data = [
            {
                "date_str": st["date"].strftime("%d/%m/%Y"),
                "shift_nome": st["shift"].nome,
                "meta_prevista": st["meta_prevista"]
            }
            for st in calc["shift_targets"]
        ]

        bladders_data = [
            {
                "id": b.id,
                "codigo": b.codigo_bladder,
                "descricao": b.descricao or ""
            }
            for b in calc["bladder_info"]["bladders"]
        ]

        auto_selected_id = calc["bladder_info"]["auto_selected"].id if calc["bladder_info"]["auto_selected"] else None
        bladder_codigo = calc["bladder_info"]["auto_selected"].codigo_bladder if calc["bladder_info"]["auto_selected"] else ("BLADDER NÃO CADASTRADO" if not calc["bladder_info"]["bladders"] else "ERRO DE CONFIGURAÇÃO")

        return JsonResponse({
            "success": True,
            "lixo_estimado": calc["lixo_estimado"],
            "ia_estimada": calc["ia_estimada"],
            "perda_total_estimada": calc["perda_total_estimada"],
            "producao_boa_estimada": calc["producao_boa_estimada"],
            "data_hora_fim_str": calc["final_dt"].strftime("%d/%m/%Y às %H:%M:%S"),
            "bladder_codigo": bladder_codigo,
            "bladders": bladders_data,
            "auto_selected_bladder_id": auto_selected_id,
            "bladder_warning": calc["bladder_info"]["warning"],
            "shift_targets": shifts_data,
        })
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


@lider_producao_required
def bladder_list(request):
    """
    Lista todos os bladders atualmente em uso nas cavidades configuradas.
    """
    filters = {
        "q": request.GET.get("q", "").strip(),
        "prensa_id": request.GET.get("prensa_id", "").strip(),
        "setup_status": request.GET.get("setup_status", "").strip(),
        "near_limit": request.GET.get("near_limit", "").strip(),
    }
    context = BladderTrackingService.get_active_bladders_context(filters)
    return render(request, "production/bladder_list.html", context)


@lider_producao_required
def bladder_history(request):
    """
    Exibe o histórico consolidado de utilizações de bladders com filtros e paginação backend.
    """
    filters = {
        "data_inicio": request.GET.get("data_inicio", "").strip(),
        "data_fim": request.GET.get("data_fim", "").strip(),
        "bla": request.GET.get("bla", "").strip(),
        "lote": request.GET.get("lote", "").strip(),
        "prensa_id": request.GET.get("prensa_id", "").strip(),
        "cavidade_id": request.GET.get("cavidade_id", "").strip(),
        "motivo_troca": request.GET.get("motivo_troca", "").strip(),
        "status": request.GET.get("status", "").strip(),
    }
    page = request.GET.get("page", 1)
    context = BladderTrackingService.get_bladder_history_context(filters, page=page)
    return render(request, "production/bladder_history.html", context)


@lider_producao_required
def bladder_detail(request, pk=None):
    """
    Exibe a ficha detalhada e consolidada do ciclo de vida completo de uma identidade de bladder (BLA + Lote).
    """
    bla_param = request.GET.get("bla", "").strip()
    lote_param = request.GET.get("lote", "").strip()

    context_data = BladderTrackingService.get_bladder_consolidated_detail(
        bla_code=bla_param if bla_param else None,
        lot_str=lote_param if lote_param else None,
        usage_id=pk
    )

    if not context_data:
        messages.error(request, "Bladder ou utilização não encontrada.")
        return redirect("production:bladder_list")

    return render(request, "production/bladder_detail.html", context_data)


# ==============================================================================
# CENTRAL DE CONFIGURAÇÃO SCADA E CADASTRO ORGANIZADO DE XIDs (SUPERUSER ONLY)
# ==============================================================================

@superuser_required
def xid_config_dashboard(request):
    """
    Visão geral da Central de Configuração SCADA / XIDs.
    Exibe contadores de preenchimento, diagnósticos de cobertura por prensa,
    detecção de duplicidades e filtros rápidos.
    """
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "all").strip()
    sector_filter = request.GET.get("sector", "vulcanizacao").strip()

    diagnostics = XIDDiagnosticsService.get_diagnostics_overview(
        search_query=q if q else None,
        status_filter=status_filter if status_filter else None,
        sector_filter=sector_filter if sector_filter else "vulcanizacao"
    )

    return render(request, "production/xid_config_dashboard.html", {
        "diagnostics": diagnostics,
        "q": q,
        "status_filter": status_filter,
        "sector_filter": sector_filter,
    })



@superuser_required
def xid_machine_config(request, pk):
    """
    Configuração individual de XIDs para uma prensa e suas respectivas cavidades.
    Utiliza transação atômica para garantir que falhas em qualquer cavidade impeçam salvamento parcial.
    """
    machine = get_object_or_404(Machine.objects.select_related("setor"), pk=pk)
    machine_cfg = getattr(machine, "production_config", None)
    is_new_config = (machine_cfg is None)

    # Identificar próxima e anterior para navegação fluida
    prev_machine = Machine.objects.filter(id__lt=machine.id).order_by("-id").first()
    next_machine = Machine.objects.filter(id__gt=machine.id).order_by("id").first()

    CavityFormSetClass = get_cavity_formset(extra=0)

    if request.method == "POST":
        if is_new_config:
            machine_cfg = ProductionMachineConfig(machine=machine)

        form = ProductionMachineConfigForm(request.POST, instance=machine_cfg)
        formset = CavityFormSetClass(request.POST, instance=machine_cfg)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic(using="default"):
                saved_cfg = form.save(commit=False)
                saved_cfg.machine = machine
                saved_cfg.save()

                formset.instance = saved_cfg
                formset.save()

                # Limpar caches de resolução do ScadaReader
                scada_reader.clear_caches()

            messages.success(request, f"Configurações da prensa '{machine.nome}' salvas com sucesso no banco padrão!")
            action = request.POST.get("action", "save")

            if action == "save_and_back":
                return redirect("production:xid_config_dashboard")
            elif action == "save_and_next":
                if next_machine:
                    return redirect("production:xid_machine_config", pk=next_machine.pk)
                else:
                    first_m = Machine.objects.all().order_by("id").first()
                    if first_m and first_m.pk != machine.pk:
                        return redirect("production:xid_machine_config", pk=first_m.pk)
                    return redirect("production:xid_config_dashboard")
            else:
                return redirect("production:xid_machine_config", pk=machine.pk)

        else:
            messages.error(
                request,
                "Erro ao salvar configurações da prensa. Verifique os campos destacados e corrija os erros."
            )
    else:
        if is_new_config:
            machine_cfg = ProductionMachineConfig(
                machine=machine,
                ordem_exibicao=1,
                stale_limit_seconds=120,
                produzindo_value="1"
            )
            form = ProductionMachineConfigForm(instance=machine_cfg)
            # Para nova configuração sem cavidades no banco, inicializa com 2 cavidades padrão
            CavityFormSetInit = get_cavity_formset(extra=2)
            formset = CavityFormSetInit(
                instance=machine_cfg,
                initial=[
                    {"nome": "Cavidade 1", "ordem": 1},
                    {"nome": "Cavidade 2", "ordem": 2},
                ]
            )
        else:
            form = ProductionMachineConfigForm(instance=machine_cfg)
            formset = CavityFormSetClass(instance=machine_cfg)

    # Inspecionar duplicidades conhecidas
    overview = XIDDiagnosticsService.get_diagnostics_overview()
    duplicates_map = overview.get("duplicates_map", {})

    return render(request, "production/xid_machine_config.html", {
        "machine": machine,
        "machine_cfg": machine_cfg,
        "is_new_config": is_new_config,
        "form": form,
        "formset": formset,
        "prev_machine": prev_machine,
        "next_machine": next_machine,
        "duplicates_map": duplicates_map,
        "machine_fields_defs": XIDRegistry.get_machine_fields(),
        "cavity_fields_defs": XIDRegistry.get_cavity_fields(),
    })


@superuser_required
def xid_global_config(request):
    """
    Gestão de Parâmetros Globais e Alarmes Globais do Scada-LTS.
    Permite cadastrar, visualizar e editar variáveis de telemetria geral da fábrica.
    """
    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "save_param":
            param_id = request.POST.get("param_id")
            instance = get_object_or_404(ProductionGlobalParameter, pk=param_id) if param_id else None
            form = ProductionGlobalParameterForm(request.POST, instance=instance)
            if form.is_valid():
                with transaction.atomic(using="default"):
                    form.save()
                    scada_reader.clear_caches()
                messages.success(request, f"Parâmetro Global '{form.cleaned_data['nome']}' salvo com sucesso!")
                return redirect("production:xid_global_config")
            else:
                messages.error(request, f"Erro ao salvar parâmetro global: {form.errors.as_text()}")

        elif action == "save_alarm":
            alarm_id = request.POST.get("alarm_id")
            instance = get_object_or_404(ProductionGlobalAlarm, pk=alarm_id) if alarm_id else None
            form = ProductionGlobalAlarmForm(request.POST, instance=instance)
            if form.is_valid():
                with transaction.atomic(using="default"):
                    form.save()
                    scada_reader.clear_caches()
                messages.success(request, f"Alarme Global '{form.cleaned_data['nome']}' salvo com sucesso!")
                return redirect("production:xid_global_config")
            else:
                messages.error(request, f"Erro ao salvar alarme global: {form.errors.as_text()}")

    global_params = list(
        ProductionGlobalParameter.objects.exclude(
            Q(chave__startswith="calandra_") | Q(nome__istartswith="calandra") |
            Q(chave__startswith="caldeira_") | Q(nome__istartswith="caldeira")
        ).order_by("ordem", "nome")
    )
    global_alarms = list(ProductionGlobalAlarm.objects.all().order_by("ordem", "nome"))
    param_form = ProductionGlobalParameterForm()
    alarm_form = ProductionGlobalAlarmForm()

    return render(request, "production/xid_global_config.html", {
        "global_params": global_params,
        "global_alarms": global_alarms,
        "param_form": param_form,
        "alarm_form": alarm_form,
    })


@superuser_required
def xid_test_api(request):
    """
    Endpoint assíncrono interno para teste e leitura em tempo real de um XID no Scada-LTS.
    Segurança:
    - Exclusivo para superusuários (via @superuser_required).
    - Método POST obrigatório.
    - CSRF verificado.
    - Estritamente somente-leitura.
    """
    if request.method != "POST":
        return JsonResponse(
            {"success": False, "error": "Método não permitido. Utilize POST."},
            status=405
        )

    xid_val = ""
    if request.content_type == "application/json":
        try:
            body_data = json.loads(request.body.decode("utf-8"))
            xid_val = body_data.get("xid", "")
        except Exception:
            return JsonResponse(
                {"success": False, "error": "Payload JSON inválido."},
                status=400
            )
    else:
        xid_val = request.POST.get("xid", "")

    result = XIDTestService.test_single_xid(xid_val)
    return JsonResponse(result)


@superuser_required
def xid_calandra_config(request):
    """
    Configuração e mapeamento dos 21 XIDs da Calandra no Scada-LTS.
    Permite visualizar, editar e testar a comunicação em tempo real de cada variável.
    """
    from .services_calandra import CALANDRA_VARIABLES_CONFIG

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "save_calandra_xids":
            with transaction.atomic(using="default"):
                for var in CALANDRA_VARIABLES_CONFIG:
                    key = var["key"]
                    db_key = f"calandra_{key}"
                    form_xid = request.POST.get(f"xid_{key}", "").strip()

                    obj, _ = ProductionGlobalParameter.objects.get_or_create(
                        chave=db_key,
                        defaults={
                            "nome": f"Calandra - {var['label']}",
                            "unidade": var["unit"],
                            "ordem": var["order"],
                        }
                    )
                    obj.nome = f"Calandra - {var['label']}"
                    obj.xid = form_xid if form_xid else var["tag_name"]
                    obj.unidade = var["unit"]
                    obj.ordem = var["order"]
                    obj.save()

                scada_reader.clear_caches()
            messages.success(request, "Configurações de XIDs da Calandra salvas com sucesso!")
            return redirect("production:xid_calandra_config")

        elif action == "restore_defaults":
            with transaction.atomic(using="default"):
                ProductionGlobalParameter.objects.filter(chave__startswith="calandra_").delete()
                scada_reader.clear_caches()
            messages.success(request, "Configurações da Calandra restauradas para os padrões canônicos!")
            return redirect("production:xid_calandra_config")

    # Carregar estado atual para renderização
    db_map = {
        p.chave: p.xid
        for p in ProductionGlobalParameter.objects.filter(chave__startswith="calandra_")
    }

    groups = [
        {"id": "producao", "title": "1. Produção & Contexto", "badge": "3 Variáveis", "icon": "bi-speedometer2", "vars": []},
        {"id": "cargas", "title": "2. Cargas & Tensões (kg)", "badge": "4 Variáveis", "icon": "bi-arrows-expand", "vars": []},
        {"id": "espessuras", "title": "3. Espessuras (mm)", "badge": "4 Variáveis", "icon": "bi-bounding-box", "vars": []},
        {"id": "temperatura_borracha", "title": "4. Temperatura da Borracha (°C)", "badge": "3 Variáveis", "icon": "bi-fire", "vars": []},
        {"id": "temperaturas_processo", "title": "5. Temperaturas do Equipamento (°C)", "badge": "7 Variáveis", "icon": "bi-thermometer-high", "vars": []},
    ]
    group_dict = {g["id"]: g for g in groups}

    for var in CALANDRA_VARIABLES_CONFIG:
        db_key = f"calandra_{var['key']}"
        current_xid = db_map.get(db_key) or var["tag_name"]
        item = {
            **var,
            "current_xid": current_xid,
            "is_customized": (db_key in db_map and db_map[db_key] != var["tag_name"]),
        }
        if var["group"] in group_dict:
            group_dict[var["group"]]["vars"].append(item)

    return render(request, "production/xid_calandra_config.html", {
        "groups": groups,
        "total_vars": len(CALANDRA_VARIABLES_CONFIG),
    })


@superuser_required
def xid_caldeira_config(request):
    """
    Configuração e mapeamento dos 9 XIDs da Caldeira 2 e Utilidades no Scada-LTS.
    Agrupamento em: Geração de vapor, Linhas de alta, Linhas de baixa, Condensado e Utilidades auxiliares.
    """
    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "save_caldeira_xids":
            with transaction.atomic(using="default"):
                for var in CALDEIRA_VARIABLES_CONFIG:
                    key = var["key"]
                    db_key = f"caldeira_{key}"
                    form_xid = request.POST.get(f"xid_{key}", "").strip()

                    obj, _ = ProductionGlobalParameter.objects.get_or_create(
                        chave=db_key,
                        defaults={
                            "nome": f"Caldeira - {var['label']}",
                            "unidade": var["unit"],
                            "ordem": var["order"],
                        }
                    )
                    obj.nome = f"Caldeira - {var['label']}"
                    obj.xid = form_xid if form_xid else var["tag_name"]
                    obj.unidade = var["unit"]
                    obj.ordem = var["order"]
                    obj.save()

                extra_signals = [
                    (f"prensa_{number:02d}", f"Prensa {number:02d} em vulcanização", xid, 20 + number)
                    for number, xid in PRESS_STATUS_XIDS.items()
                ]
                extra_signals.append(("porta_lenha", "Porta da caldeira aberta", DOOR_XID, 40))
                for key, label, default_xid, order in extra_signals:
                    ProductionGlobalParameter.objects.update_or_create(
                        chave=f"caldeira_{key}",
                        defaults={"nome": label, "xid": request.POST.get(f"xid_{key}", "").strip() or default_xid,
                                  "unidade": "ON/OFF", "ordem": order},
                    )

                scada_reader.clear_caches()
            messages.success(request, "Configurações de XIDs da Caldeira salvas com sucesso!")
            return redirect("production:xid_caldeira_config")

        elif action == "restore_defaults":
            with transaction.atomic(using="default"):
                ProductionGlobalParameter.objects.filter(chave__startswith="caldeira_").delete()
                scada_reader.clear_caches()
            messages.success(request, "Configurações da Caldeira restauradas para os padrões canônicos!")
            return redirect("production:xid_caldeira_config")

    # Carregar estado atual para renderização
    db_map = {
        p.chave: p.xid
        for p in ProductionGlobalParameter.objects.filter(chave__startswith="caldeira_")
    }

    groups = [
        {"id": "geracao_vapor", "title": "1. Geração de Vapor", "badge": "2 Variáveis", "icon": "bi-fire", "vars": []},
        {"id": "linhas_alta", "title": "2. Linhas de Alta", "badge": "2 Variáveis", "icon": "bi-arrow-up-circle-fill", "vars": []},
        {"id": "linhas_baixa", "title": "3. Linhas de Baixa", "badge": "2 Variáveis", "icon": "bi-arrow-down-circle-fill", "vars": []},
        {"id": "condensado", "title": "4. Condensado", "badge": "1 Variável (Totalizador)", "icon": "bi-droplet-fill", "vars": []},
        {"id": "utilidades_auxiliares", "title": "5. Utilidades Auxiliares", "badge": "2 Variáveis", "icon": "bi-gear-wide-connected", "vars": []},
    ]
    group_dict = {g["id"]: g for g in groups}

    for var in CALDEIRA_VARIABLES_CONFIG:
        db_key = f"caldeira_{var['key']}"
        current_xid = db_map.get(db_key) or var["tag_name"]
        item = {
            **var,
            "current_xid": current_xid,
            "is_customized": (db_key in db_map and db_map[db_key] != var["tag_name"]),
        }
        if var["group"] in group_dict:
            group_dict[var["group"]]["vars"].append(item)

    press_group = {"id": "prensas", "title": "6. Prensas em Vulcanização", "badge": "11 sinais · Prensa 03 sem XID",
                   "icon": "bi-building-gear", "vars": []}
    for number, default_xid in PRESS_STATUS_XIDS.items():
        key = f"prensa_{number:02d}"
        current_xid = db_map.get(f"caldeira_{key}") or default_xid
        press_group["vars"].append({"key": key, "friendly_name": f"Prensa {number:02d}",
                                    "description": "ON = em vulcanização; OFF = fora dessa etapa.",
                                    "tag_name": default_xid, "current_xid": current_xid,
                                    "is_customized": current_xid != default_xid, "unit": "ON/OFF"})
    groups.append(press_group)
    door_xid = db_map.get("caldeira_porta_lenha") or DOOR_XID
    groups.append({"id": "porta", "title": "7. Porta de Alimentação", "badge": "1 sinal", "icon": "bi-door-open",
                   "vars": [{"key": "porta_lenha", "friendly_name": "Porta da caldeira",
                             "description": "ON/1 = porta aberta; o evento sugere alimentação, sem comprová-la.",
                             "tag_name": DOOR_XID, "current_xid": door_xid,
                             "is_customized": door_xid != DOOR_XID, "unit": "ON/OFF"}]})

    return render(request, "production/xid_caldeira_config.html", {
        "groups": groups,
        "total_vars": len(CALDEIRA_VARIABLES_CONFIG),
    })


# ==============================================================================
# CENTRAL DE RELATÓRIOS DE MÁQUINAS & HISTÓRICOS (CALANDRA & CALDEIRA 2)
# ==============================================================================

@lider_producao_required
def machine_reports_hub(request):
    """
    Central de Relatórios de Máquinas (/producao/relatorios/).
    Apresenta catálogo amigável de máquinas disponíveis para consulta histórica.
    Zero consultas ao banco SCADA.
    """
    available_reports = [
        {
            "slug": "calandra",
            "name": "Calandra",
            "tag": "CALANDRA",
            "process": "Emborrachamento de Tecido",
            "description": "Histórico das 21 variáveis de processo: produção, cargas de tensão, espessuras e temperaturas da borracha e da máquina.",
            "url_name": "production:calandra_report",
            "icon": "bi-layers-half",
            "is_active": True,
            "badge_label": "Ativo",
            "badge_class": "success",
        },
        {
            "slug": "caldeira",
            "name": "Caldeira 2",
            "tag": "CALDEIRA 2",
            "process": "Geração e Distribuição de Vapor",
            "description": "Histórico das 9 variáveis de vapor, setpoint, linhas de alta e baixa (prensas 1-7 e 8-12), totalizador de condensado, ar comprimido e vácuo.",
            "url_name": "production:caldeira_report",
            "icon": "bi-fire",
            "is_active": True,
            "badge_label": "Ativo",
            "badge_class": "warning",
        },
    ]
    return render(request, "production/machine_reports_hub.html", {
        "reports": available_reports,
    })


@lider_producao_required
def calandra_historical_report(request):
    """
    Relatório Histórico da Calandra (/producao/relatorios/calandra/).
    Filtros rápidos (Hoje, Ontem, 7d, 30d) e personalizado.
    Gráficos organizados por 6 grupos de processo e tabela de estado sincronizado.
    """
    periodo = request.GET.get("periodo", "").strip()
    data_inicio = request.GET.get("data_inicio", "").strip()
    hora_inicio = request.GET.get("hora_inicio", "").strip()
    data_final = request.GET.get("data_final", "").strip()
    hora_final = request.GET.get("hora_final", "").strip()
    page_num = request.GET.get("page", "1").strip()

    start_dt, end_dt, periodo_ativo, error_msg = CalandraHistoricalService.parse_period_filters(
        periodo=periodo if periodo else None,
        data_inicio=data_inicio if data_inicio else None,
        hora_inicio=hora_inicio if hora_inicio else None,
        data_final=data_final if data_final else None,
        hora_final=hora_final if hora_final else None,
    )

    if error_msg:
        messages.warning(request, error_msg)

    # Consulta e sincronização temporal do histórico
    history_data = CalandraHistoricalService.get_synchronized_history(start_dt, end_dt)
    timeline = history_data["timeline"]
    variables_config = CalandraHistoricalService.get_variables_config()

    # Paginação da tabela (50 registros por página)
    paginator = Paginator(timeline, 50)
    try:
        page_obj = paginator.page(page_num)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # Compactar timeline para o cliente (suporte à seleção temporal coordenada e recálculo instantâneo de cards em JS)
    compact_timeline = [
        {
            "ts": item["ts"],
            "datetime_str": item["datetime_str"],
            "passada_val": item.get("passada_val"),
            "passada_label": item.get("passada_label"),
            "is_effective": item.get("is_effective", False),
            "values": item["values"],
        }
        for item in timeline
    ]

    context = {
        "periodo_ativo": periodo_ativo,
        "data_inicio_str": start_dt.strftime("%Y-%m-%d"),
        "hora_inicio_str": start_dt.strftime("%H:%M"),
        "data_final_str": end_dt.strftime("%Y-%m-%d"),
        "hora_final_str": end_dt.strftime("%H:%M"),
        "start_dt_formatted": start_dt.strftime("%d/%m/%Y %H:%M"),
        "end_dt_formatted": end_dt.strftime("%d/%m/%Y %H:%M"),
        "timeline_page": page_obj,
        "total_records": len(timeline),
        "raw_points_count": history_data["raw_points_count"],
        "variables_found_count": history_data["variables_found_count"],
        "variables_missing": history_data["variables_missing"],
        "variables_config": variables_config,
        "total_vars": len(variables_config),
        "chart_datasets_json": json.dumps(history_data["chart_datasets"]),
        "card_stats": history_data.get("card_stats", {}),
        "effective_points_count": history_data.get("effective_points_count", 0),
        "passada_context": history_data.get("passada_context", "Sem dados"),
        "compact_timeline_json": json.dumps(compact_timeline),
    }
    return render(request, "production/calandra_report.html", context)


@lider_producao_required
def calandra_export_excel(request):
    """
    Exportação do Histórico Sincronizado da Calandra em formato Excel (.xlsx).
    """
    periodo = request.GET.get("periodo", "").strip()
    data_inicio = request.GET.get("data_inicio", "").strip()
    hora_inicio = request.GET.get("hora_inicio", "").strip()
    data_final = request.GET.get("data_final", "").strip()
    hora_final = request.GET.get("hora_final", "").strip()

    start_dt, end_dt, _, _ = CalandraHistoricalService.parse_period_filters(
        periodo=periodo if periodo else None,
        data_inicio=data_inicio if data_inicio else None,
        hora_inicio=hora_inicio if hora_inicio else None,
        data_final=data_final if data_final else None,
        hora_final=hora_final if hora_final else None,
    )

    excel_bytes = CalandraHistoricalService.generate_excel_report(start_dt, end_dt)

    filename = f"CALANDRA_HISTORICO_{start_dt.strftime('%Y-%m-%d')}_{end_dt.strftime('%Y-%m-%d')}.xlsx"
    response = HttpResponse(
        excel_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@lider_producao_required
def caldeira_historical_report(request):
    """
    Relatório Histórico da Caldeira 2 (/producao/relatorios/caldeira/).
    Apresenta indicadores de vapor, setpoint, desvios amostra a amostra,
    diferenças entre linhas, totalizador de condensado e utilidades auxiliares.
    """
    periodo = request.GET.get("periodo", "").strip()
    data_inicio = request.GET.get("data_inicio", "").strip()
    hora_inicio = request.GET.get("hora_inicio", "").strip()
    data_final = request.GET.get("data_final", "").strip()
    hora_final = request.GET.get("hora_final", "").strip()
    page_num = request.GET.get("page", "1").strip()

    start_dt, end_dt, periodo_ativo, error_msg = CaldeiraHistoricalService.parse_period_filters(
        periodo=periodo if periodo else None,
        data_inicio=data_inicio if data_inicio else None,
        hora_inicio=hora_inicio if hora_inicio else None,
        data_final=data_final if data_final else None,
        hora_final=hora_final if hora_final else None,
    )

    if error_msg:
        messages.warning(request, error_msg)

    # Resumo limitado em memória; os registros da tabela são consultados por página.
    history_data = CaldeiraFastReader.summary(start_dt, end_dt)
    variables_config = CaldeiraHistoricalService.get_variables_config()

    paginator = Paginator(range(history_data["total_records"]), CaldeiraFastReader.PAGE_SIZE)
    try:
        number = paginator.validate_number(page_num)
    except PageNotAnInteger:
        number = 1
    except EmptyPage:
        number = paginator.num_pages
    rows = CaldeiraFastReader.page(start_dt, end_dt, number, history_data["total_records"])
    page_obj = Page(rows, number, paginator)

    context = {
        "periodo_ativo": periodo_ativo,
        "data_inicio_str": start_dt.strftime("%Y-%m-%d"),
        "hora_inicio_str": start_dt.strftime("%H:%M"),
        "data_final_str": end_dt.strftime("%Y-%m-%d"),
        "hora_final_str": end_dt.strftime("%H:%M"),
        "start_dt_formatted": start_dt.strftime("%d/%m/%Y %H:%M"),
        "end_dt_formatted": end_dt.strftime("%d/%m/%Y %H:%M"),
        "timeline_page": page_obj,
        "total_records": history_data["total_records"],
        "raw_points_count": history_data["raw_points_count"],
        "variables_found_count": history_data["variables_found_count"],
        "variables_missing": history_data["variables_missing"],
        "variables_config": variables_config,
        "chart_datasets_json": json.dumps(history_data["chart_datasets"]),
        "stats": history_data.get("stats", {}),
        "card_stats": history_data.get("card_stats", {}),
        "condensate_stats": history_data.get("condensate_stats", {}),
        "has_data": history_data.get("has_data", False),
    }
    return render(request, "production/caldeira_report.html", context)


def _caldeira_performance_filters(request):
    """Mantém os filtros e o instante da análise iguais na tela e no Excel."""
    window = request.GET.get("janela", "24h")
    if window not in ("24h", "7d", "personalizado"):
        window = "24h"
    now_local = timezone.localtime()
    end_dt = now_local.replace(minute=(now_local.minute // 5) * 5, second=0, microsecond=0)
    if window == "personalizado":
        try:
            start_value = datetime.fromisoformat(request.GET.get("inicio", ""))
            end_value = datetime.fromisoformat(request.GET.get("fim", ""))
            if (timezone.is_aware(start_value) or timezone.is_aware(end_value)
                    or start_value.second or start_value.microsecond
                    or end_value.second or end_value.microsecond):
                raise ValueError
            start_dt = timezone.make_aware(start_value)
            end_dt = timezone.make_aware(end_value)
            if not start_dt < end_dt <= now_local or end_dt - start_dt > timedelta(days=CaldeiraInsightsService.MAX_DAYS):
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Informe início e fim válidos: o fim deve ser posterior ao início, não pode estar no futuro e o intervalo máximo é de 31 dias.") from exc
    else:
        try:
            snapshot_ms = int(request.GET.get("fim_ms", ""))
            snapshot = timezone.localtime(datetime.fromtimestamp(snapshot_ms / 1000, tz=dt_timezone.utc))
            if not end_dt - timedelta(hours=2) <= snapshot <= end_dt or snapshot.second or snapshot.minute % 5:
                raise ValueError
            end_dt = snapshot.replace(microsecond=0)
        except (ValueError, OverflowError):
            pass
        start_dt = end_dt - (timedelta(days=7) if window == "7d" else timedelta(hours=24))
    try:
        drop_bar = float(request.GET.get("queda_bar", "1.0").replace(",", "."))
        if not 0.2 <= drop_bar <= 3.0:
            raise ValueError
    except ValueError:
        drop_bar = 1.0
    try:
        min_minutes = int(request.GET.get("duracao_min", "2"))
        if not 1 <= min_minutes <= 15:
            raise ValueError
    except ValueError:
        min_minutes = 2
    settings_obj = CaldeiraAnalysisSettings.objects.filter(pk=1).first() or CaldeiraAnalysisSettings(pk=1)
    floor = float(settings_obj.operating_pressure_floor_bar) if settings_obj.operating_pressure_floor_bar is not None else None
    return window, start_dt, end_dt, drop_bar, min_minutes, settings_obj, floor


def _caldeira_performance_query(window, start_dt, end_dt, drop_bar, min_minutes):
    params = {"janela": window, "queda_bar": drop_bar, "duracao_min": min_minutes}
    if window == "personalizado":
        params.update({"inicio": timezone.localtime(start_dt).strftime("%Y-%m-%dT%H:%M"),
                       "fim": timezone.localtime(end_dt).strftime("%Y-%m-%dT%H:%M")})
    else:
        params["fim_ms"] = int(end_dt.timestamp() * 1000)
    return urlencode(params)


@lider_producao_required
def caldeira_performance(request):
    """Mostra o resultado pronto sem bloquear a requisição no histórico SCADA."""
    try:
        window, start_dt, end_dt, drop_bar, min_minutes, settings_obj, floor = _caldeira_performance_filters(request)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("production:caldeira_performance")
    key = caldeira_insights_job_key(start_dt, end_dt, drop_bar, min_minutes, floor, settings_obj.updated_at)
    analysis = read_caldeira_insights_result(key)
    if analysis is None:
        ensure_caldeira_insights_job(key, start_dt, end_dt, drop_bar, min_minutes, floor,
                                    retry=request.GET.get("retry") == "1")
        state = read_caldeira_insights_state(key) or {}
        query = _caldeira_performance_query(window, start_dt, end_dt, drop_bar, min_minutes)
        refresh_url = f"{reverse('production:caldeira_performance')}?{query}"
        response = render(request, "production/caldeira_performance_loading.html", {
            "state": state, "refresh_url": refresh_url, "retry_url": f"{refresh_url}&retry=1",
            "window": window, "start_dt": start_dt, "end_dt": end_dt,
            "start_input": timezone.localtime(start_dt).strftime("%Y-%m-%dT%H:%M"),
            "end_input": timezone.localtime(end_dt).strftime("%Y-%m-%dT%H:%M"),
            "drop_bar": drop_bar, "min_minutes": min_minutes,
        })
        response["Cache-Control"] = "no-store"
        return response
    if analysis["above_pmta"]:
        maintenance_advice = ("Leitura acima da PMTA da placa: confirme o instrumento e acione imediatamente "
                              "o responsável técnico conforme o procedimento da instalação.")
        maintenance_level = "danger"
    elif floor is not None and analysis["below_floor_count"]:
        maintenance_advice = ("Houve leituras abaixo da referência operacional cadastrada. Solicite avaliação "
                              "técnica antecipada; os dados não identificam a causa nem definem o serviço necessário.")
        maintenance_level = "warning"
    elif not analysis["pressure_samples"]:
        maintenance_advice = ("Sem leituras de pressão suficientes para avaliar a condição. Confirme a comunicação "
                              "do supervisório e mantenha o plano de inspeção documentado.")
        maintenance_level = "secondary"
    elif analysis["drop_total"]:
        maintenance_advice = ("Há recuos pelo critério de triagem escolhido. Compare com prensas e abertura da porta "
                              "e peça revisão técnica se o padrão se repetir. Sem faixa operacional aprovada, "
                              "a telemetria não define quando antecipar a manutenção.")
        maintenance_level = "warning"
    else:
        maintenance_advice = ("Nenhum recuo foi identificado pelo critério escolhido nesta janela. "
                              "Mantenha as verificações e inspeções previstas no plano documentado.")
        maintenance_level = "success"
    due = settings_obj.next_inspection_due
    if due is None:
        inspection_status = "Data da próxima inspeção não cadastrada. Consulte o último relatório NR-13."
    elif due < end_dt.date():
        inspection_status = "A data cadastrada para a inspeção passou. Confira o relatório e acione o responsável técnico."
    elif due <= end_dt.date() + timedelta(days=30):
        inspection_status = "A data cadastrada para a inspeção está próxima. Planeje com o responsável técnico."
    else:
        inspection_status = "Próxima inspeção registrada; mantenha o plano e os registros atualizados."
    return render(request, "production/caldeira_performance.html", {
        "analysis": analysis,
        "analysis_json": json.dumps({"hours": analysis["hours"]}),
        "export_query": _caldeira_performance_query(window, start_dt, end_dt, drop_bar, min_minutes),
        "start_input": timezone.localtime(start_dt).strftime("%Y-%m-%dT%H:%M"),
        "end_input": timezone.localtime(end_dt).strftime("%Y-%m-%dT%H:%M"),
        "window": window,
        "settings_obj": settings_obj,
        "settings_form": CaldeiraAnalysisSettingsForm(instance=settings_obj),
        "inspection_status": inspection_status,
        "maintenance_advice": maintenance_advice,
        "maintenance_level": maintenance_level,
    })


@lider_producao_required
def caldeira_performance_excel(request):
    try:
        window, start_dt, end_dt, drop_bar, min_minutes, settings_obj, floor = _caldeira_performance_filters(request)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("production:caldeira_performance")
    key = caldeira_insights_job_key(start_dt, end_dt, drop_bar, min_minutes, floor, settings_obj.updated_at)
    analysis = read_caldeira_insights_result(key)
    if analysis is None:
        ensure_caldeira_insights_job(key, start_dt, end_dt, drop_bar, min_minutes, floor)
        query = _caldeira_performance_query(window, start_dt, end_dt, drop_bar, min_minutes)
        return redirect(f"{reverse('production:caldeira_performance')}?{query}")
    response = FileResponse(build_insights_excel(analysis),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="caldeira_desempenho_{end_dt:%Y%m%d_%H%M}.xlsx"'
    return response


@superuser_required
def caldeira_performance_settings(request):
    if request.method != "POST":
        return redirect("production:caldeira_performance")
    settings_obj = CaldeiraAnalysisSettings.objects.filter(pk=1).first() or CaldeiraAnalysisSettings(pk=1)
    form = CaldeiraAnalysisSettingsForm(request.POST, instance=settings_obj)
    if form.is_valid():
        form.save()
        messages.success(request, "Datas e referência operacional salvas.")
    else:
        details = " ".join(str(error) for errors in form.errors.values() for error in errors)
        messages.error(request, f"Revise os campos de manutenção e inspeção. {details}")
    return redirect("production:caldeira_performance")


@lider_producao_required
def caldeira_export_excel(request):
    """
    Exportação do Histórico Sincronizado e Resumo Gerencial da Caldeira 2 em formato Excel (.xlsx).
    """
    periodo = request.GET.get("periodo", "").strip()
    data_inicio = request.GET.get("data_inicio", "").strip()
    hora_inicio = request.GET.get("hora_inicio", "").strip()
    data_final = request.GET.get("data_final", "").strip()
    hora_final = request.GET.get("hora_final", "").strip()

    start_dt, end_dt, _, _ = CaldeiraHistoricalService.parse_period_filters(
        periodo=periodo if periodo else None,
        data_inicio=data_inicio if data_inicio else None,
        hora_inicio=hora_inicio if hora_inicio else None,
        data_final=data_final if data_final else None,
        hora_final=hora_final if hora_final else None,
    )

    if end_dt - start_dt > timedelta(days=1):
        job_id = start_caldeira_export_job(request.user, start_dt, end_dt)
        return redirect("production:caldeira_export_status", job_id=job_id)

    user_name = request.user.get_full_name() or request.user.username or "Sistema"
    excel_file = CaldeiraFastReader.excel_file(start_dt, end_dt, generated_by=user_name)

    filename = f"relatorio_caldeira_{start_dt.strftime('%Y%m%d_%H%M')}_ate_{end_dt.strftime('%Y%m%d_%H%M')}.xlsx"
    response = FileResponse(
        excel_file,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@lider_producao_required
def caldeira_export_status(request, job_id):
    job = read_caldeira_export_job(job_id)
    if job is None or job.get("user_id") != request.user.pk:
        raise Http404("Exportação não encontrada.")
    path = caldeira_export_output_path(job_id)
    ready = job.get("status") == "ready" and path.is_file()
    if job.get("status") in ("queued", "running"):
        created = timezone.datetime.fromisoformat(job["created_at"])
        if timezone.now() - created > timedelta(hours=2):
            job = {**job, "status": "failed"}
    if job.get("status") == "ready" and not ready:
        job = {**job, "status": "failed"}
    if ready and request.GET.get("download") == "1":
        start_dt = timezone.datetime.fromisoformat(job["start"])
        end_dt = timezone.datetime.fromisoformat(job["end"])
        filename = f"relatorio_caldeira_{start_dt:%Y%m%d_%H%M}_ate_{end_dt:%Y%m%d_%H%M}.xlsx"
        return FileResponse(path.open("rb"), as_attachment=True, filename=filename,
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return render(request, "production/caldeira_export_status.html", {
        "job": job, "ready": ready, "job_id": job_id,
    })







