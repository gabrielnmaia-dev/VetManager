"""Mixins de ViewSet para autoria, auditoria e exclusão lógica."""

from rest_framework.exceptions import ValidationError

from apps.auditoria.models import AuditLog
from apps.auditoria.services import (
    registrar,
    snapshot,
    usuario_da_request,
)


class AuditModelViewSetMixin:
    """Registra auditoria e propaga o usuário em create/update/delete.

    A view concreta define ``audit_entidade`` apenas para documentação/legado;
    o rótulo efetivo vem do model da instância (``app_label.model_name``).
    """

    audit_entidade = None
    audit_exclude = ()

    def justificativa(self) -> str:
        data = getattr(self.request, "data", None)
        if hasattr(data, "get"):
            return data.get("justificativa", "") or ""
        return ""

    def perform_create(self, serializer):
        instance = serializer.save()
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=instance,
            request=self.request,
            justificativa=self.justificativa(),
        )

    def perform_update(self, serializer):
        anteriores = snapshot(serializer.instance, exclude=self.audit_exclude)
        instance = serializer.save()
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=instance,
            dados_anteriores=anteriores,
            request=self.request,
            justificativa=self.justificativa(),
        )

    def perform_destroy(self, instance):
        anteriores = snapshot(instance, exclude=self.audit_exclude)
        instance.delete(user=usuario_da_request(self.request))
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.EXCLUSAO,
            instancia=instance,
            dados_anteriores=anteriores,
            dados_posteriores=None,
            request=self.request,
            justificativa=self.justificativa(),
        )


class JustificativaObrigatoriaMixin:
    """Exige justificativa em exclusões de registros clínicos."""

    def perform_destroy(self, instance):
        if not self.justificativa().strip():
            raise ValidationError(
                {"justificativa": ["Informe a justificativa para excluir este registro clínico."]}
            )
        return super().perform_destroy(instance)
