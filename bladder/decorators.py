from functools import wraps
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect


def user_is_lider_bladder(user):
    """
    Retorna True estritamente para Superusuários ou membros do grupo 'Liderança Bladder'.
    Usuários staff genéricos NÃO possuem acesso apenas por serem staff.
    Usuários de outros módulos (Manutenção, Produção, Matrizaria) NÃO possuem acesso sem pertencer à Liderança Bladder.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name='Liderança Bladder').exists()


def user_is_apoio_bladder(user):
    """
    Retorna True se o usuário for um colaborador de apoio operacional cadastrado e ativo.
    Não exige turma fixa e não altera a escala 12x36 titular.
    """
    if not user or not user.is_authenticated:
        return False
    try:
        from .models import FuncionarioApoioBladder
        return FuncionarioApoioBladder.objects.filter(usuario=user, ativo=True).exists()
    except Exception:
        return False


def user_is_operador_regular_bladder(user):
    """
    Retorna True se o usuário pertencer ao grupo 'Operadores Bladder' E possuir
    um PerfilOperacionalBladder ativo vinculado a uma turma válida ('TURMA_A' ou 'TURMA_B').
    Se o perfil estiver inativo ou ausente, a operação normal é negada.
    """
    if not user or not user.is_authenticated:
        return False
    if not user.groups.filter(name='Operadores Bladder').exists():
        return False

    perfil = getattr(user, 'perfil_operacional_bladder', None)
    if perfil is None:
        try:
            from .models import PerfilOperacionalBladder
            perfil = PerfilOperacionalBladder.objects.filter(usuario=user).first()
        except Exception:
            return False

    if perfil and perfil.ativo and perfil.turma in ['TURMA_A', 'TURMA_B']:
        return True
    return False


def user_is_operador_bladder(user):
    """
    Retorna True se o usuário possuir qualquer permissão de operação no Setor de Bladder:
    - Superusuário (exceção administrativa);
    - Líder Bladder;
    - Operador Regular ativo (com turma A ou B);
    - Funcionário de Apoio operacional ativo.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user_is_lider_bladder(user):
        return True
    if user_is_operador_regular_bladder(user):
        return True
    if user_is_apoio_bladder(user):
        return True
    return False


def lider_bladder_required(view_func):
    """
    Decorator que restringe o acesso estritamente à Liderança do Setor de Bladder.
    Operadores de chão de fábrica são redirecionados com segurança para /bladder/operador/.
    Usuários externos/não autorizados são redirecionados para o portal central.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        if not user_is_lider_bladder(request.user):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Acesso restrito à Liderança do Setor de Bladder.'}, status=403)

            messages.error(request, "Acesso restrito à Liderança do Setor de Bladder.")
            if user_is_operador_bladder(request.user):
                return redirect('bladder:operador')
            return redirect('portal_select')

        return view_func(request, *args, **kwargs)

    return _wrapped_view


def operador_ou_lider_bladder_required(view_func):
    """
    Decorator que autoriza operadores ativos, funcionários de apoio ativos e líderes do Setor de Bladder.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        if not user_is_operador_bladder(request.user):
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Acesso restrito aos colaboradores autorizados do Setor de Bladder.'}, status=403)

            messages.error(request, "Acesso restrito aos colaboradores autorizados do Setor de Bladder.")
            return redirect('portal_select')

        return view_func(request, *args, **kwargs)

    return _wrapped_view
