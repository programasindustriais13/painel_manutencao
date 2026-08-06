from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from .decorators import lider_producao_required, lider_ou_pcp_required
from .services import ProductionStateService
from .models import ProductionTarget, ProductionMatrixCatalog, ProductionShift
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
    Área de gestão de metas da produção (/producao/metas/).
    """
    targets_qs = ProductionTarget.objects.select_related(
        "shift", "matrix_catalog", "predicted_machine", "predicted_cavity", "created_by"
    ).order_by("-date", "shift__ordem_exibicao")

    date_filter = request.GET.get("date", "").strip()
    status_filter = request.GET.get("status", "").strip()
    shift_filter = request.GET.get("shift_id", "").strip()

    if date_filter:
        targets_qs = targets_qs.filter(date=date_filter)
    if status_filter:
        targets_qs = targets_qs.filter(status=status_filter)
    if shift_filter and shift_filter.isdigit():
        targets_qs = targets_qs.filter(shift_id=int(shift_filter))

    form = ProductionTargetForm(initial={"date": timezone.now().date(), "status": "ATIVO"})

    return render(request, "production/target_list.html", {
        "targets": targets_qs,
        "shifts": ProductionShift.objects.filter(ativo=True).order_by("ordem_exibicao"),
        "form": form,
        "filters": {
            "date": date_filter,
            "status": status_filter,
            "shift_id": shift_filter,
        }
    })


@lider_ou_pcp_required
def target_create(request):
    """
    Criação de meta de produção.
    """
    if request.method == "POST":
        form = ProductionTargetForm(request.POST)
        if form.is_valid():
            target = form.save(commit=False)
            target.created_by = request.user
            target.save()
            messages.success(request, "Meta de produção cadastrada com sucesso!")
            return redirect("production:target_list")
        else:
            messages.error(request, "Erro ao cadastrar meta. Verifique os dados informados.")
            targets_qs = ProductionTarget.objects.select_related("shift", "matrix_catalog", "created_by").order_by("-date")
            return render(request, "production/target_list.html", {
                "targets": targets_qs,
                "shifts": ProductionShift.objects.filter(ativo=True).order_by("ordem_exibicao"),
                "form": form,
                "filters": {},
            })
    return redirect("production:target_list")


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


