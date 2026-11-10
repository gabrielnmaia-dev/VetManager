"""Views do catálogo de serviços, orçamentos e serviços realizados.

A recepção consulta catálogo e orçamentos e pode registrar/editar propostas,
aprovar e recusar. A conversão em serviço realizado e o cadastro do catálogo
ficam restritos a administradores e veterinários.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.auditoria.models import AuditLog
from apps.auditoria.services import registrar, snapshot, usuario_da_request
from apps.base.views import AuditModelViewSetMixin

from . import services
from .models import (
    CategoriaServico,
    HistoricoOrcamento,
    Orcamento,
    Servico,
    ServicoRealizado,
)
from .serializers import (
    CategoriaServicoSerializer,
    ConversaoOrcamentoSerializer,
    HistoricoOrcamentoSerializer,
    OrcamentoSerializer,
    ServicoRealizadoSerializer,
    ServicoSerializer,
)

LEITURA = ("admin", "veterinario", "recepcao")
ESCRITA = ("admin", "veterinario")
COMERCIAL = ("admin", "veterinario", "recepcao")


class CategoriaServicoViewSet(
    AuditModelViewSetMixin, viewsets.ModelViewSet
):
    """Categorias comerciais dos serviços."""

    queryset = CategoriaServico.objects.all()
    serializer_class = CategoriaServicoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["ativo"]
    search_fields = ["nome", "descricao"]
    ordering_fields = ["nome", "ativo", "created_at"]
    ordering = ["nome"]
    audit_entidade = "categoria_servico"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "update": ESCRITA,
        "partial_update": ESCRITA,
        "destroy": ESCRITA,
        "*": ESCRITA,
    }


class ServicoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Catálogo de serviços, preços, duração e regras comerciais."""

    queryset = Servico.objects.select_related("categoria").all()
    serializer_class = ServicoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["categoria", "situacao", "permite_desconto"]
    search_fields = ["nome", "descricao", "regras", "categoria__nome"]
    ordering_fields = [
        "nome",
        "preco_base",
        "duracao_estimada_minutos",
        "situacao",
        "created_at",
    ]
    ordering = ["nome"]
    audit_entidade = "servico"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "update": ESCRITA,
        "partial_update": ESCRITA,
        "destroy": ESCRITA,
        "*": ESCRITA,
    }


