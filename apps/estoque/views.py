"""Views do catálogo de produtos e categorias.

Leitura liberada para admin, veterinário e recepção (a recepção precisa
consultar o catálogo). Escrita restrita a admin e veterinário.
"""

from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.base.views import AuditModelViewSetMixin

from . import services
from .models import (
    CategoriaProduto,
    Fornecedor,
    Inventario,
    ItemInventario,
    Lote,
    MovimentacaoEstoque,
    Produto,
)
from .serializers import (
    AjusteEstoqueSerializer,
    CategoriaProdutoSerializer,
    EntradaEstoqueSerializer,
    FornecedorSerializer,
    InventarioSerializer,
    ItemInventarioSerializer,
    LoteSerializer,
    MovimentacaoEstoqueSerializer,
    ProdutoSerializer,
    SaidaEstoqueSerializer,
)

LEITURA = ("admin", "veterinario", "recepcao")
ESCRITA = ("admin", "veterinario")


class CategoriaProdutoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """CRUD de categorias do catálogo."""

    queryset = CategoriaProduto.objects.all().order_by("nome")
    serializer_class = CategoriaProdutoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["tipo", "ativo"]
    search_fields = ["nome", "descricao"]
    ordering_fields = ["nome", "tipo", "created_at"]
    ordering = ["nome"]
    audit_entidade = "categoria_produto"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "ativas": LEITURA,
        "*": ESCRITA,
    }

    @action(detail=False, methods=["get"], url_path="ativas")
    def ativas(self, request):
        """Categorias ativas para os seletores do frontend."""
        qs = self.filter_queryset(self.get_queryset().filter(ativo=True))
        return Response(self.get_serializer(qs, many=True).data)

    def perform_destroy(self, instance):
        if Produto.objects.filter(categoria=instance).exists():
            raise ValidationError(
                {
                    "detail": (
                        "Não é possível excluir uma categoria que possui "
                        "produtos vinculados. Inative-a ou mova os produtos."
                    )
                }
            )
        return super().perform_destroy(instance)


class ProdutoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """CRUD do catálogo de produtos e medicamentos."""

    queryset = Produto.objects.select_related("categoria").all()
    serializer_class = ProdutoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "categoria",
        "categoria__tipo",
        "ativo",
        "tipo_estoque",
        "forma_farmaceutica",
        "unidade_medida",
        "controla_estoque",
        "requer_receita",
    ]
    search_fields = [
        "nome",
        "descricao",
        "fabricante",
        "apresentacao",
        "principio_ativo",
        "concentracao",
        "codigo_interno",
        "codigo_barras",
        "categoria__nome",
    ]
    ordering_fields = [
        "nome",
        "categoria__nome",
        "tipo_estoque",
        "codigo_interno",
        "created_at",
    ]
    ordering = ["nome"]
    audit_entidade = "produto"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "ativos": LEITURA,
        "medicamentos": LEITURA,
        "*": ESCRITA,
    }

    @action(detail=False, methods=["get"], url_path="ativos")
    def ativos(self, request):
        """Produtos ativos, respeitando os filtros da query string."""
        qs = self.filter_queryset(self.get_queryset().filter(ativo=True))
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="medicamentos")
    def medicamentos(self, request):
        """Medicamentos ativos para prescrição e administração clínica."""
        qs = self.filter_queryset(
            self.get_queryset().filter(
                ativo=True,
                categoria__tipo=CategoriaProduto.Tipo.MEDICAMENTO,
            )
        )
        return Response(self.get_serializer(qs, many=True).data)


def _param_bool(valor):
    return str(valor or "").lower() in {"1", "true", "t", "sim", "yes"}


class FornecedorViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """CRUD de fornecedores."""

    queryset = Fornecedor.objects.all().order_by("nome")
    serializer_class = FornecedorSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["ativo"]
    search_fields = ["nome", "razao_social", "cnpj", "email"]
    ordering_fields = ["nome", "created_at"]
    ordering = ["nome"]
    audit_entidade = "fornecedor"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "*": ESCRITA,
    }


class LoteViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """CRUD de lotes, com filtros de validade e saldo."""

    queryset = Lote.objects.select_related("produto", "fornecedor").all()
    serializer_class = LoteSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["produto", "fornecedor"]
    search_fields = ["numero_lote", "produto__nome", "produto__codigo_interno"]
    ordering_fields = [
        "data_validade",
        "quantidade_atual",
        "produto__nome",
        "created_at",
    ]
    ordering = ["data_validade", "-created_at"]
    audit_entidade = "lote"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "fefo": LEITURA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        tipo_estoque = params.get("tipo_estoque")
        if tipo_estoque:
            qs = qs.filter(produto__tipo_estoque=tipo_estoque)

        if _param_bool(params.get("com_saldo")):
            qs = qs.filter(quantidade_atual__gt=0)

        validade_ate = params.get("validade_ate")
        if validade_ate:
            qs = qs.filter(data_validade__lte=validade_ate)

        validade_de = params.get("validade_de")
        if validade_de:
            qs = qs.filter(data_validade__gte=validade_de)

        if _param_bool(params.get("vencidos")):
            qs = qs.filter(
                data_validade__lt=timezone.localdate(), quantidade_atual__gt=0
            )

        if _param_bool(params.get("vencendo")):
            hoje = timezone.localdate()
            qs = qs.filter(
                data_validade__gte=hoje,
                data_validade__lte=hoje + timedelta(
                    days=services.DIAS_ALERTA_VALIDADE
                ),
                quantidade_atual__gt=0,
            )
        return qs

    @action(detail=False, methods=["get"], url_path="fefo")
    def fefo(self, request):
        """Lotes com saldo em ordem FEFO para um produto."""
        produto_id = request.query_params.get("produto")
        if not produto_id:
            raise ValidationError({"produto": ["Informe o produto."]})
        qs = (
            self.get_queryset()
            .filter(produto_id=produto_id, quantidade_atual__gt=0)
            .exclude(data_validade__lt=timezone.localdate())
            .order_by(F("data_validade").asc(nulls_last=True), "created_at")
        )
        return Response(self.get_serializer(qs, many=True).data)

    def perform_destroy(self, instance):
        if instance.quantidade_atual and instance.quantidade_atual > 0:
            raise ValidationError(
                {"detail": "Não é possível excluir um lote com saldo em estoque."}
            )
        if instance.movimentacoes.exists():
            raise ValidationError(
                {"detail": "Não é possível excluir um lote que possui movimentações."}
            )
        if instance.itens_inventario.exists():
            raise ValidationError(
                {"detail": "Não é possível excluir um lote que participa de inventário."}
            )
        return super().perform_destroy(instance)


