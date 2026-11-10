from django.contrib import admin

from .models import (
    CategoriaServico,
    HistoricoOrcamento,
    ItemOrcamento,
    Orcamento,
    Servico,
    ServicoRealizado,
)


@admin.register(CategoriaServico)
class CategoriaServicoAdmin(admin.ModelAdmin):
    list_display = ("nome", "ativo", "created_at")
    list_filter = ("ativo",)
    search_fields = ("nome", "descricao")


@admin.register(Servico)
class ServicoAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "categoria",
        "preco_base",
        "duracao_estimada_minutos",
        "situacao",
    )
    list_filter = ("situacao", "categoria", "permite_desconto")
    search_fields = ("nome", "descricao", "regras", "categoria__nome")
    autocomplete_fields = ("categoria",)


class ItemOrcamentoInline(admin.TabularInline):
    model = ItemOrcamento
    extra = 0
    autocomplete_fields = ("servico",)
    fields = (
        "servico",
        "quantidade",
        "valor_unitario",
        "desconto",
        "valor_total",
        "desconto_motivo",
        "observacoes",
    )
    readonly_fields = ("valor_total",)


class HistoricoOrcamentoInline(admin.TabularInline):
    model = HistoricoOrcamento
    extra = 0
    can_delete = False
    readonly_fields = (
        "status_anterior",
        "status_novo",
        "usuario",
        "observacao",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Orcamento)
class OrcamentoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pet",
        "tutor",
        "status",
        "validade",
        "valor_total",
        "data_hora",
    )
    list_filter = ("status", "validade")
    search_fields = ("pet__nome", "tutor__nome", "observacoes")
    readonly_fields = (
        "subtotal",
        "valor_desconto",
        "valor_total",
        "aprovado_em",
        "recusado_em",
        "convertido_em",
        "cancelado_em",
        "decidido_por",
    )
    inlines = [ItemOrcamentoInline, HistoricoOrcamentoInline]


@admin.register(ServicoRealizado)
class ServicoRealizadoAdmin(admin.ModelAdmin):
    list_display = (
        "data_hora",
        "pet",
        "servico",
        "profissional",
        "quantidade",
        "valor_total",
    )
    list_filter = ("servico", "profissional", "data_hora")
    search_fields = ("pet__nome", "pet__tutor__nome", "servico__nome")
    readonly_fields = (
        "valor_total",
        "desconto_autorizado_por",
        "orcamento_item",
    )
