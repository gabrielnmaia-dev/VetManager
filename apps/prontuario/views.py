from datetime import timedelta

from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.base.views import AuditModelViewSetMixin
from .models import Prontuario, Vacina
from .serializers import ProntuarioSerializer, VacinaSerializer


class ProntuarioViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    queryset = Prontuario.objects.select_related(
        "pet", "veterinario__profissional"
    ).prefetch_related(
        # Evita N+1 ao serializar as vacinas aninhadas.
        Prefetch(
            "vacinas",
            queryset=Vacina.objects.select_related(
                "pet__tutor", "veterinario__profissional"
            ),
        )
    ).all()
    serializer_class = ProntuarioSerializer
    # Acesso restrito a admin/veterinário (RoleBasedPermission, em base.py).
    role_policy = ("admin", "veterinario")
    filter_backends = [filters.SearchFilter]
    search_fields = ["pet__nome", "diagnostico"]
    audit_entidade = "prontuario"
    audit_exclude = ("observacoes", "prescricao")  # dados sensíveis omitidos do snapshot padrão

    def get_queryset(self):
        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    # Obs.: o cache_page que existia aqui foi removido. Ele devolvia a
    # resposta em cache antes da checagem de grupo (que ficava no
    # get_queryset), vazando prontuários para qualquer usuário logado,
    # e mostrava dados desatualizados por 5 min após criar/editar.


class VacinaViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Registro de vacinas por animal.

    A recepção pode consultar o histórico (para responder ao tutor), mas só
    admin/veterinário criam, editam ou excluem registros clínicos.
    """

    queryset = Vacina.objects.select_related(
        "pet__tutor", "prontuario", "veterinario__profissional"
    ).all()
    serializer_class = VacinaSerializer
    role_policy = {
        "list": ("admin", "veterinario", "recepcao"),
        "retrieve": ("admin", "veterinario", "recepcao"),
        "resumo": ("admin", "veterinario", "recepcao"),
        "create": ("admin", "veterinario"),
        "update": ("admin", "veterinario"),
        "partial_update": ("admin", "veterinario"),
        "destroy": ("admin", "veterinario"),
        "*": ("admin",),
    }
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["pet", "veterinario", "via_aplicacao"]
    search_fields = [
        "nome_vacina",
        "pet__nome",
        "pet__tutor__nome",
        "lote",
        "fabricante",
    ]
    ordering_fields = [
        "data_aplicacao",
        "data_retorno",
        "nome_vacina",
        "criado_em",
    ]
    ordering = ["-data_aplicacao", "-id"]
    audit_entidade = "vacina"

    def _queryset_base(self):
        """Filtros de animal e período, sem a situação calculada."""
        qs = super().get_queryset()

        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)

        # Intervalo por data de aplicação.
        data_inicio = self.request.query_params.get("data_inicio")
        data_fim = self.request.query_params.get("data_fim")
        if data_inicio:
            qs = qs.filter(data_aplicacao__gte=data_inicio)
        if data_fim:
            qs = qs.filter(data_aplicacao__lte=data_fim)

        return qs

    def get_queryset(self):
        qs = self._queryset_base()

        # Filtro por situação calculada (não é campo do banco).
        situacao = self.request.query_params.get("situacao")
        hoje = timezone.localdate()
        limite = hoje + timedelta(days=Vacina.DIAS_ALERTA_RETORNO)
        if situacao == Vacina.Situacao.ATRASADA:
            qs = qs.filter(data_retorno__lt=hoje)
        elif situacao == Vacina.Situacao.PROXIMA:
            qs = qs.filter(
                data_retorno__gte=hoje, data_retorno__lte=limite
            )
        elif situacao == Vacina.Situacao.EM_DIA:
            qs = qs.filter(data_retorno__gt=limite)
        elif situacao == Vacina.Situacao.SEM_RETORNO:
            qs = qs.filter(data_retorno__isnull=True)

        return qs

    @action(detail=False, methods=["get"])
    def resumo(self, request):
        """Contagem por situação, respeitando animal e período.

        Não aplica o filtro ``situacao`` para que os cartões mostrem sempre
        o panorama completo do animal selecionado.
        """
        hoje = timezone.localdate()
        limite = hoje + timedelta(days=Vacina.DIAS_ALERTA_RETORNO)
        agregado = self._queryset_base().aggregate(
            total=Count("id"),
            em_dia=Count(
                "id", filter=Q(data_retorno__gt=limite)
            ),
            proxima=Count(
                "id",
                filter=Q(data_retorno__gte=hoje, data_retorno__lte=limite),
            ),
            atrasada=Count("id", filter=Q(data_retorno__lt=hoje)),
            sem_retorno=Count("id", filter=Q(data_retorno__isnull=True)),
        )
        return Response(agregado)
