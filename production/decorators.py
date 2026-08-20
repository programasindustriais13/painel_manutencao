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

