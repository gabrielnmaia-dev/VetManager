"""Views do catálogo de produtos e categorias.

Leitura liberada para admin, veterinário e recepção (a recepção precisa
consultar o catálogo). Escrita restrita a admin e veterinário.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.base.views import AuditModelViewSetMixin

from .models import CategoriaProduto, Produto
from .serializers import CategoriaProdutoSerializer, ProdutoSerializer

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
