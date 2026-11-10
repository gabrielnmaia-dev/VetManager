"""Contexto por requisição usado pelos logs estruturados.

O Django (com Gunicorn em modo síncrono) atende uma requisição por thread, mas
``contextvars`` também funciona corretamente em ASGI/async. O middleware
``RequestContextMiddleware`` limpa o contexto no início e no fim de cada
requisição para evitar que o identificador ou o usuário "vazem" para a
próxima.
"""

from __future__ import annotations

from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("vetmanager_request_id", default=None)
_usuario_id: ContextVar[str | None] = ContextVar("vetmanager_usuario_id", default=None)


def definir_request_id(valor: str | None) -> None:
    _request_id.set(valor)


def obter_request_id() -> str | None:
    return _request_id.get()


def definir_usuario_id(valor: str | None) -> None:
    _usuario_id.set(str(valor) if valor is not None else None)


def obter_usuario_id() -> str | None:
    return _usuario_id.get()


def limpar_contexto() -> None:
    """Zera os valores do contexto atual (chamado pelo middleware)."""

    _request_id.set(None)
    _usuario_id.set(None)
