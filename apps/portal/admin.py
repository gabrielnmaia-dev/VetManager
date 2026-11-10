from django.contrib import admin

from .models import (
    AcessoPortal,
    ConviteAcessoPortal,
    NotificacaoPortal,
    RecuperacaoSenhaPortal,
    SessaoPortal,
    SolicitacaoAgendamento,
)


@admin.register(ConviteAcessoPortal)
class ConviteAcessoPortalAdmin(admin.ModelAdmin):
    list_display = ("email", "tutor", "status", "expira_em", "created_at")
    list_filter = ("revogado_em", "usado_em")
    search_fields = ("email", "tutor__nome")
    readonly_fields = ("token_hash", "created_at", "updated_at")


@admin.register(AcessoPortal)
class AcessoPortalAdmin(admin.ModelAdmin):
    list_display = ("user", "tutor", "ativo", "ultimo_acesso_em", "created_at")
    list_filter = ("ativo",)
    search_fields = ("user__username", "user__email", "tutor__nome")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SessaoPortal)
class SessaoPortalAdmin(admin.ModelAdmin):
    list_display = ("acesso", "expira_em", "revogada_em", "ip", "created_at")
    list_filter = ("revogada_em",)
    search_fields = ("acesso__user__username", "acesso__tutor__nome")
    readonly_fields = ("jti", "created_at", "updated_at")


@admin.register(SolicitacaoAgendamento)
class SolicitacaoAgendamentoAdmin(admin.ModelAdmin):
    list_display = ("pet", "tutor", "tipo_servico", "data_preferida", "status")
    list_filter = ("status", "tipo_servico", "periodo")
    search_fields = ("pet__nome", "tutor__nome")
    readonly_fields = ("created_at", "updated_at")


@admin.register(NotificacaoPortal)
class NotificacaoPortalAdmin(admin.ModelAdmin):
    list_display = ("titulo", "tutor", "tipo", "lida", "created_at")
    list_filter = ("lida", "tipo")
    search_fields = ("titulo", "mensagem", "tutor__nome")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RecuperacaoSenhaPortal)
class RecuperacaoSenhaPortalAdmin(admin.ModelAdmin):
    list_display = ("user", "expira_em", "usado_em", "created_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("token_hash", "created_at", "updated_at")
