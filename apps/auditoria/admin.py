from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Somente leitura: a trilha de auditoria não é editável nem removível."""

    list_display = (
        "criado_em",
        "acao",
        "entidade",
        "entidade_id",
        "usuario_username",
    )
    list_filter = ("acao", "entidade", "criado_em")
    search_fields = ("entidade", "entidade_id", "usuario_username", "justificativa")
    date_hierarchy = "criado_em"
    ordering = ("-criado_em",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in AuditLog._meta.fields]
