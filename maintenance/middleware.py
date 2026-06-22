"""
Middleware de Expiração de Sessão por Perfil
============================================
Garante que o usuário do grupo 'Visualizador' ou com username 'tv'
tenha sessão perpétua (10 anos), enquanto todos os demais perfis
(técnicos, operadores) seguem o SESSION_COOKIE_AGE padrão de 4 horas.

Posicionamento no MIDDLEWARE: APÓS AuthenticationMiddleware.
"""


class SessionExpiryByProfileMiddleware:
    """Intercepta cada request e ajusta a expiração da sessão
    de acordo com o perfil do usuário autenticado.

    - Visualizador / username 'tv': sessão perpétua (315.360.000 segundos = ~10 anos)
    - Demais perfis: SESSION_COOKIE_AGE padrão (definido em settings.py)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Verifica apenas se o usuário está autenticado
        if hasattr(request, 'user') and request.user.is_authenticated:
            # Usa flag na sessão para evitar consultar o grupo a cada request
            if not request.session.get('_session_expiry_checked'):
                user = request.user
                is_tv_viewer = (
                    user.username == 'tv'
                    or user.groups.filter(name='Visualizador').exists()
                )
                if is_tv_viewer:
                    # Sessão perpétua para o painel da TV (10 anos)
                    request.session.set_expiry(315360000)
                # Marca como já verificado para não repetir em cada request
                request.session['_session_expiry_checked'] = True

        response = self.get_response(request)
        return response
