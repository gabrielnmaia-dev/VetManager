from rest_framework.routers import DefaultRouter
from django.urls import path
from apps.accounts.views import AlterarSenhaView, PerfilView
from apps.tutores.views import TutorViewSet
from apps.pets.views import PetViewSet
from apps.atendimentos.views import AtendimentoViewSet
from apps.veterinarios.views import ProfissionalViewSet
from apps.prontuario.views import ProntuarioViewSet, VacinaViewSet
from apps.dashboard.views import DashboardView

router = DefaultRouter()
router.register("tutores", TutorViewSet, basename="tutor")
router.register("pets", PetViewSet, basename="pet")
router.register("atendimentos", AtendimentoViewSet, basename="atendimento")
router.register("profissionais", ProfissionalViewSet, basename="profissional")
router.register("prontuarios", ProntuarioViewSet, basename="prontuario")
router.register("vacinas", VacinaViewSet, basename="vacina")

urlpatterns = router.urls + [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("perfil/", PerfilView.as_view(), name="perfil"),
    path(
        "perfil/alterar-senha/",
        AlterarSenhaView.as_view(),
        name="perfil-alterar-senha",
    ),
]