"""Endpoints de healthcheck.

São views Django simples (não DRF) de propósito: não passam por autenticação,
throttling ou renderers, então funcionam mesmo se a camada de API estiver
degradada. Não expõem dados clínicos nem credenciais.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from core.logging_context import obter_request_id

from .checks import executar_readiness, verificar_backend


def _servico() -> str:
    return os.environ.get("SERVICE_NAME", "vetmanager-api")


def _ambiente() -> str:
    return os.environ.get(
        "ENVIRONMENT", getattr(settings, "ENVIRONMENT", "development")
    )


def _resposta(status: str, checks: dict, *, http_status: int) -> JsonResponse:
    payload = {
        "status": status,
        "timestamp": timezone.now().isoformat(),
        "servico": _servico(),
        "ambiente": _ambiente(),
        "request_id": obter_request_id(),
        "checks": checks,
    }
    resposta = JsonResponse(payload, status=http_status)
    resposta["Cache-Control"] = "no-store"
    return resposta


@never_cache
@require_GET
def liveness(request):
    """Liveness: apenas confirma que o processo responde. Sem I/O externo."""

    check = verificar_backend()
    return _resposta("ok", {"backend": check}, http_status=200)


@never_cache
@require_GET
def readiness(request):
    """Readiness: banco, cache/Redis, worker e armazenamento de arquivos."""

    checks = executar_readiness()
    # ``nao_configurado`` é aceitável (ex.: Redis/worker ausentes). Qualquer
    # verificação em ``erro`` indica que a instância não deve receber tráfego.
    falhou = any(item.get("status") == "erro" for item in checks.values())
    return _resposta(
        "erro" if falhou else "ok",
        checks,
        http_status=503 if falhou else 200,
    )
