"""Trilha de auditoria append-only.

Registros de auditoria são imutáveis: não podem ser alterados nem removidos
pela aplicação. Qualquer tentativa levanta ``ProtectedError``. A limpeza, se
algum dia necessária, deve ser feita por rotina administrativa no banco, com
retenção definida em política própria.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import ProtectedError


class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ProtectedError(
            "Registros de auditoria são imutáveis e não podem ser alterados.",
            set(self),
        )

    def delete(self):
        raise ProtectedError(
            "Registros de auditoria são imutáveis e não podem ser excluídos.",
            set(self),
        )


class AuditLog(models.Model):
    """Um evento auditável: quem, o quê, quando, valores antes/depois."""

    class Acao(models.TextChoices):
        CRIACAO = "criacao", "Criação"
        ATUALIZACAO = "atualizacao", "Atualização"
        EXCLUSAO = "exclusao", "Exclusão lógica"
        RESTAURACAO = "restauracao", "Restauração"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auditorias",
        verbose_name="usuário",
    )
    # Snapshot do username: o registro continua legível se o usuário for
    # removido ou renomeado.
    usuario_username = models.CharField(max_length=150, blank=True)

    acao = models.CharField(max_length=20, choices=Acao.choices, db_index=True)
    entidade = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Rótulo estável no formato app_label.model_name.",
    )
    entidade_id = models.CharField(max_length=64, db_index=True)

    dados_anteriores = models.JSONField(null=True, blank=True)
    dados_posteriores = models.JSONField(null=True, blank=True)

    justificativa = models.TextField(blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        indexes = [
            models.Index(fields=["entidade", "entidade_id", "-criado_em"]),
            models.Index(fields=["usuario", "-criado_em"]),
        ]

    def __str__(self):
        return f"{self.get_acao_display()} {self.entidade}#{self.entidade_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ProtectedError(
                "Registros de auditoria são imutáveis e não podem ser alterados.",
                {self},
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ProtectedError(
            "Registros de auditoria não podem ser excluídos.",
            {self},
        )
