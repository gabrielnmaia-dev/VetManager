"""Views de prescrição e administração de medicamentos.

A recepção pode consultar prescrições e administrações (apoio ao tutor), mas
somente admin/veterinário criam, administram e cancelam.
"""

from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditoria.models import AuditLog
from apps.auditoria.services import registrar, snapshot, usuario_da_request
from apps.base.views import AuditModelViewSetMixin

from . import services
from .models import AdministracaoMedicamento, ItemPrescricao, Prescricao
from .serializers import (
    AdministracaoMedicamentoSerializer,
    PrescricaoSerializer,
)

LEITURA = ("admin", "veterinario", "recepcao")
ESCRITA = ("admin", "veterinario")


class PrescricaoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Prescrições estruturadas vinculadas ao prontuário/atendimento."""

    queryset = (
        Prescricao.objects.select_related(
            "prontuario",
            "atendimento",
            "pet",
            "pet__tutor",
            "veterinario__profissional",
            "cancelada_por",
        )
        .prefetch_related(
            Prefetch(
                "itens",
                queryset=ItemPrescricao.objects.select_related("produto"),
            ),
            Prefetch(
                "administracoes",
                queryset=AdministracaoMedicamento.objects.select_related(
                    "pet", "produto", "lote", "profissional"
                ),
            ),
        )
        .all()
    )
    serializer_class = PrescricaoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "pet",
        "veterinario",
        "atendimento",
        "prontuario",
        "status",
    ]
    search_fields = [
        "pet__nome",
        "pet__tutor__nome",
        "veterinario__profissional__nome",
        "itens__produto__nome",
        "itens__produto__principio_ativo",
    ]
    ordering_fields = ["data_prescricao", "created_at", "status"]
    ordering = ["-data_prescricao", "-created_at"]
    audit_entidade = "prescricao"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "cancelar": ESCRITA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        # A busca inclui medicamentos dos itens (relação reversa); DISTINCT
        # evita que uma prescrição com dois itens apareça duas vezes.
        if self.request.query_params.get("search"):
            qs = qs.distinct()
        return qs

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        prescricao = self.get_object()
        anteriores = snapshot(prescricao)
        motivo = request.data.get("motivo", "") if hasattr(request.data, "get") else ""
        prescricao = services.cancelar_prescricao(
            prescricao_id=prescricao.pk,
            motivo=motivo,
            usuario=usuario_da_request(request),
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=prescricao,
            dados_anteriores=anteriores,
            justificativa=motivo,
            request=request,
        )
        return Response(self.get_serializer(prescricao).data)


class AdministracaoMedicamentoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Administrações clínicas; cada criação baixa um lote no estoque."""

    queryset = (
        AdministracaoMedicamento.objects.select_related(
            "item_prescricao",
            "prescricao",
            "pet",
            "produto",
            "lote",
            "atendimento",
            "atendimento__pet",
            "profissional",
            "movimentacao",
            "estorno_movimentacao",
            "cancelada_por",
        )
        .all()
    )
    serializer_class = AdministracaoMedicamentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "item_prescricao",
        "prescricao",
        "pet",
        "produto",
        "lote",
        "atendimento",
        "profissional",
        "status",
    ]
    search_fields = [
        "pet__nome",
        "pet__tutor__nome",
        "produto__nome",
        "produto__principio_ativo",
        "lote__numero_lote",
        "profissional__nome",
        "motivo_cancelamento",
    ]
    ordering_fields = ["data_hora", "quantidade", "created_at"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "administracao_medicamento"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "cancelar": ESCRITA,
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
        """Evita auditoria duplicada quando a chave de idempotência repete."""
        instance = serializer.save()
        if getattr(instance, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=instance,
            request=self.request,
            justificativa=self.justificativa(),
        )

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        administracao = self.get_object()
        anteriores = snapshot(administracao)
        motivo = request.data.get("motivo", "") if hasattr(request.data, "get") else ""
        administracao = services.cancelar_administracao(
            administracao_id=administracao.pk,
            motivo=motivo,
            usuario=usuario_da_request(request),
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=administracao,
            dados_anteriores=anteriores,
            justificativa=motivo,
            request=request,
        )
        return Response(self.get_serializer(administracao).data)
