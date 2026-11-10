"""Verificações de saúde do VetManager.

Cada verificação devolve um dicionário com ``status`` (``ok`` /
``nao_configurado`` / ``erro``), latência e um detalhe seguro. Nenhuma
verificação expõe credenciais, strings de conexão ou dados clínicos: em caso
de falha devolvemos apenas o tipo da exceção.

As funções são pequenas e isoladas para poderem ser mockadas nos testes.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import connection

# Limite padrão de espaço livre em disco para o diretório de mídia.
_LIVRE_MINIMO_PADRAO = 100 * 1024 * 1024  # 100 MB


def _ms(inicio: float) -> float:
    return round((time.perf_counter() - inicio) * 1000, 1)


def _erro(inicio: float, exc: BaseException) -> dict:
    return {
        "status": "erro",
        "latencia_ms": _ms(inicio),
        "erro_tipo": type(exc).__name__,
    }


def verificar_backend() -> dict:
    """Liveness: o processo Django está no ar e respondendo."""

    return {"status": "ok", "latencia_ms": 0.0}


def verificar_banco() -> dict:
    """Readiness: o PostgreSQL responde a um SELECT trivial."""

    inicio = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - vira status, não exception
        return _erro(inicio, exc)
    return {"status": "ok", "latencia_ms": _ms(inicio)}


def _backend_cache() -> str:
    try:
        return str(settings.CACHES["default"]["BACKEND"])
    except (AttributeError, KeyError, TypeError):
        return ""


def verificar_cache() -> dict:
    """Readiness: Redis (quando configurado) aceita set/get.

    Se o cache for local (LocMem), não há serviço externo a verificar: o
    status é ``nao_configurado`` e isso não derruba a readiness.
    """

    backend = _backend_cache()
    if "redis" not in backend.lower():
        return {
            "status": "nao_configurado",
            "latencia_ms": 0.0,
            "detalhe": "cache local (LocMem); Redis nao configurado",
        }

    inicio = time.perf_counter()
    chave = f"healthcheck:{os.getpid()}:{time.time_ns()}"
    try:
        cache.set(chave, "ok", timeout=5)
        valor = cache.get(chave)
        if valor != "ok":
            raise RuntimeError("cache nao devolveu o valor gravado")
    except Exception as exc:  # noqa: BLE001
        return _erro(inicio, exc)
    finally:
        try:
            cache.delete(chave)
        except Exception:  # pragma: no cover - limpeza best-effort
            pass
    return {"status": "ok", "latencia_ms": _ms(inicio)}


def verificar_worker() -> dict:
    """Readiness: worker assíncrono.

    O projeto não possui Celery/RQ configurado hoje. Devolvemos
    ``nao_configurado`` em vez de fingir um worker saudável. Quando um worker
    for adicionado, ele deve gravar um heartbeat no cache e esta função deve
    checá-lo.
    """

    return {
        "status": "nao_configurado",
        "latencia_ms": 0.0,
        "detalhe": "nenhum worker assincrono configurado",
    }


def verificar_armazenamento() -> dict:
    """Readiness: MEDIA_ROOT existe, aceita escrita e tem espaço livre."""

    inicio = time.perf_counter()
    raiz = Path(settings.MEDIA_ROOT)
    try:
        raiz.mkdir(parents=True, exist_ok=True)
        teste = raiz / f".healthcheck-{os.getpid()}"
        teste.write_text("ok", encoding="utf-8")
        if teste.read_text(encoding="utf-8") != "ok":
            raise RuntimeError("nao foi possivel ler o arquivo de teste")
        teste.unlink()
        livre = shutil.disk_usage(raiz).free
        minimo = int(
            getattr(settings, "HEALTH_MIN_FREE_BYTES", _LIVRE_MINIMO_PADRAO)
        )
        if livre < minimo:
            raise RuntimeError("espaco livre abaixo do minimo")
    except Exception as exc:  # noqa: BLE001
        return _erro(inicio, exc)
    return {
        "status": "ok",
        "latencia_ms": _ms(inicio),
        "livre_bytes": livre,
    }


# Ordem estável para a resposta e para os testes.
CHECKS_READINESS = (
    ("backend", verificar_backend),
    ("database", verificar_banco),
    ("cache", verificar_cache),
    ("worker", verificar_worker),
    ("storage", verificar_armazenamento),
)


def executar_readiness() -> dict[str, dict]:
    return {nome: funcao() for nome, funcao in CHECKS_READINESS}
