from django.contrib import admin

from .models import (
    AplicacaoPagamento,
    Caixa,
    ContaReceber,
    FormaPagamento,
    HistoricoContaReceber,
    MovimentacaoCaixa,
    Pagamento,
    ParcelaContaReceber,
)


@admin.register(FormaPagamento)
class FormaPagamentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "ativo", "permite_parcelamento")
    list_filter = ("tipo", "ativo", "permite_parcelamento")
    search_fields = ("nome", "observacoes")


class ParcelaInline(admin.TabularInline):
    model = ParcelaContaReceber
    extra = 0
    readonly_fields = ("valor_pago", "saldo", "status")
    fields = ("numero", "vencimento", "valor", "valor_pago", "saldo", "status")


class HistoricoContaInline(admin.TabularInline):
    model = HistoricoContaReceber
    extra = 0
    can_delete = False
    readonly_fields = (
        "status_anterior",
        "status_novo",
        "valor_pago",
        "saldo",
        "usuario",
        "observacao",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ContaReceber)
class ContaReceberAdmin(admin.ModelAdmin):
    list_display = (
        "descricao",
        "tutor",
        "valor",
        "saldo",
        "vencimento",
        "status",
    )
    list_filter = ("status", "vencimento", "data_emissao")
    search_fields = ("descricao", "tutor__nome", "observacoes")
    readonly_fields = ("valor_pago", "saldo", "cancelado_em", "cancelado_por")
    inlines = [ParcelaInline, HistoricoContaInline]


class AplicacaoInline(admin.TabularInline):
    model = AplicacaoPagamento
    extra = 0
    can_delete = False
    readonly_fields = ("parcela", "valor")


@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = (
        "data_hora",
        "conta",
        "forma_pagamento",
        "valor",
        "status",
        "caixa",
    )
    list_filter = ("status", "forma_pagamento", "data_hora")
    search_fields = ("conta__descricao", "conta__tutor__nome", "observacoes")
    readonly_fields = ("estornado_em", "estornado_por", "motivo_estorno")
    inlines = [AplicacaoInline]


class MovimentacaoInline(admin.TabularInline):
    model = MovimentacaoCaixa
    extra = 0
    can_delete = False
    readonly_fields = (
        "tipo",
        "valor",
        "descricao",
        "forma_pagamento",
        "pagamento",
        "data_hora",
        "created_by",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Caixa)
class CaixaAdmin(admin.ModelAdmin):
    list_display = (
        "descricao",
        "status",
        "data_abertura",
        "data_fechamento",
        "valor_abertura",
        "valor_fechamento_sistema",
        "diferenca",
    )
    list_filter = ("status", "data_abertura")
    search_fields = ("descricao", "observacoes")
    readonly_fields = (
        "valor_fechamento_sistema",
        "diferenca",
        "usuario_abertura",
        "usuario_fechamento",
    )
    inlines = [MovimentacaoInline]


@admin.register(MovimentacaoCaixa)
class MovimentacaoCaixaAdmin(admin.ModelAdmin):
    list_display = ("data_hora", "caixa", "tipo", "valor", "descricao")
    list_filter = ("tipo", "data_hora", "caixa")
    search_fields = ("descricao", "caixa__descricao")