class OrcamentoViewSet(
    AuditModelViewSetMixin, viewsets.ModelViewSet
):
    """Orçamentos com itens, decisão, histórico e conversão."""

    queryset = (
        Orcamento.objects.select_related(
            "tutor", "pet", "atendimento", "profissional", "decidido_por"
        )
        .prefetch_related("itens", "historico")
        .all()
    )
    serializer_class = OrcamentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "tutor",
        "pet",
        "atendimento",
        "profissional",
        "status",
    ]
    search_fields = [
        "pet__nome",
        "tutor__nome",
        "observacoes",
        "itens__servico__nome",
    ]
    ordering_fields = [
        "data_hora",
        "validade",
        "valor_total",
        "status",
        "created_at",
    ]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "orcamento"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": COMERCIAL,
        "update": COMERCIAL,
        "partial_update": COMERCIAL,
        "destroy": ESCRITA,
        "enviar": COMERCIAL,
        "aprovar": COMERCIAL,
        "recusar": COMERCIAL,
        "cancelar": COMERCIAL,
        "converter": ESCRITA,
        "historico": LEITURA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        data_inicio = params.get("data_inicio")
        if data_inicio:
            qs = qs.filter(data_hora__date__gte=data_inicio)
        data_fim = params.get("data_fim")
        if data_fim:
            qs = qs.filter(data_hora__date__lte=data_fim)
        validade_inicio = params.get("validade_inicio")
        if validade_inicio:
            qs = qs.filter(validade__gte=validade_inicio)
        validade_fim = params.get("validade_fim")
        if validade_fim:
            qs = qs.filter(validade__lte=validade_fim)
        return qs

    def perform_create(self, serializer):
        orcamento = serializer.save()
        if getattr(orcamento, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=orcamento,
            request=self.request,
            justificativa=self.justificativa(),
        )

    def _executar_transicao(self, request, pk, funcao):
        orcamento = self.get_object()
        anteriores = snapshot(orcamento)
        orcamento = funcao(
            orcamento_id=orcamento.pk,
            usuario=usuario_da_request(request),
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=orcamento,
            dados_anteriores=anteriores,
            justificativa=self.justificativa(),
            request=request,
        )
        return Response(self.get_serializer(orcamento).data)

    @action(detail=True, methods=["post"], url_path="enviar")
    def enviar(self, request, pk=None):
        observacao = (
            request.data.get("observacao", "")
            if hasattr(request.data, "get")
            else ""
        )
        return self._executar_transicao(
            request,
            pk,
            lambda **kwargs: services.enviar_orcamento(
                **kwargs, observacao=observacao
            ),
        )

    @action(detail=True, methods=["post"], url_path="aprovar")
    def aprovar(self, request, pk=None):
        observacao = (
            request.data.get("observacao", "")
            if hasattr(request.data, "get")
            else ""
        )
        return self._executar_transicao(
            request,
            pk,
            lambda **kwargs: services.aprovar_orcamento(
                **kwargs, observacao=observacao
            ),
        )

    @action(detail=True, methods=["post"], url_path="recusar")
    def recusar(self, request, pk=None):
        motivo = (
            request.data.get("motivo", "")
            if hasattr(request.data, "get")
            else ""
        )
        if not (motivo or "").strip():
            raise ValidationError(
                {"motivo": ["Informe o motivo da recusa."]}
            )
        return self._executar_transicao(
            request,
            pk,
            lambda **kwargs: services.recusar_orcamento(
                **kwargs, motivo=motivo
            ),
        )

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        motivo = (
            request.data.get("motivo", "")
            if hasattr(request.data, "get")
            else ""
        )
        return self._executar_transicao(
            request,
            pk,
            lambda **kwargs: services.cancelar_orcamento(
                **kwargs, motivo=motivo
            ),
        )

    @action(detail=True, methods=["post"], url_path="converter")
    def converter(self, request, pk=None):
        orcamento = self.get_object()
        dados = ConversaoOrcamentoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        anteriores = snapshot(orcamento)
        orcamento = services.converter_orcamento(
            orcamento_id=orcamento.pk,
            usuario=usuario_da_request(request),
            **dados.validated_data,
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=orcamento,
            dados_anteriores=anteriores,
            justificativa=self.justificativa(),
            request=request,
        )
        return Response(self.get_serializer(orcamento).data)

    @action(detail=True, methods=["get"], url_path="historico")
    def historico(self, request, pk=None):
        orcamento = self.get_object()
        qs = HistoricoOrcamento.objects.filter(orcamento=orcamento).order_by(
            "created_at"
        )
        return Response(HistoricoOrcamentoSerializer(qs, many=True).data)


class ServicoRealizadoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Serviços efetivamente executados, com valores fechados."""

    queryset = (
        ServicoRealizado.objects.select_related(
            "atendimento",
            "pet",
            "pet__tutor",
            "servico",
            "profissional",
            "desconto_autorizado_por",
            "orcamento_item",
        )
        .all()
    )
    serializer_class = ServicoRealizadoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "atendimento",
        "pet",
        "servico",
        "profissional",
        "orcamento_item",
    ]
    search_fields = [
        "pet__nome",
        "pet__tutor__nome",
        "servico__nome",
        "profissional__nome",
        "observacoes",
    ]
    ordering_fields = ["data_hora", "valor_total", "created_at"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "servico_realizado"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        data_inicio = params.get("data_inicio")
        if data_inicio:
            qs = qs.filter(data_hora__date__gte=data_inicio)
        data_fim = params.get("data_fim")
        if data_fim:
            qs = qs.filter(data_hora__date__lte=data_fim)
        return qs

    def perform_create(self, serializer):
        registro = serializer.save()
        if getattr(registro, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=registro,
            request=self.request,
            justificativa=self.justificativa(),
        )
