import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.db.models import Q
from maintenance.models import Machine
from .decorators import lider_producao_required, lider_ou_pcp_required, superuser_required
from .services import ProductionStateService, PCPCalculationService, BladderTrackingService, scada_reader
from .services_calandra import CalandraHistoricalService
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
            Q(chave__startswith="calandra_") | Q(nome__istartswith="calandra")
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
    Configuração e mapeamento dos 20 XIDs da Calandra no Scada-LTS.
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
        {"id": "temperaturas_processo", "title": "5. Temperaturas do Equipamento (°C)", "badge": "6 Variáveis", "icon": "bi-thermometer-high", "vars": []},
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


# ==============================================================================
# CENTRAL DE RELATÓRIOS DE MÁQUINAS & HISTÓRICO DA CALANDRA
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
            "description": "Histórico das 20 variáveis de processo: produção, cargas de tensão, espessuras e temperaturas da borracha e da máquina.",
            "url_name": "production:calandra_report",
            "icon": "bi-layers-half",
            "is_active": True,
            "badge_label": "Ativo",
            "badge_class": "success",
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
    Gráficos organizados por 5 grupos de processo e tabela de estado sincronizado.
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






