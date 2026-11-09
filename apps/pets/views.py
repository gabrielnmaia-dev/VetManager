"""Views do app pets com filtros, busca e catálogos controlados."""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Especie, Raca, Pet, HistoricoResponsabilidadePet
from .serializers import (
    EspecieSerializer,
    RacaSerializer,
    PetSerializer,
    PetResumoSerializer,
    PetCreateSerializer,
    HistoricoResponsabilidadePetSerializer,
)
from apps.base.views import AuditModelViewSetMixin


class EspecieViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Catálogo de espécies: listagem, criação e edição."""

    queryset = Especie.objects.all().order_by("nome")
    serializer_class = EspecieSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["nome"]
    ordering_fields = ["nome", "criado_em"]
    ordering = ["nome"]
    audit_entidade = "especie"
    role_policy = ("admin", "veterinario", "recepcao")

    @action(detail=False, methods=["get"], url_path="ativas")
    def ativas(self, request):
        """Retorna apenas espécies ativas (para dropdowns do frontend)."""
        especies = self.get_queryset().filter(ativo=True)
        serializer = self.get_serializer(especies, many=True)
        return Response(serializer.data)


class RacaViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Catálogo de raças vinculado a espécies."""

    queryset = Raca.objects.select_related("especie").all().order_by("especie__nome", "nome")
    serializer_class = RacaSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["especie", "ativo"]
    search_fields = ["nome", "especie__nome"]
    ordering_fields = ["nome", "especie__nome", "criado_em"]
    ordering = ["especie__nome", "nome"]
    audit_entidade = "raca"
    role_policy = ("admin", "veterinario", "recepcao")

    def get_queryset(self):
        qs = super().get_queryset()
        especie_id = self.request.query_params.get("especie")
        if especie_id:
            qs = qs.filter(especie_id=especie_id)
        return qs

    @action(detail=False, methods=["get"], url_path="ativas")
    def ativas(self, request):
        """Retorna apenas raças ativas, opcionalmente filtradas por espécie."""
        qs = self.get_queryset().filter(ativo=True)
        especie_id = request.query_params.get("especie")
        if especie_id:
            qs = qs.filter(especie_id=especie_id)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class PetViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Cadastro completo de pets com catálogos controlados."""

    queryset = Pet.objects.select_related("tutor", "especie", "raca").all()
    serializer_class = PetSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = [
        "tutor",
        "especie",
        "raca",
        "sexo",
        "castrado",
        "vermifugado",
        "microchip",
    ]
    search_fields = ["nome", "tutor__nome", "especie__nome", "raca__nome", "cor"]
    ordering_fields = ["nome", "especie__nome", "data_nascimento", "idade", "criado_em"]
    ordering = ["nome"]
    audit_entidade = "pet"
    role_policy = ("admin", "veterinario", "recepcao")

    def get_queryset(self):
        qs = super().get_queryset()
        tutor_id = self.request.query_params.get("tutor")
        if tutor_id:
            qs = qs.filter(tutor_id=tutor_id)
        especie_id = self.request.query_params.get("especie")
        if especie_id:
            qs = qs.filter(especie_id=especie_id)
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return PetCreateSerializer
        return super().get_serializer_class()

    @action(detail=True, methods=["get"], url_path="historico-responsaveis")
    def historico_responsaveis(self, request, pk=None):
        """Retorna o histórico de troca de responsável do pet."""
        pet = self.get_object()
        historico = pet.historico_responsaveis.all().order_by("-data_inicio")
        serializer = HistoricoResponsabilidadePetSerializer(historico, many=True)
        return Response(serializer.data)


class HistoricoResponsabilidadePetViewSet(
    AuditModelViewSetMixin, viewsets.ReadOnlyModelViewSet
):
    """Histórico de responsabilidade: somente leitura (audit trail)."""

    queryset = (
        HistoricoResponsabilidadePet.objects.select_related("pet", "tutor")
        .all()
        .order_by("-data_inicio")
    )
    serializer_class = HistoricoResponsabilidadePetSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["pet", "tutor"]
    ordering_fields = ["data_inicio", "data_fim"]
    ordering = ["-data_inicio"]
    audit_entidade = "historico_responsabilidade_pet"
    role_policy = ("admin", "veterinario", "recepcao")
