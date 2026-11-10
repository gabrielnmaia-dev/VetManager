"""
Middlewares operacionais do VetManager.

* ``ApiNoStoreMiddleware`` — impede cache de respostas da API.
* ``RequestContextMiddleware`` — gera/propaga ``X-Request-ID`` e limpa o
  contexto de logging a cada requisição.
* ``AccessLogMiddleware`` — registra cada requisição em log estruturado com
  duração, status, usuário e request id. É a base para detectar lentidão,
  falhas e erros 500.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid

from core.logging_context import (
    definir_request_id,
    definir_usuario_id,
    limpar_contexto,
    obter_usuario_id,
)

logger_acesso = logging.getLogger("vetmanager.access")

# Só aceitamos request ids simples vindos de proxies/clientes. Qualquer coisa
# fora do padrão é substituída por um UUID gerado pelo próprio backend.
_REQUEST_ID_VALIDO = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Caminhos cujo log de acesso é ruído (estáticos e sondas de saúde).
_PREFIXOS_SEM_LOG = ("/static/", "/media/", "/favicon.ico", "/health/")

_LENTO_MS_PADRAO = 1000


class ApiNoStoreMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
        return response


class RequestContextMiddleware:
    """Atribui um ``request_id`` e zera o contexto no fim da requisição."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limpar_contexto()
        recebido = (request.META.get("HTTP_X_REQUEST_ID") or "").strip()
        request_id = (
            recebido if _REQUEST_ID_VALIDO.fullmatch(recebido) else uuid.uuid4().hex
        )
        definir_request_id(request_id)
        request.request_id = request_id
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request_id
            return response
        finally:
            limpar_contexto()


def _usuario_da_requisicao(request) -> str | None:
    # JWTs (interno e portal) preenchem o contexto durante a autenticação.
    usuario = obter_usuario_id()
    if usuario:
        return usuario
    try:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return str(user.pk)
    except Exception:  # pragma: no cover - nunca deve derrubar a requisição
        return None
    return None


def _rota(request) -> str:
    # Apenas o caminho: query string pode conter dados sensíveis em filtros.
    return request.path[:500]


def _view(request) -> str | None:
    match = getattr(request, "resolver_match", None)
    return getattr(match, "view_name", None) if match else None


class AccessLogMiddleware:
    """Loga cada requisição no logger ``vetmanager.access``."""

    def __init__(self, get_response):
        self.get_response = get_response
        try:
            from django.conf import settings

            self.limite_lento_ms = int(
                getattr(
                    settings,
                    "ACCESS_LOG_SLOW_MS",
                    os.environ.get("ACCESS_LOG_SLOW_MS", _LENTO_MS_PADRAO),
                )
            )
        except (TypeError, ValueError):
            self.limite_lento_ms = _LENTO_MS_PADRAO

    def __call__(self, request):
        if request.path.startswith(_PREFIXOS_SEM_LOG):
            return self.get_response(request)

        inicio = time.perf_counter()
        try:
            response = self.get_response(request)
        except Exception as exc:
            duracao = (time.perf_counter() - inicio) * 1000
            definir_usuario_id(_usuario_da_requisicao(request))
            logger_acesso.error(
                "Requisicao falhou",
                extra={
                    "operacao": _view(request) or "http.request",
                    "metodo": request.method,
                    "rota": _rota(request),
                    "status_code": 500,
                    "duracao_ms": round(duracao, 1),
                    "erro_tipo": type(exc).__name__,
                    "erro_mensagem": str(exc)[:300],
                },
                exc_info=exc,
            )
            from apps.health.metrics import incrementar_failures, incrementar_erros_500

            incrementar_failures()
            incrementar_erros_500()
            raise

        duracao = (time.perf_counter() - inicio) * 1000
        definir_usuario_id(_usuario_da_requisicao(request))
        extra = {
            "operacao": _view(request) or "http.request",
            "metodo": request.method,
            "rota": _rota(request),
            "status_code": response.status_code,
            "duracao_ms": round(duracao, 1),
        }

        if response.status_code >= 500:
            logger_acesso.error("Requisicao finalizada com erro", extra=extra)
            from apps.health.metrics import incrementar_failures, incrementar_erros_500

            incrementar_failures()
            incrementar_erros_500()
        elif duracao >= self.limite_lento_ms:
            extra["lentidao"] = True
            logger_acesso.warning("Requisicao lenta", extra=extra)
            from apps.health.metrics import incrementar_lentidao

            incrementar_lentidao()
        else:
            logger_acesso.info("Requisicao concluida", extra=extra)

        return response
