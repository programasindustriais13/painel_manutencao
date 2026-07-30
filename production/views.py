from django.shortcuts import render
from .decorators import lider_producao_required
from .services import ProductionStateService


@lider_producao_required
def production_dashboard(request):
    """
    Renderiza o dashboard geral do módulo de produção.
    """
    state = ProductionStateService.get_dashboard_state()
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
