from django.urls import path
from rest_framework.routers import DefaultRouter

from .views_admin import (
    AcessoPortalViewSet,
    ConviteAcessoPortalViewSet,
    LiberacaoDocumentoView,
    NotificacaoPortalAdminViewSet,
    SolicitacaoAgendamentoAdminViewSet,
)

router = DefaultRouter()
router.register("convites", ConviteAcessoPortalViewSet, basename="portal-admin-convite")
router.register("acessos", AcessoPortalViewSet, basename="portal-admin-acesso")
router.register(
    "solicitacoes",
    SolicitacaoAgendamentoAdminViewSet,
    basename="portal-admin-solicitacao",
)
router.register(
    "notificacoes",
    NotificacaoPortalAdminViewSet,
    basename="portal-admin-notificacao",
)

urlpatterns = router.urls + [
    path(
        "liberacoes/",
        LiberacaoDocumentoView.as_view(),
        name="portal-admin-liberacao",
    ),
]
