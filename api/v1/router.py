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
from apps.prescricao.views import (
    AdministracaoMedicamentoViewSet,
    PrescricaoViewSet,
)
from apps.procedimentos.views import (
    CategoriaProcedimentoViewSet,
    ExecucaoProcedimentoViewSet,
    ProcedimentoViewSet,
)
from apps.internacao.views import (
    AdministracaoMedicamentoInternacaoViewSet,
    CuidadoInternacaoViewSet,
    EvolucaoInternacaoViewSet,
    InternacaoCentralView,
    InternacaoViewSet,
    LeitoViewSet,
    OcupacaoLeitoViewSet,
)
from apps.servicos.views import (
    CategoriaServicoViewSet,
    OrcamentoViewSet,
    ServicoRealizadoViewSet,
    ServicoViewSet,
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
router.register("prescricoes", PrescricaoViewSet, basename="prescricao")
router.register(
    "administracoes-medicamento",
    AdministracaoMedicamentoViewSet,
    basename="administracao-medicamento",
)
router.register(
    "categorias-procedimento",
    CategoriaProcedimentoViewSet,
    basename="categoria-procedimento",
)
router.register("procedimentos", ProcedimentoViewSet, basename="procedimento")
router.register(
    "execucoes-procedimento",
    ExecucaoProcedimentoViewSet,
    basename="execucao-procedimento",
)
router.register("leitos", LeitoViewSet, basename="leito")
router.register(
    "ocupacoes-leito",
    OcupacaoLeitoViewSet,
    basename="ocupacao-leito",
)
router.register("internacoes", InternacaoViewSet, basename="internacao")
router.register(
    "evolucoes-internacao",
    EvolucaoInternacaoViewSet,
    basename="evolucao-internacao",
)
router.register(
    "cuidados-internacao",
    CuidadoInternacaoViewSet,
    basename="cuidado-internacao",
)
router.register(
    "administracoes-internacao",
    AdministracaoMedicamentoInternacaoViewSet,
    basename="administracao-internacao",
)
router.register(
    "categorias-servico",
    CategoriaServicoViewSet,
    basename="categoria-servico",
)
router.register("servicos", ServicoViewSet, basename="servico")
router.register("orcamentos", OrcamentoViewSet, basename="orcamento")
router.register(
    "servicos-realizados",
    ServicoRealizadoViewSet,
    basename="servico-realizado",
)

urlpatterns = router.urls + [
    path(
        "internacao/central/",
        InternacaoCentralView.as_view(),
        name="internacao-central",
    ),
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
