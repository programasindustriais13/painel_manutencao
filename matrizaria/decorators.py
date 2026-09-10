from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages


def _user_can_access_matrizaria(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(
        name__in=[
            "Operadores",
            "Operador",
            "Liderança de Produção",
            "Operadores Vulcanização",
            "Matrizaria",
        ]
    ).exists()


def _user_can_request_matrizaria(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(
        name__in=[
            "Operadores",
            "Operador",
            "Liderança de Produção",
            "Operadores Vulcanização",
        ]
    ).exists()


def _user_can_execute_matrizaria(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(
        name__in=[
            "Operadores",
            "Operador",
            "Matrizaria",
        ]
    ).exists()


def _user_can_inspect_matrizaria(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(
        name__in=[
            "Operadores",
            "Operador",
            "Liderança de Produção",
            "Operadores Vulcanização",
        ]
    ).exists()


def _user_can_cancel_matrizaria(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(
        name__in=[
            "Operadores",
            "Operador",
            "Liderança de Produção",
        ]
    ).exists()


def _user_can_view_matrizaria_reports(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(
        name__in=[
            "Operadores",
            "Operador",
            "Liderança de Produção",
        ]
    ).exists()


def _user_can_view_matrizaria_tv(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if user.username in ["tv_matrizaria", "tv"]:
        return True
    return user.groups.filter(
        name__in=[
            "Operadores",
            "Operador",
            "Liderança de Produção",
            "Operadores Vulcanização",
            "Matrizaria",
            "Visualizador Matrizaria",
            "Visualizador",
        ]
    ).exists()


# Aliases para compatibilidade e concisão
_user_can_solicitar = _user_can_request_matrizaria
_user_can_executar = _user_can_execute_matrizaria
_user_can_conferir = _user_can_inspect_matrizaria
_user_can_cancelar = _user_can_cancel_matrizaria
_user_can_relatorios = _user_can_view_matrizaria_reports
_user_can_tv = _user_can_view_matrizaria_tv


# --- DECORATORS ---

def matrizaria_access_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_access_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso restrito. Você não possui permissão para acessar o módulo de Matrizaria.")
        return redirect("home_redirect")
    return wrapper


def matrizaria_solicitar_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_request_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. Apenas Líderes de Produção, Operadores de Vulcanização e Administradores podem abrir solicitações.")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_executar_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_execute_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. Apenas colaboradores da oficina de Matrizaria ou Administradores podem executar serviços.")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_conferir_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_inspect_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. A conferência de serviços é restrita à Liderança de Produção, Operadores de Vulcanização e Administradores.")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_cancelar_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_cancel_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. O cancelamento de serviços é restrito a Líderes de Produção e Administradores.")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_relatorios_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_view_matrizaria_reports(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. A visualização e exportação de relatórios de auditoria é restrita a Líderes e Administradores.")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_tv_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_view_matrizaria_tv(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado ao Painel TV da Matrizaria.")
        return redirect("home_redirect")
    return wrapper
