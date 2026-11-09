from rest_framework.routers import DefaultRouter
from django.urls import path
from apps.accounts.views import AlterarSenhaView, PerfilView
from apps.tutores.views import TutorViewSet
from apps.pets.views import (
    PetViewSet,
    EspecieViewSet,
    RacaViewSet,
    HistoricoResponsabilidadePetViewSet,
    MedicaoVitalViewSet,
)
from apps.atendimentos.views import AtendimentoViewSet
from apps.veterinarios.views import (
    ProfissionalViewSet,
    VeterinarioViewSet,
    TipoServicoViewSet,
    SalaConsultorioViewSet,
    HorarioTrabalhoViewSet,
    BloqueioAgendaViewSet,
    ListaEsperaViewSet,
    AgendamentoRecorrenteViewSet,
    HistoricoStatusAtendimentoViewSet,
)
from apps.documentos.views import (
    DocumentoClinicoViewSet,
    DocumentoVeterinarioViewSet,
    ModeloDocumentoViewSet,
)
from apps.prontuario.views import ProntuarioViewSet, VacinaViewSet
from apps.dashboard.views import DashboardView

router = DefaultRouter()
router.register("tutores", TutorViewSet, basename="tutor")
router.register("pets", PetViewSet, basename="pet")
router.register("especies", EspecieViewSet, basename="especie")
router.register("racas", RacaViewSet, basename="raca")
router.register(
    "historicos-responsabilidade-pet",
    HistoricoResponsabilidadePetViewSet,
    basename="historico-responsabilidade-pet",
)
router.register(
    "medicoes-vitais",
    MedicaoVitalViewSet,
    basename="medicao-vital",
)
router.register("documentos-clinicos", DocumentoClinicoViewSet, basename="documento-clinico")
router.register(
    "documentos-veterinarios",
    DocumentoVeterinarioViewSet,
    basename="documento-veterinario",
)
router.register("modelos-documento", ModeloDocumentoViewSet, basename="modelo-documento")
router.register("atendimentos", AtendimentoViewSet, basename="atendimento")
router.register("profissionais", ProfissionalViewSet, basename="profissional")
router.register("veterinarios", VeterinarioViewSet, basename="veterinario")
router.register("tipos-servico", TipoServicoViewSet, basename="tipo-servico")
router.register("salas", SalaConsultorioViewSet, basename="sala")
router.register("horarios-trabalho", HorarioTrabalhoViewSet, basename="horario-trabalho")
router.register("bloqueios-agenda", BloqueioAgendaViewSet, basename="bloqueio-agenda")
router.register("lista-espera", ListaEsperaViewSet, basename="lista-espera")
router.register(
    "agendamentos-recorrentes",
    AgendamentoRecorrenteViewSet,
    basename="agendamento-recorrente",
)
router.register(
    "historicos-status-atendimento",
    HistoricoStatusAtendimentoViewSet,
    basename="historico-status-atendimento",
)
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
