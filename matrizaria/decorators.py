from functools import wraps
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied


def _user_can_dashboard_matrizaria(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active
                and user.has_perm("matrizaria.view_dashboard_matrizaria"))


def matrizaria_dashboard_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _user_can_dashboard_matrizaria(request.user):
            raise PermissionDenied("Acesso restrito à liderança autorizada da Matrizaria.")
        return view_func(request, *args, **kwargs)
    return wrapper


def matrizaria_detalhe_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_dashboard_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        return matrizaria_access_required(view_func)(request, *args, **kwargs)
    return wrapper


def matrizaria_landing_name(user):
    """Entrada do módulo sem conceder acesso operacional a leitores gerenciais."""
    if _user_can_dashboard_matrizaria(user):
        return "matrizaria:dashboard"
    if _user_is_exclusively_operador_vulcanizacao(user):
        return "matrizaria:minhas_solicitacoes"
    return "matrizaria:kanban"


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
            "Matrizaria",
            "Visualizador Matrizaria",
            "Visualizador",
        ]
    ).exists()


def _user_is_operador_vulcanizacao(user) -> bool:
    """Retorna True se o usuário pertencer ao grupo 'Operadores Vulcanização'."""
    if not user or not user.is_authenticated:
        return False
    return user.groups.filter(name="Operadores Vulcanização").exists()


def _user_is_exclusively_operador_vulcanizacao(user) -> bool:
    """
    Retorna True se o usuário for operador de vulcanização de chão de fábrica
    SEM papéis acumulados de liderança, oficina ou administração geral.
    """
    if not _user_is_operador_vulcanizacao(user):
        return False
    if user.is_superuser or user.is_staff:
        return False
    return not user.groups.exclude(name="Operadores Vulcanização").filter(
        name__in=[
            "Matrizaria",
            "Liderança de Produção",
            "Operadores",
            "Operador",
            "Visualizador Matrizaria",
            "Visualizador",
            "Gestores",
            "Líderes",
            "Tecnicos_Lideres",
            "Planejamento",
        ]
    ).exists()


def _user_can_access_matrizaria_kanban(user) -> bool:
    """
    Retorna True se o usuário puder visualizar o Kanban geral da oficina de Matrizaria.
    Operadores exclusivos de vulcanização NÃO possuem acesso ao Kanban geral.
    """
    if not _user_can_access_matrizaria(user):
        return False
    if _user_is_exclusively_operador_vulcanizacao(user):
        return False
    return True


# Aliases para compatibilidade e concisão
_user_can_solicitar = _user_can_request_matrizaria
_user_can_executar = _user_can_execute_matrizaria
_user_can_conferir = _user_can_inspect_matrizaria
_user_can_cancelar = _user_can_cancel_matrizaria
_user_can_relatorios = _user_can_view_matrizaria_reports
_user_can_tv = _user_can_view_matrizaria_tv
_user_can_kanban = _user_can_access_matrizaria_kanban


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
        if _user_is_exclusively_operador_vulcanizacao(request.user):
            return redirect("matrizaria:minhas_solicitacoes")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_executar_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_execute_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. Apenas colaboradores da oficina de Matrizaria ou Administradores podem executar serviços.")
        if _user_is_exclusively_operador_vulcanizacao(request.user):
            return redirect("matrizaria:minhas_solicitacoes")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_kanban_required(view_func):
    """
    Decorator para o Kanban geral da Matrizaria.
    Redireciona operadores de vulcanização exclusivos para sua interface dedicada
    de acompanhamento ('minhas_solicitacoes').
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _user_can_access_matrizaria(request.user):
            messages.error(request, "Acesso restrito. Você não possui permissão para acessar o módulo de Matrizaria.")
            return redirect("home_redirect")
        if _user_is_exclusively_operador_vulcanizacao(request.user):
            messages.info(
                request,
                "O Kanban geral é restrito à oficina. Você foi redirecionado para suas solicitações."
            )
            return redirect("matrizaria:minhas_solicitacoes")
        return view_func(request, *args, **kwargs)
    return wrapper


def matrizaria_conferir_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_inspect_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. A conferência de serviços é restrita à Liderança de Produção e Administradores.")
        if _user_is_exclusively_operador_vulcanizacao(request.user):
            return redirect("matrizaria:minhas_solicitacoes")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_cancelar_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_cancel_matrizaria(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. O cancelamento de serviços é restrito a Líderes de Produção e Administradores.")
        if _user_is_exclusively_operador_vulcanizacao(request.user):
            return redirect("matrizaria:minhas_solicitacoes")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_relatorios_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_view_matrizaria_reports(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado. A visualização e exportação de relatórios de auditoria é restrita a Líderes e Administradores.")
        if _user_is_exclusively_operador_vulcanizacao(request.user):
            return redirect("matrizaria:minhas_solicitacoes")
        return redirect("matrizaria:kanban")
    return wrapper


def matrizaria_tv_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if _user_can_view_matrizaria_tv(request.user):
            return view_func(request, *args, **kwargs)
        messages.error(request, "Acesso negado ao Painel TV da Matrizaria.")
        if _user_is_exclusively_operador_vulcanizacao(request.user):
            return redirect("matrizaria:minhas_solicitacoes")
        return redirect("home_redirect")
    return wrapper
