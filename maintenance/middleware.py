import time
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import JsonResponse
from django.shortcuts import redirect, resolve_url
from django.utils import timezone

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
        "Liderança Bladder",
        "Operadores Bladder",
    ]
    if user.groups.filter(name__in=operational_groups).exists():
        return False

    is_tv_name = user.username in ["tv", "tv_matrizaria"]
    is_tv_group = user.groups.filter(name__in=["Visualizador", "Visualizador Matrizaria"]).exists()
    return is_tv_name or is_tv_group


def is_night_shift_account(user, request=None) -> bool:
    """
    Identifica a conta restrita de retiradas noturnas do Setor de Bladder.
    Regra estrita:
    - Usuário autenticado;
    - Username 'noturno_bladder' ou flag de sessão 'is_night_shift_session'.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'username', '') == 'noturno_bladder':
        return True
    if request and hasattr(request, 'session') and request.session.get('is_night_shift_session'):
        return True
    return False


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
            elif is_night_shift_account(user, request):
                # Conta da Estação Noturna Bladder:
                if request.path.startswith("/logout/"):
                    return self.get_response(request)

                request.session.pop("_session_expired", None)
                if not request.session.get("_night_expiry_set"):
                    request.session.set_expiry(getattr(settings, "NIGHT_SHIFT_MAX_SECONDS", 16 * 3600))
                    request.session["_night_expiry_set"] = True
                    request.session["is_night_shift_session"] = True

                # Confinamento estrito de rotas
                if not (request.path.startswith("/bladder/noturno/") or request.path.startswith("/static/") or request.path.startswith("/api/session/")):
                    return redirect("/bladder/noturno/")

                # Teto absoluto de segurança de 16 horas
                now_ts = time.time()
                night_start = request.session.get("night_shift_start_ts")
                max_seconds = getattr(settings, "NIGHT_SHIFT_MAX_SECONDS", 16 * 3600)
                if night_start is not None and (now_ts - float(night_start)) > max_seconds:
                    logger.warning("Sessão noturna bladder expirada por teto máximo de 16h (user=%s)", user.username)
                    try:
                        from bladder.models import SessaoNoturnaBladder
                        sessao_id = request.session.get("sessao_noturna_id")
                        if sessao_id:
                            SessaoNoturnaBladder.objects.filter(id=sessao_id, status='ATIVA').update(
                                status='EXPIRADA',
                                data_hora_fim=timezone.now(),
                                observacoes='Sessão expirada pelo teto absoluto de 16 horas.'
                            )
                    except Exception as err:
                        logger.error("Erro ao marcar sessão noturna expirada: %s", err)
                    from django.contrib.auth import logout as auth_logout
                    auth_logout(request)
                    request.user = AnonymousUser()
                    login_url = resolve_url(settings.LOGIN_URL)
                    try:
                        messages.info(request, "A sessão da Estação Noturna atingiu o teto máximo de 16 horas e foi encerrada.")
                    except Exception:
                        pass
                    return redirect(f"{login_url}?next=/bladder/noturno/")

                request.session["_last_human_activity"] = now_ts
                return self.get_response(request)
            else:
                # Não interceptar requisições para logout
                if request.path.startswith("/logout/"):
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
                    # Se o usuário com sessão expirada já está na tela de login,
                    # limpa as chaves de autenticação da sessão e desautentica request.user
                    if request.path.startswith("/login/"):
                        was_already_marked = bool(request.session.get("_session_expired"))
                        from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
                        for key in [SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY, "_session_expired", "_last_human_activity"]:
                            request.session.pop(key, None)
                        request.session.modified = True
                        request.user = AnonymousUser()
                        if not was_already_marked:
                            try:
                                messages.info(request, "Sua sessão foi encerrada por inatividade.")
                            except Exception:
                                pass
                        return self.get_response(request)

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

                # Se for rota de login com sessão VÁLIDA (não expirada), permite passar para CustomLoginView
                if request.path.startswith("/login/"):
                    return self.get_response(request)

                # Sessão ativa e válida:
                if last_activity is None:
                    request.session["_last_human_activity"] = now_ts
                elif not is_background_request(request):
                    # Throttling de atualização: evita UPDATE constante no banco para requisições GET rápidas
                    if request.method != "GET" or (now_ts - float(last_activity)) >= 30:
                        request.session["_last_human_activity"] = now_ts

        response = self.get_response(request)
        return response

