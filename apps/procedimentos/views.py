"""Views do catálogo e da execução de procedimentos.

A recepção pode consultar catálogo e histórico (apoio ao tutor), mas somente
admin/veterinário cadastram procedimentos, registram execuções e cancelam.
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
from .models import (
    CategoriaProcedimento,
    ExecucaoProcedimento,
    MaterialPrevistoProcedimento,
    MaterialUtilizadoProcedimento,
    Procedimento,
)
from .serializers import (
    CategoriaProcedimentoSerializer,
    ExecucaoProcedimentoSerializer,
    ProcedimentoSerializer,
)

LEITURA = ("admin", "veterinario", "recepcao")
ESCRITA = ("admin", "veterinario")


class CategoriaProcedimentoViewSet(
    AuditModelViewSetMixin, viewsets.ModelViewSet
):
    """Catálogo de categorias de procedimento."""

    queryset = CategoriaProcedimento.objects.all()
    serializer_class = CategoriaProcedimentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["ativo"]
    search_fields = ["nome", "descricao"]
    ordering_fields = ["nome", "ativo", "created_at"]
    ordering = ["nome"]
    audit_entidade = "categoria_procedimento"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "update": ESCRITA,
        "partial_update": ESCRITA,
        "destroy": ESCRITA,
        "*": ESCRITA,
    }


class ProcedimentoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Catálogo de procedimentos, com materiais previstos aninhados."""

    queryset = (
        Procedimento.objects.select_related("categoria")
        .prefetch_related(
            Prefetch(
                "materiais_previstos",
                queryset=MaterialPrevistoProcedimento.objects.select_related(
                    "produto"
                ),
            )
        )
        .all()
    )
    serializer_class = ProcedimentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["categoria", "tipo", "ativo"]
    search_fields = ["nome", "descricao", "categoria__nome"]
    ordering_fields = ["nome", "tipo", "duracao_estimada_minutos", "created_at"]
    ordering = ["nome"]
    audit_entidade = "procedimento"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "update": ESCRITA,
        "partial_update": ESCRITA,
        "destroy": ESCRITA,
        "*": ESCRITA,
    }


class ExecucaoProcedimentoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Execuções de procedimentos; a criação consome materiais do estoque."""

    queryset = (
        ExecucaoProcedimento.objects.select_related(
            "pet",
            "pet__tutor",
            "atendimento",
            "procedimento",
            "profissional",
            "cancelada_por",
        )
        .prefetch_related(
            "equipe",
            Prefetch(
                "materiais",
                queryset=MaterialUtilizadoProcedimento.objects.select_related(
                    "produto", "lote", "movimentacao", "estorno_movimentacao"
                ),
            ),
        )
        .all()
    )
    serializer_class = ExecucaoProcedimentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "pet",
        "atendimento",
        "procedimento",
        "profissional",
        "status",
    ]
    search_fields = [
        "pet__nome",
        "pet__tutor__nome",
        "procedimento__nome",
        "profissional__nome",
        "resultado",
        "intercorrencias",
    ]
    ordering_fields = ["data_hora", "created_at", "status"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "execucao_procedimento"
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
        """Não duplica auditoria quando a chave de idempotência repete."""
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
        execucao = self.get_object()
        anteriores = snapshot(execucao)
        motivo = request.data.get("motivo", "") if hasattr(request.data, "get") else ""
        execucao = services.cancelar_execucao(
            execucao_id=execucao.pk,
            motivo=motivo,
            usuario=usuario_da_request(request),
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=execucao,
            dados_anteriores=anteriores,
            justificativa=motivo,
            request=request,
        )
        return Response(self.get_serializer(execucao).data)
