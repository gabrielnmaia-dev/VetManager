from django.contrib import admin

from .models import (
    CategoriaProcedimento,
    ExecucaoProcedimento,
    MaterialPrevistoProcedimento,
    MaterialUtilizadoProcedimento,
    Procedimento,
)


@admin.register(CategoriaProcedimento)
class CategoriaProcedimentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "ativo", "created_at")
    list_filter = ("ativo",)
    search_fields = ("nome", "descricao")


class MaterialPrevistoInline(admin.TabularInline):
    model = MaterialPrevistoProcedimento
    extra = 0
    autocomplete_fields = ("produto",)
    fields = ("produto", "quantidade_prevista", "observacoes")


@admin.register(Procedimento)
class ProcedimentoAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "categoria",
        "tipo",
        "duracao_estimada_minutos",
        "ativo",
    )
    list_filter = ("tipo", "ativo", "categoria")
    search_fields = ("nome", "descricao", "categoria__nome")
    inlines = [MaterialPrevistoInline]


@admin.register(MaterialPrevistoProcedimento)
class MaterialPrevistoProcedimentoAdmin(admin.ModelAdmin):
    list_display = ("procedimento", "produto", "quantidade_prevista")
    search_fields = ("procedimento__nome", "produto__nome")
    autocomplete_fields = ("procedimento", "produto")


class MaterialUtilizadoInline(admin.TabularInline):
    model = MaterialUtilizadoProcedimento
    extra = 0
    can_delete = False
    fields = (
        "produto",
        "lote",
        "quantidade",
        "movimentacao",
        "estorno_movimentacao",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ExecucaoProcedimento)
class ExecucaoProcedimentoAdmin(admin.ModelAdmin):
    """Somente leitura: a criação precisa passar pelo serviço transacional."""

    list_display = (
        "data_hora",
        "pet",
        "procedimento",
        "profissional",
        "status",
    )
    list_filter = ("status", "procedimento__tipo", "data_hora")
    search_fields = (
        "pet__nome",
        "pet__tutor__nome",
        "procedimento__nome",
        "profissional__nome",
    )
    date_hierarchy = "data_hora"
    filter_horizontal = ("equipe",)
    inlines = [MaterialUtilizadoInline]
    readonly_fields = [
        field.name for field in ExecucaoProcedimento._meta.fields
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
