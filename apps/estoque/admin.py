from django.contrib import admin

from .models import (
    CategoriaProduto,
    Fornecedor,
    Inventario,
    ItemInventario,
    Lote,
    MovimentacaoEstoque,
    Produto,
)


@admin.register(CategoriaProduto)
class CategoriaProdutoAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "ativo", "criado_em")
    list_filter = ("tipo", "ativo")
    search_fields = ("nome",)

    @admin.display(description="criado em")
    def criado_em(self, obj):
        return obj.created_at


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "codigo_interno",
        "categoria",
        "tipo_estoque",
        "estoque_minimo",
        "ativo",
    )
    list_filter = ("categoria", "tipo_estoque", "ativo", "requer_receita")
    search_fields = (
        "nome",
        "codigo_interno",
        "codigo_barras",
        "principio_ativo",
        "fabricante",
    )
    autocomplete_fields = ("categoria",)


@admin.register(Fornecedor)
class FornecedorAdmin(admin.ModelAdmin):
    list_display = ("nome", "cnpj", "telefone", "email", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome", "razao_social", "cnpj")


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = (
        "produto",
        "numero_lote",
        "data_validade",
        "quantidade_atual",
        "quantidade_inicial",
        "fornecedor",
    )
    list_filter = ("produto__tipo_estoque", "data_validade")
    search_fields = ("numero_lote", "produto__nome", "produto__codigo_interno")
    autocomplete_fields = ("produto", "fornecedor")


@admin.register(MovimentacaoEstoque)
class MovimentacaoEstoqueAdmin(admin.ModelAdmin):
    list_display = (
        "data_hora",
        "tipo",
        "produto",
        "lote",
        "direcao",
        "quantidade",
        "saldo_posterior",
        "created_by",
    )
    list_filter = ("tipo", "direcao")
    search_fields = ("produto__nome", "lote__numero_lote", "motivo")
    readonly_fields = [field.name for field in MovimentacaoEstoque._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ItemInventarioInline(admin.TabularInline):
    model = ItemInventario
    extra = 0
    readonly_fields = ("quantidade_sistema", "diferenca", "movimentacao")


@admin.register(Inventario)
class InventarioAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tipo_estoque",
        "status",
        "iniciado_em",
        "finalizado_em",
        "finalizado_por",
    )
    list_filter = ("tipo_estoque", "status")
    inlines = [ItemInventarioInline]


@admin.register(ItemInventario)
class ItemInventarioAdmin(admin.ModelAdmin):
    list_display = (
        "inventario",
        "lote",
        "quantidade_sistema",
        "quantidade_contada",
        "diferenca",
    )
    list_filter = ("inventario__status",)
    search_fields = ("lote__produto__nome", "lote__numero_lote")
