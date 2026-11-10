"""Views da internação veterinária.

A recepção pode consultar leitos, internados, evoluções, cuidados e
administrações. Somente admin/veterinário admitem, transferem, evoluem,
administram medicamentos e dão alta.
"""

from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.models import AuditLog
from apps.auditoria.services import registrar, snapshot, usuario_da_request
from apps.base.views import AuditModelViewSetMixin
from apps.prescricao.models import ItemPrescricao, Prescricao

from . import services
from .models import (
    AdministracaoMedicamentoInternacao,
    CuidadoInternacao,
    EvolucaoInternacao,
    Internacao,
    Leito,
    OcupacaoLeito,
)
from .serializers import (
    AdministracaoMedicamentoInternacaoSerializer,
    AltaInternacaoSerializer,
    CuidadoInternacaoSerializer,
    EvolucaoInternacaoSerializer,
    InternacaoResumoSerializer,
    InternacaoSerializer,
    LeitoSerializer,
    OcupacaoLeitoSerializer,
    PrescricaoPendenteSerializer,
    TransferenciaInternacaoSerializer,
)

LEITURA = ("admin", "veterinario", "recepcao")
ESCRITA = ("admin", "veterinario")


def leitos_queryset():
    """Leitos com contagem de ocupações abertas anotada."""
    return (
        Leito.objects.annotate(
            ocupados_count=Count(
                "ocupacoes",
                filter=Q(
                    ocupacoes__data_saida__isnull=True,
                    ocupacoes__is_deleted=False,
                ),
                distinct=True,
            )
        )
        .prefetch_related(
            Prefetch(
                "ocupacoes",
                queryset=OcupacaoLeito.objects.filter(
                    data_saida__isnull=True, is_deleted=False
                ).select_related(
                    "internacao__pet", "internacao__profissional_responsavel"
                ),
                to_attr="ocupacoes_abertas_list",
            )
        )
        .all()
    )


def internacoes_queryset():
    """Internações com relacionamentos e contadores para listagem."""
    return (
        Internacao.objects.select_related(
            "pet",
            "pet__tutor",
            "atendimento_origem",
            "prontuario",
            "leito",
            "profissional_responsavel",
            "profissional_alta",
        )
        .prefetch_related("prescricoes", "documentos")
        .annotate(
            evolucoes_count=Count(
                "evolucoes", filter=Q(evolucoes__is_deleted=False), distinct=True
            ),
            cuidados_count=Count(
                "cuidados", filter=Q(cuidados__is_deleted=False), distinct=True
            ),
            administracoes_count=Count(
                "administracoes",
                filter=Q(administracoes__is_deleted=False),
                distinct=True,
            ),
            ultima_evolucao_anotada=Max(
                "evolucoes__data_hora",
                filter=Q(evolucoes__is_deleted=False),
            ),
        )
        .all()
    )


class LeitoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Cadastro de leitos com disponibilidade derivada da ocupação."""

    queryset = leitos_queryset()
    serializer_class = LeitoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["tipo", "situacao"]
    search_fields = ["nome", "observacoes"]
    ordering_fields = ["nome", "tipo", "situacao", "capacidade", "created_at"]
    ordering = ["nome"]
    audit_entidade = "leito"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "update": ESCRITA,
        "partial_update": ESCRITA,
        "destroy": ESCRITA,
        "disponiveis": LEITURA,
        "historico": LEITURA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("disponivel") in ("1", "true", "True"):
            qs = qs.filter(situacao=Leito.Situacao.ATIVO)
        return qs

    @action(detail=False, methods=["get"], url_path="disponiveis")
    def disponiveis(self, request):
        """Lista apenas leitos ativos com vaga disponível."""
        qs = self.get_queryset().filter(situacao=Leito.Situacao.ATIVO)
        disponiveis = [leito for leito in qs if leito.disponivel]
        page = self.paginate_queryset(disponiveis)
        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data
            )
        return Response(self.get_serializer(disponiveis, many=True).data)

    @action(detail=True, methods=["get"], url_path="historico")
    def historico(self, request, pk=None):
        """Histórico completo de ocupações do leito."""
        leito = self.get_object()
        ocupacoes = (
            leito.ocupacoes.select_related(
                "internacao__pet", "internacao__pet__tutor"
            )
            .order_by("-data_entrada")
            .all()
        )
        return Response(OcupacaoLeitoSerializer(ocupacoes, many=True).data)


class OcupacaoLeitoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Histórico de ocupação de leitos, somente leitura."""

    queryset = OcupacaoLeito.objects.select_related(
        "leito", "internacao__pet", "internacao__pet__tutor"
    ).all()
    serializer_class = OcupacaoLeitoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["leito", "internacao"]
    search_fields = ["leito__nome", "internacao__pet__nome", "motivo_saida"]
    ordering_fields = ["data_entrada", "data_saida", "created_at"]
    ordering = ["-data_entrada"]
    role_policy = {"list": LEITURA, "retrieve": LEITURA, "*": ESCRITA}


class InternacaoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Admissão e acompanhamento do episódio de internação."""

    queryset = internacoes_queryset()
    serializer_class = InternacaoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["pet", "leito", "profissional_responsavel", "status", "estado_clinico"]
    search_fields = [
        "pet__nome",
        "pet__tutor__nome",
        "leito__nome",
        "profissional_responsavel__nome",
        "motivo_internacao",
        "diagnostico_inicial",
    ]
    ordering_fields = [
        "data_hora_entrada",
        "data_hora_alta",
        "estado_clinico",
        "status",
        "created_at",
    ]
    ordering = ["-data_hora_entrada"]
    audit_entidade = "internacao"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "update": ESCRITA,
        "partial_update": ESCRITA,
        "transferir": ESCRITA,
        "alta": ESCRITA,
        "evolucoes": LEITURA,
        "cuidados": LEITURA,
        "administracoes": LEITURA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("ativas") in ("1", "true", "True"):
            qs = qs.filter(status=Internacao.Status.INTERNADO)
        if params.get("data_inicio"):
            qs = qs.filter(data_hora_entrada__date__gte=params["data_inicio"])
        if params.get("data_fim"):
            qs = qs.filter(data_hora_entrada__date__lte=params["data_fim"])
        return qs

    def perform_create(self, serializer):
        internacao = serializer.save()
        if getattr(internacao, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=internacao,
            request=self.request,
            justificativa=self.justificativa(),
        )

    @action(detail=True, methods=["post"], url_path="transferir")
    def transferir(self, request, pk=None):
        internacao = self.get_object()
        dados = TransferenciaInternacaoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        anteriores = snapshot(internacao)
        internacao = services.transferir_internacao(
            internacao_id=internacao.pk,
            usuario=usuario_da_request(request),
            **dados.validated_data,
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=internacao,
            dados_anteriores=anteriores,
            justificativa=self.justificativa(),
            request=request,
        )
        return Response(self.get_serializer(internacao).data)

    @action(detail=True, methods=["post"], url_path="alta")
    def alta(self, request, pk=None):
        internacao = self.get_object()
        dados = AltaInternacaoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        anteriores = snapshot(internacao)
        internacao = services.dar_alta(
            internacao_id=internacao.pk,
            usuario=usuario_da_request(request),
            **dados.validated_data,
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=internacao,
            dados_anteriores=anteriores,
            justificativa=self.justificativa(),
            request=request,
        )
        return Response(self.get_serializer(internacao).data)

    @action(detail=True, methods=["get"], url_path="evolucoes")
    def evolucoes(self, request, pk=None):
        internacao = self.get_object()
        qs = internacao.evolucoes.select_related("profissional").order_by(
            "-data_hora", "-created_at"
        )
        return Response(EvolucaoInternacaoSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="cuidados")
    def cuidados(self, request, pk=None):
        internacao = self.get_object()
        qs = internacao.cuidados.select_related("profissional").order_by(
            "-data_hora", "-created_at"
        )
        return Response(CuidadoInternacaoSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="administracoes")
    def administracoes(self, request, pk=None):
        internacao = self.get_object()
        qs = internacao.administracoes.select_related(
            "pet",
            "produto",
            "lote",
            "profissional",
            "movimentacao",
            "estorno_movimentacao",
            "cancelada_por",
        ).order_by("-data_hora", "-created_at")
        return Response(
            AdministracaoMedicamentoInternacaoSerializer(qs, many=True).data
        )

    @action(detail=True, methods=["get"], url_path="resumo")
    def resumo(self, request, pk=None):
        """Resumo completo para a tela de detalhe/alta."""
        internacao = self.get_object()
        return Response(
            {
                "internacao": self.get_serializer(internacao).data,
                "ocupacoes": OcupacaoLeitoSerializer(
                    internacao.ocupacoes.select_related("leito").all(),
                    many=True,
                ).data,
                "evolucoes": EvolucaoInternacaoSerializer(
                    internacao.evolucoes.select_related("profissional").all(),
                    many=True,
                ).data,
                "cuidados": CuidadoInternacaoSerializer(
                    internacao.cuidados.select_related("profissional").all(),
                    many=True,
                ).data,
                "administracoes": AdministracaoMedicamentoInternacaoSerializer(
                    internacao.administracoes.select_related(
                        "produto", "lote", "profissional"
                    ).all(),
                    many=True,
                ).data,
            }
        )


class EvolucaoInternacaoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Evoluções clínicas imutáveis (sem update/destroy)."""

    queryset = EvolucaoInternacao.objects.select_related(
        "internacao__pet", "profissional"
    ).all()
    serializer_class = EvolucaoInternacaoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["internacao", "profissional"]
    search_fields = [
        "internacao__pet__nome",
        "evolucao_clinica",
        "observacoes",
        "intercorrencias",
        "profissional__nome",
    ]
    ordering_fields = ["data_hora", "created_at"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "evolucao_internacao"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("data_inicio"):
            qs = qs.filter(data_hora__date__gte=params["data_inicio"])
        if params.get("data_fim"):
            qs = qs.filter(data_hora__date__lte=params["data_fim"])
        return qs


class CuidadoInternacaoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Cuidados de rotina/enfermagem (sem update/destroy)."""

    queryset = CuidadoInternacao.objects.select_related(
        "internacao__pet", "profissional"
    ).all()
    serializer_class = CuidadoInternacaoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["internacao", "tipo", "profissional"]
    search_fields = [
        "internacao__pet__nome",
        "descricao",
        "observacoes",
        "profissional__nome",
    ]
    ordering_fields = ["data_hora", "tipo", "created_at"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "cuidado_internacao"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ESCRITA,
        "*": ESCRITA,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get("data_inicio"):
            qs = qs.filter(data_hora__date__gte=params["data_inicio"])
        if params.get("data_fim"):
            qs = qs.filter(data_hora__date__lte=params["data_fim"])
        return qs


class AdministracaoMedicamentoInternacaoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Medicações administradas na internação, com estoque rastreável."""

    queryset = AdministracaoMedicamentoInternacao.objects.select_related(
        "internacao",
        "internacao__pet",
        "pet",
        "item_prescricao",
        "prescricao",
        "produto",
        "lote",
        "profissional",
        "movimentacao",
        "estorno_movimentacao",
        "cancelada_por",
    ).all()
    serializer_class = AdministracaoMedicamentoInternacaoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "internacao",
        "pet",
        "item_prescricao",
        "prescricao",
        "produto",
        "lote",
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
    audit_entidade = "administracao_internacao"
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
        if params.get("data_inicio"):
            qs = qs.filter(data_hora__date__gte=params["data_inicio"])
        if params.get("data_fim"):
            qs = qs.filter(data_hora__date__lte=params["data_fim"])
        return qs

    def perform_create(self, serializer):
        administracao = serializer.save()
        if getattr(administracao, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=administracao,
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


class InternacaoCentralView(APIView):
    """Painel único da internação: leitos, internados e pendências."""

    role_policy = {"GET": LEITURA, "*": ESCRITA}

    def get(self, request):
        hoje = timezone.localdate()
        leitos = list(leitos_queryset().order_by("nome"))
        internados = list(
            internacoes_queryset()
            .filter(status=Internacao.Status.INTERNADO)
            .order_by("-data_hora_entrada")
        )
        ids = [internacao.pk for internacao in internados]

        administracoes_hoje = (
            AdministracaoMedicamentoInternacao.objects.filter(
                internacao__in=ids,
                data_hora__date=hoje,
                status=AdministracaoMedicamentoInternacao.Status.ATIVA,
            )
            .select_related("pet", "produto", "lote", "profissional")
            .order_by("-data_hora")[:50]
        )
        cuidados_recentes = (
            CuidadoInternacao.objects.filter(internacao__in=ids)
            .select_related("internacao__pet", "profissional")
            .order_by("-data_hora")[:30]
        )
        evolucoes_recentes = (
            EvolucaoInternacao.objects.filter(internacao__in=ids)
            .select_related("internacao__pet", "profissional")
            .order_by("-data_hora")[:30]
        )

        prescricoes = (
            Prescricao.objects.filter(
                pet_id__in=[internacao.pet_id for internacao in internados],
                status=Prescricao.Status.ATIVA,
            )
            .select_related("pet", "veterinario__profissional")
            .prefetch_related(
                Prefetch(
                    "itens",
                    queryset=ItemPrescricao.objects.select_related("produto"),
                ),
                Prefetch(
                    "administracoes_internacao",
                    queryset=AdministracaoMedicamentoInternacao.objects.filter(
                        internacao__in=ids,
                        status=AdministracaoMedicamentoInternacao.Status.ATIVA,
                    ),
                    to_attr="administracoes_periodo",
                ),
            )
            .order_by("-data_prescricao")
        )

        total_leitos = len([leito for leito in leitos if leito.situacao == Leito.Situacao.ATIVO])
        disponiveis = len([leito for leito in leitos if leito.disponivel])
        ocupados = sum(leito.ocupados for leito in leitos)

        return Response(
            {
                "resumo": {
                    "total_leitos": total_leitos,
                    "leitos_disponiveis": disponiveis,
                    "leitos_ocupados": ocupados,
                    "internados": len(internados),
                    "graves": len(
                        [
                            internacao
                            for internacao in internados
                            if internacao.estado_clinico
                            in (
                                Internacao.EstadoClinico.GRAVE,
                                Internacao.EstadoClinico.CRITICO,
                            )
                        ]
                    ),
                    "administracoes_hoje": len(administracoes_hoje),
                    "prescricoes_ativas": prescricoes.count(),
                },
                "leitos": LeitoSerializer(leitos, many=True).data,
                "internados": InternacaoResumoSerializer(
                    internados, many=True
                ).data,
                "prescricoes_pendentes": PrescricaoPendenteSerializer(
                    prescricoes, many=True
                ).data,
                "administracoes_hoje": AdministracaoMedicamentoInternacaoSerializer(
                    administracoes_hoje, many=True
                ).data,
                "cuidados_recentes": CuidadoInternacaoSerializer(
                    cuidados_recentes, many=True
                ).data,
                "evolucoes_recentes": EvolucaoInternacaoSerializer(
                    evolucoes_recentes, many=True
                ).data,
            }
        )
