from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages

def lider_producao_required(view_func):
    """
    Decorator that requires the user to be a superuser, staff, or belong to
    the 'Liderança de Produção' group. Redirects other users to their default home_redirect.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if user.is_superuser or user.is_staff or user.groups.filter(name="Liderança de Produção").exists():
            return view_func(request, *args, **kwargs)
        
        messages.error(
            request,
            "Acesso negado. Esta área é restrita para a Liderança de Produção."
        )
        return redirect("home_redirect")
    return wrapper


def lider_ou_pcp_required(view_func):
    """
    Decorator requiring the user to be a superuser, staff, belong to 'Liderança de Produção' group,
    or possess the 'production.add_productiontarget' permission.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if (
            user.is_superuser
            or user.is_staff
            or user.groups.filter(name="Liderança de Produção").exists()
            or user.has_perm("production.add_productiontarget")
        ):
            return view_func(request, *args, **kwargs)

        messages.error(
            request,
            "Acesso negado. Você não possui permissão para gerenciar metas de produção."
        )
        return redirect("home_redirect")
    return wrapper

