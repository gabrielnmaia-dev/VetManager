"""Métricas operacionais simples do VetManager.

Contadores em memória (cache) de eventos que o AccessLogMiddleware e os
healthchecks registram. Expomos um endpoint JSON (`/health/metrics/`) para
que ferramentas externas (Prometheus, Datadog, etc.) coletem.

Não é um substituto de um sistema de monitoramento dedicado, mas permite
identificar falhas, lentidão, erros 500 e falhas de comunicação externa sem
depender de dependências extras (prometheus_client).

Os valores são acumulados no cache padrão (LocMem em teste/dev, Redis em
produção). Reinicie o serviço para zerar os contadores.
"""

from __future__ import annotations

import os
import time

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from core.logging_context import obter_request_id

# Prefixo das chaves de contador no cache.
_PREFIXO = "vetmanager:metricas:"

# Janela (segundos) usada para calcular taxa de erro/sucesso nos últimos N.
JANELA_SEGUNDOS = int(getattr(settings, "METRICA_JANELA_SEGUNDOS", 300))

_NOMES_CONTADORES = (
    "total_failures",
    "erros_500",
    "lentidao",
    "falhas_externas",
)


def _chave(nome: str) -> str:
    return f"{_PREFIXO}{nome}"


def _registrar(nome: str, incremento: int = 1) -> None:
    try:
        cache.incr(_chave(nome), delta=incremento)
    except ValueError:
        cache.set(_chave(nome), incremento, timeout=None)


def incrementar_failures() -> None:
    """Conta falhas totais de requisição (erros 500 / exceções)."""
    _registrar("total_failures")


def incrementar_erros_500() -> None:
    """Conta respostas com status 500."""
    _registrar("erros_500")


def incrementar_lentidao() -> None:
    """Conta requisições acima do limite de lentidão."""
    _registrar("lentidao")


def incrementar_falha_externa(servico: str) -> None:
    """Conta falha de comunicação com serviço externo (Softcom, e-mail, etc.)."""
    _registrar("falhas_externas")
    _registrar(f"falhas_externas:{servico}")


def contadores() -> dict:
    """Lê todos os contadores acumulados no cache."""

    resultado: dict[str, int] = {}
    for nome in _NOMES_CONTADORES:
        try:
            valor = cache.get(_chave(nome)) or 0
        except Exception:
            valor = 0
        resultado[nome] = int(valor)

    # Falhas por serviço externo (varredura leve das chaves presentes).
    externos: dict[str, int] = {}
    for servico in ("softcom", "email", "sms"):
        try:
            valor = cache.get(_chave(f"falhas_externas:{servico}")) or 0
        except Exception:
            valor = 0
        externos[servico] = int(valor)

    return {
        "total_failures": resultado.get("total_failures", 0),
        "erros_500": resultado.get("erros_500", 0),
        "lentidao": resultado.get("lentidao", 0),
        "falhas_externas": {
            "total": resultado.get("falhas_externas", 0),
            "por_servico": externos,
        },
        "janela_segundos": JANELA_SEGUNDOS,
        "timestamp": time.time(),
    }


@never_cache
@require_GET
def metrics(request):
    """Endpoint JSON com contadores operacionais acumulados."""

    payload = {
        "servico": getattr(settings, "SERVICE_NAME", "vetmanager-api"),
        "ambiente": getattr(settings, "ENVIRONMENT", "development"),
        "request_id": obter_request_id(),
        "metricas": contadores(),
    }
    return JsonResponse(payload, status=200)
