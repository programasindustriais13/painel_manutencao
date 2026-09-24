import time
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import JsonResponse
from django.shortcuts import redirect, resolve_url

logger = logging.getLogger(__name__)


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


def is_background_request(request) -> bool:
    """
    Identifica requisições automáticas de background / polling que:
    - Podem consultar a sessão;
    - NUNCA renovam inatividade humana nem atualizam _last_human_activity;
    - Não gravam desnecessariamente na sessão para evitar contenção de concorrência.
    """
    path = request.path
    # 1. Rota real do polling assíncrono da TV da Matrizaria
    if path.startswith("/matrizaria/api/tv-data/"):
        return True
    # 2. Endpoint de consulta periódica de status de sessão pelo frontend
    if path.startswith("/api/session/status/"):
        return True
    # 3. Polling assíncrono do painel TV de manutenção via AJAX
    if path == "/tv/" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    return False


@receiver(user_logged_in)
def reset_session_inactivity_on_login(sender, request, user, **kwargs):
    """
    Ao realizar login com sucesso, limpa qualquer marcação residual de expiração lógica
    e reinicia o cronômetro de atividade humana no servidor.
    """
    if hasattr(request, "session"):
        request.session.pop("_session_expired", None)
        request.session["_last_human_activity"] = time.time()


class SessionExpiryByProfileMiddleware:
    """
    Middleware compartilhado de expiração e inatividade de sessão por perfil.
    Posicionamento: APÓS AuthenticationMiddleware e MessageMiddleware.

    1. Contas exclusivas de TV (Visualizador / Visualizador Matrizaria / 'tv' / 'tv_matrizaria'):
       - Sessão perpétua de exibição contínua (~10 anos).
       - Isenção de logout por inatividade humana.

    2. Sessões Humanas (técnicos, operadores, liderança, administração):
       - Timeout padrão de inatividade humana: 5 minutos (configurável via INACTIVITY_TIMEOUT_SECONDS).
       - O servidor é a autoridade máxima de validação do tempo decorrido.
       - Consultas automáticas em background (TV polling, status de sessão) NÃO renovam a inatividade.
       - Ações humanas reais (navegação, cliques, digitação via keep-alive) renovam a sessão.
       - Ao expirar: expiração LÓGICA e IDEMPOTENTE (sem delete físico no banco que cause SessionInterrupted
         em requisições concorrentes em trânsito).
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
                # Não interceptar requisições para rotas de autenticação (login, logout)
                auth_exempt_paths = ["/login/", "/logout/"]
                if any(request.path.startswith(p) for p in auth_exempt_paths):
                    return self.get_response(request)

                # Sessão humana: validação de inatividade no servidor
                now_ts = time.time()
                timeout = getattr(settings, "INACTIVITY_TIMEOUT_SECONDS", 300)
                last_activity = request.session.get("_last_human_activity")

                # Verifica se a sessão já foi logicamente expirada ou ultrapassou o timeout
                is_expired = bool(request.session.get("_session_expired"))
                if not is_expired and last_activity is not None:
                    elapsed = now_ts - float(last_activity)
                    if elapsed > timeout:
                        is_expired = True

                if is_expired:
                    # Marca logicamente na sessão sem deletar a linha de django_session (evita SessionInterrupted)
                    if not request.session.get("_session_expired"):
                        request.session["_session_expired"] = True
                        logger.info(
                            "Sessão humana expirada por inatividade (user=%s, path=%s)",
                            getattr(user, "username", "unknown"),
                            request.path,
                        )

                    # Desautentica em runtime na requisição atual
                    request.user = AnonymousUser()

                    is_ajax = (
                        request.headers.get("x-requested-with") == "XMLHttpRequest"
                        or request.path.startswith("/api/")
                        or "application/json" in request.headers.get("Accept", "")
                    )
                    login_url = resolve_url(settings.LOGIN_URL)
                    if is_ajax:
                        logger.info("Requisição AJAX recusada por sessão expirada (path=%s)", request.path)
                        return JsonResponse(
                            {
                                "error": "session_expired",
                                "message": "Sua sessão foi encerrada por inatividade.",
                                "redirect_url": login_url,
                            },
                            status=401,
                        )

                    try:
                        messages.info(request, "Sua sessão foi encerrada por inatividade.")
                    except Exception:
                        pass
                    return redirect(f"{login_url}?next={request.path}")

                # Sessão ativa e válida:
                if last_activity is None:
                    request.session["_last_human_activity"] = now_ts
                elif not is_background_request(request):
                    # Throttling de atualização: evita UPDATE constante no banco para requisições GET rápidas
                    if request.method != "GET" or (now_ts - float(last_activity)) >= 30:
                        request.session["_last_human_activity"] = now_ts

        response = self.get_response(request)
        return response

