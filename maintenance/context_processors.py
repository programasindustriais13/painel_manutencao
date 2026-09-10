from .views import (
    _user_can_access_maintenance,
    _user_can_access_production,
    _user_can_access_matrizaria,
    _user_has_dual_access,
    _user_is_operador,
    _user_is_lider_ou_operador,
    _user_can_create_os,
)


def module_access_context(request):
    """
    Context processor global para disponibilizar informações de permissão
    e alternância de módulos (Manutenção, Produção e Matrizaria) para os templates.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {
            'can_access_maintenance': False,
            'can_access_production': False,
            'can_access_matrizaria': False,
            'has_dual_access': False,
            'is_operador': False,
            'is_lider_ou_operador': False,
            'can_create_os': False,
        }

    return {
        'can_access_maintenance': _user_can_access_maintenance(user),
        'can_access_production': _user_can_access_production(user),
        'can_access_matrizaria': _user_can_access_matrizaria(user),
        'has_dual_access': _user_has_dual_access(user),
        'is_operador': _user_is_operador(user),
        'is_lider_ou_operador': _user_is_lider_ou_operador(user),
        'can_create_os': _user_can_create_os(user),
    }

