from django.shortcuts import render
from .decorators import lider_producao_required
from .services import ProductionStateService


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
    data_inicio = request.GET.get("data_inicio", "").strip()
    data_final = request.GET.get("data_final", "").strip()
    periodo = request.GET.get("periodo", "").strip()

    detail_state = ProductionStateService.get_machine_detail(
        config_id=pk,
        data_inicio_str=data_inicio if data_inicio else None,
        data_final_str=data_final if data_final else None,
        periodo=periodo if periodo else None
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

