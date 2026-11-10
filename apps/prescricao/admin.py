from django.contrib import admin

from .models import (
    AdministracaoMedicamento,
    ItemPrescricao,
    Prescricao,
)


class ItemPrescricaoInline(admin.TabularInline):
    model = ItemPrescricao
    extra = 0
    autocomplete_fields = ("produto",)
    fields = (
        "produto",
        "dose",
        "via",
        "frequencia",
        "duracao",
        "quantidade_prescrita",
        "observacoes",
    )


@admin.register(Prescricao)
class PrescricaoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pet",
        "veterinario",
        "data_prescricao",
        "status",
    )
    list_filter = ("status", "data_prescricao")
    search_fields = (
        "pet__nome",
        "pet__tutor__nome",
        "veterinario__profissional__nome",
    )
    inlines = [ItemPrescricaoInline]
    readonly_fields = (
        "status",
        "motivo_cancelamento",
        "cancelada_em",
        "cancelada_por",
    )


@admin.register(ItemPrescricao)
class ItemPrescricaoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "prescricao",
        "produto",
        "dose",
        "via",
        "quantidade_prescrita",
    )
    list_filter = ("via",)
    search_fields = ("produto__nome", "prescricao__pet__nome")
    autocomplete_fields = ("prescricao", "produto")


@admin.register(AdministracaoMedicamento)
class AdministracaoMedicamentoAdmin(admin.ModelAdmin):
    """Somente leitura: a criação precisa passar pelo serviço transacional."""

    list_display = (
        "data_hora",
        "pet",
        "produto",
        "lote",
        "quantidade",
        "via",
        "profissional",
        "status",
    )
    list_filter = ("status", "via", "data_hora")
    search_fields = (
        "pet__nome",
        "produto__nome",
        "lote__numero_lote",
        "profissional__nome",
    )
    date_hierarchy = "data_hora"
    readonly_fields = [
        field.name for field in AdministracaoMedicamento._meta.fields
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
