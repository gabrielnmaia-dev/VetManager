from django.contrib import admin

from .models import CategoriaProduto, Produto


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
