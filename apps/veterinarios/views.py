"""Views dos modelos de veterinários e agenda."""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, filters

from apps.base.views import AuditModelViewSetMixin

from .models import (
    AgendamentoRecorrente,
    BloqueioAgenda,
    HistoricoStatusAtendimento,
    HorarioTrabalho,
    ListaEspera,
    Profissional,
    SalaConsultorio,
    TipoServico,
    Veterinario,
)
from .serializers import (
    AgendamentoRecorrenteSerializer,
    BloqueioAgendaSerializer,
    HistoricoStatusAtendimentoSerializer,
    HorarioTrabalhoSerializer,
    ProfissionalSerializer,
    ProfissionalResumoSerializer,
    ProfissionalWriteSerializer,
    SalaConsultorioSerializer,
    TipoServicoSerializer,
    VeterinarioSerializer,
    ListaEsperaSerializer,
)


class ProfissionalViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Gerenciamento de profissionais (cadastro, edição, ativa/inativa)."""

    queryset = Profissional.objects.select_related("veterinario").all()
    serializer_class = ProfissionalSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["cargo", "ativo"]
    search_fields = ["nome", "cargo", "telefone"]
    audit_entidade = "profissional"
    # Gestão (criar/editar/excluir) restrita ao perfil admin, mas a leitura é
    # necessária para todos os papéis: a agenda e o formulário de atendimento
    # precisam listar os profissionais para selecionar o responsável.
    role_policy = {
        "list": ("admin", "veterinario", "recepcao"),
        "retrieve": ("admin", "veterinario", "recepcao"),
        "*": ("admin",),
    }

    def get_serializer_class(self):
        # create/update compartilham o serializer de escrita para que o CRMV
        # também possa ser informado/corrigido ao editar um profissional.
        if self.action in {"create", "update", "partial_update"}:
            return ProfissionalWriteSerializer
        return super().get_serializer_class()


class VeterinarioViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Cadastro de veterinários (CRMV, especialidade)."""

    queryset = (
        Veterinario.objects.select_related("profissional")
        .order_by("profissional__nome")
    )
    serializer_class = VeterinarioSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["profissional__nome", "crmv", "especialidade"]
    audit_entidade = "veterinario"
    # Leitura para todos os papéis que preenchem formulários clínicos;
    # cadastro/edição/exclusão restritos ao admin (como os profissionais).
    role_policy = {
        "list": ("admin", "veterinario", "recepcao"),
        "retrieve": ("admin", "veterinario", "recepcao"),
        "*": ("admin",),
    }


class TipoServicoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Catálogo de tipos de serviço (duração, intervalo, ativo)."""

    queryset = TipoServico.objects.all().order_by("nome")
    serializer_class = TipoServicoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["ativo"]
    search_fields = ["nome"]
    audit_entidade = "tipo_servico"
    role_policy = ("admin", "veterinario", "recepcao")


class SalaConsultorioViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Salas de consulta / consultórios."""

    queryset = SalaConsultorio.objects.all().order_by("nome")
    serializer_class = SalaConsultorioSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["ativo"]
    search_fields = ["nome"]
    audit_entidade = "sala"
    role_policy = ("admin", "veterinario", "recepcao")


class HorarioTrabalhoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Horários de trabalho semanal dos profissionais."""

    queryset = HorarioTrabalho.objects.select_related("profissional").all()
    serializer_class = HorarioTrabalhoSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["profissional", "dia_semana", "ativo"]
    ordering_fields = ["profissional", "dia_semana", "hora_inicio"]
    ordering = ["profissional", "dia_semana", "hora_inicio"]
    audit_entidade = "horario_trabalho"
    role_policy = ("admin", "veterinario", "recepcao")


class BloqueioAgendaViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Bloqueios de agenda (feriados, folgas, ausências, manutenção)."""

    queryset = BloqueioAgenda.objects.select_related(
        "profissional", "sala"
    ).all()
    serializer_class = BloqueioAgendaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["profissional", "sala", "tipo", "ativo"]
    search_fields = ["motivo", "profissional__nome", "sala__nome"]
    ordering_fields = ["data_inicio", "data_fim"]
    ordering = ["data_inicio"]
    audit_entidade = "bloqueio_agenda"
    role_policy = ("admin", "veterinario", "recepcao")


class ListaEsperaViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Lista de espera por vaga em horário desejado."""

    queryset = (
        ListaEspera.objects.select_related(
            "pet", "tutor", "profissional", "tipo_servico"
        )
        .all()
    )
    serializer_class = ListaEsperaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["pet", "tutor", "profissional", "tipo_servico", "ativo"]
    search_fields = ["pet__nome", "tutor__nome", "observacoes"]
    ordering_fields = ["data_desejada", "criado_em"]
    ordering = ["-criado_em"]
    audit_entidade = "lista_espera"
    role_policy = ("admin", "veterinario", "recepcao")


class AgendamentoRecorrenteViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Templates de agendamento recorrente."""

    queryset = (
        AgendamentoRecorrente.objects.select_related(
            "pet", "tutor", "profissional", "tipo_servico", "sala"
        )
        .all()
    )
    serializer_class = AgendamentoRecorrenteSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["pet", "tutor", "profissional", "tipo_servico", "dia_semana", "ativo"]
    search_fields = ["pet__nome", "tutor__nome", "profissional__nome"]
    ordering_fields = ["dia_semana", "hora_inicio", "data_inicio"]
    ordering = ["dia_semana", "hora_inicio"]
    audit_entidade = "agendamento_recorrente"
    role_policy = ("admin", "veterinario", "recepcao")


class HistoricoStatusAtendimentoViewSet(
    AuditModelViewSetMixin, viewsets.ReadOnlyModelViewSet
):
    """Histórico de mudanças de status (somente leitura - audit trail)."""

    queryset = (
        HistoricoStatusAtendimento.objects.select_related(
            "atendimento", "usuario"
        )
        .all()
    )
    serializer_class = HistoricoStatusAtendimentoSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["atendimento", "status_novo"]
    ordering_fields = ["data_operacao"]
    ordering = ["-data_operacao"]
    audit_entidade = "historico_status_atendimento"
    role_policy = ("admin", "veterinario", "recepcao")
