from django.shortcuts import render
from .decorators import lider_producao_required
from .services import ProductionStateService

@lider_producao_required
def production_dashboard(request):
    """
    Renders the production dashboard for the production leadership.
    """
    state = ProductionStateService.get_dashboard_state()
    return render(request, "production/dashboard.html", state)

