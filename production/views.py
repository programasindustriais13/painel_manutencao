from django.shortcuts import render
from .decorators import lider_producao_required

@lider_producao_required
def production_dashboard(request):
    """
    Renders the production dashboard for the production leadership.
    """
    return render(request, "production/dashboard.html")
