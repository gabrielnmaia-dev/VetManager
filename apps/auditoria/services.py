"""Serviço central de registro de auditoria.

Views e services chamam ``registrar`` depois de persistir a mudança. O módulo
não depende de DRF: recebe ``instance`` e, opcionalmente, a ``request`` para
capturar IP/user-agent.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from django.db import models

from .models import AuditLog


def _serializar_valor(valor):
    if isinstance(valor, (UUID, Decimal, date, datetime, time)):
        return str(valor)
    if isinstance(valor, bytes):
        return valor.hex()
    return valor


def snapshot(instance, *, exclude=()) -> dict:
    """Converte uma instância em um dict JSON-serializável de campos concretos.

    FKs viram o id (string), sem carregar objetos relacionados. Isso mantém o
    snapshot barato e estável mesmo com registros excluídos logicamente.
    """
    dados = {}
    for field in instance._meta.concrete_fields:
        if field.name in exclude:
            continue
        valor = field.value_from_object(instance)
        if isinstance(field, models.ForeignKey):
            dados[field.name] = str(valor) if valor is not None else None
        else:
            dados[field.name] = _serializar_valor(valor)
    return dados


def entidade_de(instance) -> str:
    return instance._meta.label_lower


def usuario_da_request(request):
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def _ip_da_request(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def _user_agent(request) -> str:
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "")[:255]


def registrar(
    *,
    usuario,
    acao: str,
    instancia,
    dados_anteriores: dict | None = None,
    dados_posteriores: dict | None = None,
    justificativa: str = "",
    request=None,
) -> AuditLog:
    """Persiste um evento de auditoria imutável.

    ``acao`` deve ser um dos valores de ``AuditLog.Acao``. ``usuario`` pode ser
    ``None`` (ex.: rotinas de sistema), mas o username é sempre registrado
    quando disponível.
    """
    if dados_posteriores is None and acao != AuditLog.Acao.EXCLUSAO:
        dados_posteriores = snapshot(instancia)

    return AuditLog.objects.create(
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        usuario_username=(
            usuario.get_username() if getattr(usuario, "is_authenticated", False) else ""
        ),
        acao=acao,
        entidade=entidade_de(instancia),
        entidade_id=str(instancia.pk),
        dados_anteriores=dados_anteriores,
        dados_posteriores=dados_posteriores,
        justificativa=(justificativa or "").strip(),
        ip=_ip_da_request(request),
        user_agent=_user_agent(request),
    )
