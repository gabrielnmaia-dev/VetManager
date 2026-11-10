from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    PortalAgendamentoViewSet,
    PortalAlterarSenhaView,
    PortalCsrfView,
    PortalDocumentoDownloadView,
    PortalDocumentosView,
    PortalLoginView,
    PortalLogoutView,
    PortalNotificacaoMarcarTodasView,
    PortalNotificacaoViewSet,
    PortalPerfilView,
    PortalPetViewSet,
    PortalPrescricaoViewSet,
    PortalRecuperarSenhaView,
    PortalRedefinirSenhaView,
    PortalRefreshView,
    PortalResgatarConviteView,
    PortalResumoView,
    PortalSolicitacaoCancelarView,
    PortalSolicitacaoAgendamentoViewSet,
    PortalVacinaViewSet,
)

router = DefaultRouter()
router.register("pets", PortalPetViewSet, basename="portal-pet")
router.register("agendamentos", PortalAgendamentoViewSet, basename="portal-agendamento")
router.register(
    "solicitacoes-agendamento",
    PortalSolicitacaoAgendamentoViewSet,
    basename="portal-solicitacao",
)
router.register("vacinas", PortalVacinaViewSet, basename="portal-vacina")
router.register("prescricoes", PortalPrescricaoViewSet, basename="portal-prescricao")
router.register("notificacoes", PortalNotificacaoViewSet, basename="portal-notificacao")

urlpatterns = [
    path("auth/csrf/", PortalCsrfView.as_view(), name="portal-csrf"),
    path("auth/login/", PortalLoginView.as_view(), name="portal-login"),
    path("auth/refresh/", PortalRefreshView.as_view(), name="portal-refresh"),
    path("auth/logout/", PortalLogoutView.as_view(), name="portal-logout"),
    path(
        "auth/recuperar-senha/",
        PortalRecuperarSenhaView.as_view(),
        name="portal-recuperar-senha",
    ),
    path(
        "auth/redefinir-senha/",
        PortalRedefinirSenhaView.as_view(),
        name="portal-redefinir-senha",
    ),
    path(
        "convites/resgatar/",
        PortalResgatarConviteView.as_view(),
        name="portal-resgatar-convite",
    ),
    path("perfil/", PortalPerfilView.as_view(), name="portal-perfil"),
    path(
        "perfil/alterar-senha/",
        PortalAlterarSenhaView.as_view(),
        name="portal-alterar-senha",
    ),
    path("resumo/", PortalResumoView.as_view(), name="portal-resumo"),
    path(
        "solicitacoes-agendamento/<uuid:pk>/cancelar/",
        PortalSolicitacaoCancelarView.as_view(),
        name="portal-solicitacao-cancelar",
    ),
    path("documentos/", PortalDocumentosView.as_view(), name="portal-documentos"),
    path(
        "documentos/<str:origem>/<uuid:pk>/download/",
        PortalDocumentoDownloadView.as_view(),
        name="portal-documento-download",
    ),
    path(
        "notificacoes/marcar-todas-lidas/",
        PortalNotificacaoMarcarTodasView.as_view(),
        name="portal-notificacoes-marcar-todas",
    ),
] + router.urls
