"""Modelos abstratos compartilhados por todos os apps.

Concentra três preocupações transversais:

* **Autoria** — ``created_by``/``updated_by``/``deleted_by`` são preenchidos
  exclusivamente pelo backend a partir do usuário autenticado.
* **Exclusão lógica** — ``delete()`` marca ``is_deleted`` em vez de apagar a
  linha. ``objects`` esconde os excluídos; ``all_objects`` enxerga tudo
  (inclusive para restauração e para o admin).
* **Auditoria** — os campos de data e autoria são a base dos snapshots
  registrados em ``apps.auditoria``.

Nenhum desses campos deve ser aceito em payloads de API: são ``editable=False``
e os serializers não os expõem para escrita.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ActiveManager(models.Manager):
    """Manager padrão: só registros não excluídos logicamente."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """Manager de base: enxerga inclusive registros excluídos.

    É o ``base_manager_name`` para que FKs continuem resolvendo mesmo quando o
    registro apontado foi excluído logicamente (evita
    ``RelatedObjectDoesNotExist`` em históricos/auditoria).
    """

    def get_queryset(self):
        return super().get_queryset()


class AuditFieldsModel(models.Model):
    """Datas e autoria comuns. Não define PK (usado por modelos legados)."""

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="criado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="atualizado por",
    )

    class Meta:
        abstract = True

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="criado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="atualizado por",
    )

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Exclusão lógica com recuperação controlada."""

    is_deleted = models.BooleanField(default=False, db_index=True, editable=False)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="excluído por",
    )

    # objects = visão normal da aplicação; all_objects = visão administrativa.
    objects = ActiveManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True
        base_manager_name = "all_objects"
        default_manager_name = "objects"

    @property
    def is_active(self) -> bool:
        return not self.is_deleted

    def soft_delete(self, user=None):
        """Marca o registro como excluído, preservando o histórico."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user is not None and getattr(user, "is_authenticated", False):
            self.deleted_by = user
        update_fields = ["is_deleted", "deleted_at", "deleted_by"]
        if hasattr(self, "updated_by"):
            update_fields.append("updated_by")
        self.save(update_fields=update_fields)
        return self

    def restore(self, user=None):
        """Recupera um registro excluído logicamente."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        if user is not None and getattr(user, "is_authenticated", False):
            if hasattr(self, "updated_by"):
                self.updated_by = user
        update_fields = ["is_deleted", "deleted_at", "deleted_by"]
        if hasattr(self, "updated_by"):
            update_fields.append("updated_by")
        self.save(update_fields=update_fields)
        return self

    def delete(self, using=None, keep_parents=False, *, user=None):
        """Exclusão padrão da aplicação é lógica.

        Para remoção física (ex.: limpeza de dados de teste) use
        :meth:`hard_delete`.
        """
        return self.soft_delete(user=user)

    def hard_delete(self, using=None, keep_parents=False):
        """Remoção física — reservada a rotinas administrativas explícitas."""
        return super().delete(using=using, keep_parents=keep_parents)


class BaseModel(AuditFieldsModel, SoftDeleteModel):
    """Modelo base dos cadastros principais (PK UUID + soft delete + autoria)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta(AuditFieldsModel.Meta, SoftDeleteModel.Meta):
        abstract = True

    def save(self, *args, user=None, **kwargs):
        """Preenche a autoria com o usuário autenticado, quando informado.

        O parâmetro ``user`` é keyword-only e nunca vem do payload: os
        serializers/services o obtêm de ``request.user``.
        """
        if user is not None and getattr(user, "is_authenticated", False):
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                update_fields = set(update_fields)
            if self._state.adding:
                self.created_by = user
                if update_fields is not None:
                    update_fields.add("created_by")
            self.updated_by = user
            if update_fields is not None:
                update_fields.add("updated_by")
                kwargs["update_fields"] = update_fields
        return super().save(*args, **kwargs)
