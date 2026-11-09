"""Views do app atendimentos com suporte a agenda, salas, conflitos e status."""

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.base.views import AuditModelViewSetMixin

from .models import Atendimento
from .serializers import (
    AtendimentoCancelarSerializer,
    AtendimentoConfirmarSerializer,
    AtendimentoFaltouSerializer,
    AtendimentoRapidoResponseSerializer,
    AtendimentoRapidoSerializer,
    AtendimentoReagendarSerializer,
    AtendimentoSerializer,
)
from .services import (
    cancelar_atendimento,
    confirmar_atendimento,
    marcar_faltou,
    reagendar_atendimento,
    realizar_atendimento,
)


class AtendimentoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """ViewSet de atendimentos com ações de status e validação de conflito."""

    role_policy = {
        "list": ("admin", "veterinario", "recepcao"),
        "retrieve": ("admin", "veterinario", "recepcao"),
        "create": ("admin", "veterinario", "recepcao"),
        "rapido": ("admin", "veterinario", "recepcao"),
        "update": ("admin", "veterinario"),
        "partial_update": ("admin", "veterinario"),
        "destroy": ("admin",),
        "confirmar": ("admin", "veterinario", "recepcao"),
        "cancelar": ("admin", "veterinario", "recepcao"),
        "reagendar": ("admin", "veterinario", "recepcao"),
        "faltou": ("admin", "veterinario"),
        "realizar": ("admin", "veterinario"),
        "*": ("admin",),
    }
    queryset = Atendimento.objects.select_related(
        "pet", "pet__tutor", "profissional", "sala"
    ).all()
    serializer_class = AtendimentoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = [
        "taxidog",
        "profissional",
        "sala",
        "status",
        "tipo_servico",
    ]
    search_fields = [
        "pet__nome",
        "pet__tutor__nome",
        "profissional__nome",
        "nome_profissional",
    ]
    audit_entidade = "atendimento"

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        pet_id = params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)

        profissional_id = params.get("profissional")
        if profissional_id:
            qs = qs.filter(profissional_id=profissional_id)

        sala_id = params.get("sala")
        if sala_id:
            qs = qs.filter(sala_id=sala_id)

        status_param = params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        tipo_servico = params.get("tipo_servico")
        if tipo_servico:
            qs = qs.filter(tipo_servico=tipo_servico)

        data_inicio = params.get("data_inicio")
        data_fim = params.get("data_fim")
        if data_inicio:
            qs = qs.filter(data_hora_inicio__date__gte=data_inicio)
        if data_fim:
            qs = qs.filter(data_hora_inicio__date__lte=data_fim)

        return qs

    def get_serializer_class(self):
        if self.action == "rapido":
            return AtendimentoRapidoSerializer
        return super().get_serializer_class()

    # ------------------------------------------------------------------
    # Ações de status (confirmar / cancelar / reagendar / faltou / realizar)
    # ------------------------------------------------------------------

    @extend_schema(
        request=AtendimentoConfirmarSerializer,
        responses={200: AtendimentoSerializer},
        summary="Confirmar atendimento agendado.",
    )
    @action(detail=True, methods=["post"], url_path="confirmar")
    def confirmar(self, request, pk=None):
        atendimento = self.get_object()
        serializer = AtendimentoConfirmarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        atendimento = confirmar_atendimento(
            atendimento,
            user=request.user,
            justificativa=serializer.validated_data.get("justificativa", ""),
        )
        return Response(AtendimentoSerializer(atendimento).data)

    @extend_schema(
        request=AtendimentoCancelarSerializer,
        responses={200: AtendimentoSerializer},
        summary="Cancelar atendimento com motivo.",
    )
    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        atendimento = self.get_object()
        serializer = AtendimentoCancelarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        atendimento = cancelar_atendimento(
            atendimento,
            user=request.user,
            motivo=serializer.validated_data["motivo"],
        )
        return Response(AtendimentoSerializer(atendimento).data)

    @extend_schema(
        request=AtendimentoReagendarSerializer,
        responses={200: AtendimentoSerializer},
        summary="Reagendar atendimento para novo horário/sala.",
    )
    @action(detail=True, methods=["post"], url_path="reagendar")
    def reagendar(self, request, pk=None):
        atendimento = self.get_object()
        serializer = AtendimentoReagendarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        atendimento = reagendar_atendimento(
            atendimento,
            user=request.user,
            nova_data_hora_inicio=serializer.validated_data[
                "data_hora_inicio"
            ],
            nova_duracao_minutos=serializer.validated_data.get(
                "duracao_minutos"
            ),
            nova_sala=serializer.validated_data.get("sala"),
            justificativa=serializer.validated_data.get("justificativa", ""),
        )
        return Response(AtendimentoSerializer(atendimento).data)

    @extend_schema(
        request=AtendimentoFaltouSerializer,
        responses={200: AtendimentoSerializer},
        summary="Marcar atendimento como no-show (faltou).",
    )
    @action(detail=True, methods=["post"], url_path="faltou")
    def faltou(self, request, pk=None):
        atendimento = self.get_object()
        serializer = AtendimentoFaltouSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        atendimento = marcar_faltou(
            atendimento,
            user=request.user,
            justificativa=serializer.validated_data.get("justificativa", ""),
        )
        return Response(AtendimentoSerializer(atendimento).data)

    @extend_schema(
        responses={200: AtendimentoSerializer},
        summary="Marcar atendimento como realizado.",
    )
    @action(detail=True, methods=["post"], url_path="realizar")
    def realizar(self, request, pk=None):
        atendimento = self.get_object()
        atendimento = realizar_atendimento(atendimento, user=request.user)
        return Response(AtendimentoSerializer(atendimento).data)

    @extend_schema(
        operation_id="atendimento_rapido_create",
        summary="Criar atendimento rápido (tutor + pet em uma chamada).",
        request=AtendimentoRapidoSerializer,
        responses={201: AtendimentoRapidoResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="rapido")
    def rapido(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        atendimento = serializer.save()
        return Response(
            AtendimentoRapidoResponseSerializer(atendimento).data,
            status=status.HTTP_201_CREATED,
        )
