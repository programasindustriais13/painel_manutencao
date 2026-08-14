from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from .decorators import lider_producao_required, lider_ou_pcp_required
from .services import ProductionStateService, PCPCalculationService
from .models import ProductionTarget, ProductionMatrixCatalog, ProductionShift, ProductionPCPPlan
from .forms import ProductionTargetForm, ProductionMatrixCatalogForm


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

@lider_ou_pcp_required
def pcp_plan_list(request):
    """
    Lista de Programações PCP (/production/pcp/).
    """
    plans_qs = ProductionPCPPlan.objects.select_related("matriz", "bladder", "created_by").prefetch_related("shift_targets__shift").order_by("-created_at")

    matriz_filter = request.GET.get("matriz_id", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if matriz_filter and matriz_filter.isdigit():
        plans_qs = plans_qs.filter(matriz_id=int(matriz_filter))
    if status_filter:
        plans_qs = plans_qs.filter(status=status_filter)

    max_cavities = PCPCalculationService.get_available_cavities_limit()
    matrices = ProductionMatrixCatalog.objects.filter(ativo=True).order_by("nome_exibicao", "codigo_scada")

    return render(request, "production/pcp_plan_list.html", {
        "plans": plans_qs,
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
        # Initial datetime: agora formatado localmente
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
def pcp_plan_detail(request, pk):
    """
    Detalhes e detalhamento por turno de uma Programação PCP (#id).
    """
    plan = get_object_or_404(ProductionPCPPlan.objects.select_related("matriz", "bladder", "created_by"), pk=pk)
    shift_targets = plan.shift_targets.select_related("shift", "target_legado").order_by("date", "shift__ordem_exibicao")

    return render(request, "production/pcp_plan_detail.html", {
        "plan": plan,
        "shift_targets": shift_targets,
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



