import time
from django.conf import settings
from django.contrib.auth import logout
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect


def is_dedicated_tv_account(user) -> bool:
    """
    Identifica contas exclusivas de exibição contínua em TV.
    Regra estrita:
    - Usuário ativo;
    - NÃO é superuser nem staff;
    - NÃO possui grupos operacionais (Tecnicos, Operadores, Matrizaria, etc.);
    - Username 'tv' ou 'tv_matrizaria', ou grupo 'Visualizador' / 'Visualizador Matrizaria'.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_staff:
        return False

    # Grupos com poderes operacionais que invalidam a isenção de TV
    operational_groups = [
        "Tecnicos",
        "Tecnicos_Lideres",
        "Operador",
        "Operadores",
        "Operadores Vulcanização",
        "Liderança de Produção",
        "Matrizaria",
    ]
    if user.groups.filter(name__in=operational_groups).exists():
        return False

    is_tv_name = user.username in ["tv", "tv_matrizaria"]
    is_tv_group = user.groups.filter(name__in=["Visualizador", "Visualizador Matrizaria"]).exists()
    return is_tv_name or is_tv_group


class SessionExpiryByProfileMiddleware:
    """
    Middleware compartilhado de expiração e inatividade de sessão por perfil.
    Posicionamento: APÓS AuthenticationMiddleware.

    1. Contas exclusivas de TV (Visualizador / Visualizador Matrizaria / 'tv' / 'tv_matrizaria'):
       - Sessão perpétua de exibição contínua (~10 anos).
       - Isenção de logout por inatividade humana.

    2. Sessões Humanas (técnicos, operadores, liderança, administração):
       - Timeout padrão de inatividade humana: 5 minutos (configurável via INACTIVITY_TIMEOUT_SECONDS).
       - O servidor é a autoridade máxima de validação do tempo decorrido.
       - Consultas automáticas em background (TV polling, status de sessão) NÃO renovam a inatividade.
       - Ações humanas reais (navegação, cliques, digitação via keep-alive) renovam a sessão.
       - Ao expirar: encerra a sessão via logout seguro, bloqueia ações e redireciona para login.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, "user") and request.user.is_authenticated:
            user = request.user

            if is_dedicated_tv_account(user):
                # Conta de TV dedicada: sessão perpétua sem inatividade humana
                if not request.session.get("_session_expiry_checked"):
                    request.session.set_expiry(315360000)  # ~10 anos
                    request.session["_session_expiry_checked"] = True
                    request.session["_is_tv_session"] = True
            else:
                # Sessão humana: validação de inatividade no servidor
                now_ts = time.time()
                timeout = getattr(settings, "INACTIVITY_TIMEOUT_SECONDS", 300)
                last_activity = request.session.get("_last_human_activity")

                if last_activity is not None:
                    elapsed = now_ts - float(last_activity)
                    if elapsed > timeout:
                        # Sessão expirada no servidor!
                        logout(request)

                        is_ajax = (
                            request.headers.get("x-requested-with") == "XMLHttpRequest"
                            or request.path.startswith("/api/")
                            or "application/json" in request.headers.get("Accept", "")
                        )
                        if is_ajax:
                            return JsonResponse(
                                {
                                    "error": "session_expired",
                                    "message": "Sua sessão foi encerrada por inatividade.",
                                    "redirect_url": str(settings.LOGIN_URL),
                                },
                                status=401,
                            )

                        messages.info(request, "Sua sessão foi encerrada por inatividade.")
                        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

                # Filtra requisições de background automatizadas que NÃO devem renovar a inatividade
                exempt_bg_paths = [
                    "/matrizaria/api/tv/data/",
                    "/api/session/status/",
                ]
                is_bg = any(request.path.startswith(p) for p in exempt_bg_paths)

                if not is_bg:
                    request.session["_last_human_activity"] = now_ts

        response = self.get_response(request)
        return response