class MovimentacaoEstoqueViewSet(viewsets.ReadOnlyModelViewSet):
    """Histórico imutável de movimentações e registro de entradas/saídas."""

    queryset = (
        MovimentacaoEstoque.objects.select_related(
            "produto", "lote", "fornecedor", "atendimento", "atendimento__pet"
        )
        .all()
    )
    serializer_class = MovimentacaoEstoqueSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "produto",
        "lote",
        "tipo",
        "direcao",
        "atendimento",
        "fornecedor",
    ]
    search_fields = [
        "produto__nome",
        "produto__codigo_interno",
        "lote__numero_lote",
        "motivo",
        "documento_referencia",
    ]
    ordering_fields = ["data_hora", "quantidade", "created_at"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "movimentacao_estoque"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "entrada": ESCRITA,
        "saida": ESCRITA,
        "ajuste": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        tipo_estoque = params.get("tipo_estoque")
        if tipo_estoque:
            qs = qs.filter(produto__tipo_estoque=tipo_estoque)

        data_inicio = params.get("data_inicio")
        if data_inicio:
            qs = qs.filter(data_hora__date__gte=data_inicio)

        data_fim = params.get("data_fim")
        if data_fim:
            qs = qs.filter(data_hora__date__lte=data_fim)
        return qs

    @action(detail=False, methods=["post"], url_path="entrada")
    def entrada(self, request):
        serializer = EntradaEstoqueSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data
        movimentacao = services.registrar_entrada(
            usuario=request.user, **dados
        )
        return Response(
            MovimentacaoEstoqueSerializer(movimentacao).data, status=201
        )

    @action(detail=False, methods=["post"], url_path="saida")
    def saida(self, request):
        serializer = SaidaEstoqueSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data
        movimentacoes = services.registrar_saida(
            usuario=request.user, **dados
        )
        return Response(
            MovimentacaoEstoqueSerializer(movimentacoes, many=True).data,
            status=201,
        )

    @action(detail=False, methods=["post"], url_path="ajuste")
    def ajuste(self, request):
        serializer = AjusteEstoqueSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data
        movimentacao = services.registrar_ajuste(
            usuario=request.user, **dados
        )
        return Response(
            MovimentacaoEstoqueSerializer(movimentacao).data, status=201
        )


class InventarioViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Inventários de contagem física por tipo de estoque."""

    queryset = Inventario.objects.select_related("finalizado_por").all()
    serializer_class = InventarioSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.OrderingFilter,
    ]
    filterset_fields = ["tipo_estoque", "status"]
    ordering_fields = ["iniciado_em", "finalizado_em", "created_at"]
    ordering = ["-iniciado_em"]
    audit_entidade = "inventario"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "finalizar": ESCRITA,
        "cancelar": ESCRITA,
        "*": ESCRITA,
    }

    @action(detail=True, methods=["post"], url_path="finalizar")
    def finalizar(self, request, pk=None):
        inventario = services.finalizar_inventario(
            inventario_id=pk, usuario=request.user
        )
        return Response(self.get_serializer(inventario).data)

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        inventario = services.cancelar_inventario(
            inventario_id=pk, usuario=request.user
        )
        return Response(self.get_serializer(inventario).data)

    def perform_destroy(self, instance):
        if instance.status != Inventario.Status.CANCELADO:
            raise ValidationError(
                {
                    "detail": (
                        "Cancele o inventário antes de excluí-lo. "
                        "Inventários finalizados são mantidos para auditoria."
                    )
                }
            )
        return super().perform_destroy(instance)


class ItemInventarioViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Itens de contagem de um inventário aberto."""

    queryset = (
        ItemInventario.objects.select_related(
            "inventario", "lote", "lote__produto"
        )
        .all()
    )
    serializer_class = ItemInventarioSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["inventario", "lote", "lote__produto"]
    search_fields = ["lote__numero_lote", "lote__produto__nome"]
    ordering_fields = ["lote__produto__nome", "lote__data_validade", "diferenca"]
    ordering = ["lote__produto__nome", "lote__data_validade"]
    audit_entidade = "item_inventario"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "*": ESCRITA,
    }

    def perform_destroy(self, instance):
        if instance.inventario.status != Inventario.Status.ABERTO:
            raise ValidationError(
                {"detail": "Somente itens de inventários abertos podem ser excluídos."}
            )
        return super().perform_destroy(instance)


class EstoqueDashboardView(APIView):
    """Indicadores consolidados do estoque clínico e comercial."""

    role_policy = LEITURA

    def get(self, request):
        return Response(services.resumo_estoque())


class EstoqueAlertasView(APIView):
    """Alertas de estoque mínimo e de validade dos lotes."""

    role_policy = LEITURA

    def get(self, request):
        return Response(services.alertas_estoque())
