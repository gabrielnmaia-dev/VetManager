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
from apps.prontuario.views import (
    ProntuarioViewSet,
    VacinaViewSet,
    VermifugacaoViewSet,
)
from apps.dashboard.views import (
    DashboardFiltrosView,
    DashboardHistoricoView,
    DashboardOperacionalView,
    DashboardView,
)
from apps.estoque.views import (
    CategoriaProdutoViewSet,
    EstoqueAlertasView,
    EstoqueDashboardView,
    FornecedorViewSet,
    InventarioViewSet,
    ItemInventarioViewSet,
    LoteViewSet,
    MovimentacaoEstoqueViewSet,
    ProdutoViewSet,
)

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
router.register(
    "vermifugacoes", VermifugacaoViewSet, basename="vermifugacao"
)
router.register(
    "categorias-produto",
    CategoriaProdutoViewSet,
    basename="categoria-produto",
)
router.register("produtos", ProdutoViewSet, basename="produto")
router.register("fornecedores", FornecedorViewSet, basename="fornecedor")
router.register("lotes", LoteViewSet, basename="lote")
router.register(
    "movimentacoes-estoque",
    MovimentacaoEstoqueViewSet,
    basename="movimentacao-estoque",
)
router.register("inventarios", InventarioViewSet, basename="inventario")
router.register(
    "itens-inventario", ItemInventarioViewSet, basename="item-inventario"
)

urlpatterns = router.urls + [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("estoque/dashboard/", EstoqueDashboardView.as_view(), name="estoque-dashboard"),
    path("estoque/alertas/", EstoqueAlertasView.as_view(), name="estoque-alertas"),
    path(
        "dashboard/operacional/",
        DashboardOperacionalView.as_view(),
        name="dashboard-operacional",
    ),
    path(
        "dashboard/historico/",
        DashboardHistoricoView.as_view(),
        name="dashboard-historico",
    ),
    path(
        "dashboard/filtros/",
        DashboardFiltrosView.as_view(),
        name="dashboard-filtros",
    ),
    path("perfil/", PerfilView.as_view(), name="perfil"),
    path(
        "perfil/alterar-senha/",
        AlterarSenhaView.as_view(),
        name="perfil-alterar-senha",
    ),
]
