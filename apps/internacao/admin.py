from django.contrib import admin

from .models import (
    AdministracaoMedicamentoInternacao,
    CuidadoInternacao,
    EvolucaoInternacao,
    Internacao,
    Leito,
    OcupacaoLeito,
)


class OcupacaoInline(admin.TabularInline):
    model = OcupacaoLeito
    extra = 0
    readonly_fields = ("leito", "data_entrada", "data_saida", "motivo_saida")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Leito)
class LeitoAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo", "capacidade", "situacao")
    list_filter = ("tipo", "situacao")
    search_fields = ("nome", "observacoes")


@admin.register(Internacao)
class InternacaoAdmin(admin.ModelAdmin):
    list_display = (
        "data_hora_entrada",
        "pet",
        "leito",
        "profissional_responsavel",
        "estado_clinico",
        "status",
    )
    list_filter = ("status", "estado_clinico", "leito__tipo")
    search_fields = (
        "pet__nome",
        "pet__tutor__nome",
        "motivo_internacao",
        "diagnostico_inicial",
    )
    readonly_fields = (
        "data_hora_alta",
        "profissional_alta",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    inlines = [OcupacaoInline]


@admin.register(OcupacaoLeito)
class OcupacaoLeitoAdmin(admin.ModelAdmin):
    list_display = ("leito", "internacao", "data_entrada", "data_saida")
    list_filter = ("leito",)
    search_fields = ("leito__nome", "internacao__pet__nome")


@admin.register(EvolucaoInternacao)
class EvolucaoInternacaoAdmin(admin.ModelAdmin):
    """Somente leitura: evoluções são imutáveis após o registro."""

    list_display = ("data_hora", "internacao", "profissional")
    list_filter = ("profissional", "data_hora")
    search_fields = ("internacao__pet__nome", "evolucao_clinica", "intercorrencias")
    readonly_fields = [field.name for field in EvolucaoInternacao._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CuidadoInternacao)
class CuidadoInternacaoAdmin(admin.ModelAdmin):
    list_display = ("data_hora", "internacao", "tipo", "profissional")
    list_filter = ("tipo", "profissional", "data_hora")
    search_fields = ("internacao__pet__nome", "descricao", "observacoes")
    readonly_fields = [field.name for field in CuidadoInternacao._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AdministracaoMedicamentoInternacao)
class AdministracaoMedicamentoInternacaoAdmin(admin.ModelAdmin):
    """Somente leitura: a baixa de estoque passa pelo serviço transacional."""

    list_display = (
        "data_hora",
        "internacao",
        "produto",
        "lote",
        "quantidade",
        "profissional",
        "status",
    )
    list_filter = ("status", "produto", "data_hora")
    search_fields = (
        "internacao__pet__nome",
        "produto__nome",
        "produto__principio_ativo",
        "lote__numero_lote",
    )
    readonly_fields = [
        field.name for field in AdministracaoMedicamentoInternacao._meta.fields
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
