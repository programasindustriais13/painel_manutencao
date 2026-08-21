from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages

def lider_producao_required(view_func):
    """
    Decorator that requires the user to be a superuser, staff, or belong to
    'Liderança de Produção', 'Operadores', 'Operador', or 'PCP' groups.
    Redirects unauthorized users to home_redirect.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if (
            user.is_superuser
            or user.is_staff
            or user.groups.filter(name__in=["Liderança de Produção", "Operadores", "Operador", "PCP"]).exists()
        ):
            return view_func(request, *args, **kwargs)
        
        messages.error(
            request,
            "Acesso negado. Esta área é restrita para a Produção e Operadores."
        )
        return redirect("home_redirect")
    return wrapper


def lider_ou_pcp_required(view_func):
    """
    Decorator requiring the user to be a superuser, staff, belong to 'Liderança de Produção',
    'Operadores', 'Operador', 'PCP' groups, or possess production target permissions.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if (
            user.is_superuser
            or user.is_staff
            or user.groups.filter(name__in=["Liderança de Produção", "Operadores", "Operador", "PCP"]).exists()
            or user.has_perm("production.add_productiontarget")
            or user.has_perm("production.view_productiontarget")
        ):
            return view_func(request, *args, **kwargs)

        messages.error(
            request,
            "Acesso negado. Você não possui permissão para gerenciar metas de produção."
        )
        return redirect("home_redirect")
    return wrapper


def superuser_required(view_func):
    """
    Decorator de segurança máxima que restringe o acesso estritamente a superusuários
    (request.user.is_superuser is True).
    
    Regras:
    - is_staff=True sozinho NÃO concede acesso.
    - Grupos (Operadores, Líderes de Produção, Técnicos, PCP) NÃO concedem acesso.
    - Se a requisição for assíncrona (AJAX/API), retorna JSON HTTP 403.
    - Se for página HTML comum, redireciona para o dashboard da produção com mensagem de erro.
    - Se o usuário não estiver autenticado, o @login_required redireciona para o login padrão.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if user.is_superuser:
            return view_func(request, *args, **kwargs)

        is_ajax_or_api = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.headers.get("Accept", "").startswith("application/json")
            or request.path.startswith("/producao/configuracao-scada/api/")
            or request.content_type == "application/json"
        )

        if is_ajax_or_api:
            from django.http import JsonResponse
            return JsonResponse(
                {"success": False, "error": "Acesso negado. Esta operação exige privilégios de superusuário."},
                status=403
            )

        messages.error(
            request,
            "Acesso negado. A Central de Configuração SCADA é restrita exclusivamente a administradores (superusuários)."
        )
        return redirect("production:dashboard")
    return wrapper


