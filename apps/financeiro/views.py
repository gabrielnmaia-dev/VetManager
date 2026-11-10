"""Views financeiras: contas, pagamentos, caixa e relatórios."""

from datetime import date

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.models import AuditLog
from apps.auditoria.services import registrar, snapshot, usuario_da_request
from apps.base.views import AuditModelViewSetMixin

from . import relatorios, services
from .models import (
    Caixa,
    ContaReceber,
    FormaPagamento,
    HistoricoContaReceber,
    MovimentacaoCaixa,
    Pagamento,
    ParcelaContaReceber,
)
from .serializers import (
    CaixaSerializer,
    ContaReceberSerializer,
    EstornoPagamentoSerializer,
    FechamentoCaixaSerializer,
    FormaPagamentoSerializer,
    HistoricoContaReceberSerializer,
    MovimentacaoCaixaSerializer,
    PagamentoSerializer,
    ParcelaContaReceberSerializer,
)

ADMIN = ("admin",)
GESTAO = ("admin", "recepcao")
LEITURA = ("admin", "veterinario", "recepcao")


def _data_param(request, nome):
    valor = request.query_params.get(nome)
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({nome: ["Informe uma data no formato AAAA-MM-DD."]})


def _bool_param(request, nome):
    valor = request.query_params.get(nome)
    if valor is None or valor == "":
        return None
    return valor.lower() in {"1", "true", "sim", "yes"}


class FormaPagamentoViewSet(
    AuditModelViewSetMixin, viewsets.ModelViewSet
):
    queryset = FormaPagamento.objects.all()
    serializer_class = FormaPagamentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["tipo", "ativo", "permite_parcelamento"]
    search_fields = ["nome", "observacoes"]
    ordering_fields = ["nome", "tipo", "ativo", "created_at"]
    ordering = ["nome"]
    audit_entidade = "forma_pagamento"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": ADMIN,
        "update": ADMIN,
        "partial_update": ADMIN,
        "destroy": ADMIN,
        "*": ADMIN,
    }


class ContaReceberViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        ContaReceber.objects.select_related("tutor", "atendimento")
        .prefetch_related("parcelas", "historico")
        .all()
    )
    serializer_class = ContaReceberSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["tutor", "atendimento"]
    search_fields = ["descricao", "tutor__nome", "observacoes"]
    ordering_fields = [
        "data_emissao",
        "vencimento",
        "valor",
        "saldo",
        "status",
        "created_at",
    ]
    ordering = ["-data_emissao", "-created_at"]
    audit_entidade = "conta_receber"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": GESTAO,
        "cancelar": ADMIN,
        "historico": LEITURA,
        "*": ADMIN,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        status_param = params.get("status")
        if status_param == "vencida":
            qs = qs.filter(
                status__in=[
                    ContaReceber.Status.ABERTA,
                    ContaReceber.Status.PARCIAL,
                ],
                saldo__gt=0,
                vencimento__lt=timezone.localdate(),
            )
        elif status_param:
            qs = qs.filter(status=status_param)

        vencida = _bool_param(self.request, "vencida")
        if vencida:
            qs = qs.filter(
                status__in=[
                    ContaReceber.Status.ABERTA,
                    ContaReceber.Status.PARCIAL,
                ],
                saldo__gt=0,
                vencimento__lt=timezone.localdate(),
            )
        vencimento_inicio = _data_param(self.request, "vencimento_inicio")
        if vencimento_inicio:
            qs = qs.filter(vencimento__gte=vencimento_inicio)
        vencimento_fim = _data_param(self.request, "vencimento_fim")
        if vencimento_fim:
            qs = qs.filter(vencimento__lte=vencimento_fim)
        emissao_inicio = _data_param(self.request, "data_inicio")
        if emissao_inicio:
            qs = qs.filter(data_emissao__gte=emissao_inicio)
        emissao_fim = _data_param(self.request, "data_fim")
        if emissao_fim:
            qs = qs.filter(data_emissao__lte=emissao_fim)
        return qs

    def perform_create(self, serializer):
        conta = serializer.save()
        if getattr(conta, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=conta,
            request=self.request,
            justificativa=self.justificativa(),
        )

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        conta = self.get_object()
        anteriores = snapshot(conta)
        motivo = request.data.get("motivo", "") if hasattr(request.data, "get") else ""
        conta = services.cancelar_conta_receber(
            conta_id=conta.pk,
            motivo=motivo,
            usuario=usuario_da_request(request),
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=conta,
            dados_anteriores=anteriores,
            justificativa=motivo,
            request=request,
        )
        return Response(self.get_serializer(conta).data)

    @action(detail=True, methods=["get"], url_path="historico")
    def historico(self, request, pk=None):
        conta = self.get_object()
        qs = HistoricoContaReceber.objects.filter(conta=conta).order_by(
            "created_at"
        )
        return Response(HistoricoContaReceberSerializer(qs, many=True).data)


class ParcelaContaReceberViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ParcelaContaReceber.objects.select_related("conta", "conta__tutor")
    serializer_class = ParcelaContaReceberSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["conta", "status"]
    ordering_fields = ["vencimento", "numero", "valor", "saldo"]
    ordering = ["vencimento", "numero"]
    role_policy = {"list": LEITURA, "retrieve": LEITURA, "*": ADMIN}

    def get_queryset(self):
        qs = super().get_queryset()
        vencida = _bool_param(self.request, "vencida")
        if vencida:
            qs = qs.filter(
                status__in=[
                    ParcelaContaReceber.Status.ABERTA,
                    ParcelaContaReceber.Status.PARCIAL,
                ],
                saldo__gt=0,
                vencimento__lt=timezone.localdate(),
            )
        vencimento_inicio = _data_param(self.request, "vencimento_inicio")
        if vencimento_inicio:
            qs = qs.filter(vencimento__gte=vencimento_inicio)
        vencimento_fim = _data_param(self.request, "vencimento_fim")
        if vencimento_fim:
            qs = qs.filter(vencimento__lte=vencimento_fim)
        return qs


class PagamentoViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        Pagamento.objects.select_related(
            "conta",
            "conta__tutor",
            "parcela",
            "forma_pagamento",
            "caixa",
            "estornado_por",
        )
        .prefetch_related("aplicacoes", "aplicacoes__parcela")
        .all()
    )
    serializer_class = PagamentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["conta", "parcela", "forma_pagamento", "status", "caixa"]
    search_fields = ["conta__descricao", "conta__tutor__nome", "observacoes"]
    ordering_fields = ["data_hora", "valor", "status", "created_at"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "pagamento"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": GESTAO,
        "estornar": ADMIN,
        "*": ADMIN,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        data_inicio = _data_param(self.request, "data_inicio")
        if data_inicio:
            qs = qs.filter(data_hora__date__gte=data_inicio)
        data_fim = _data_param(self.request, "data_fim")
        if data_fim:
            qs = qs.filter(data_hora__date__lte=data_fim)
        return qs

    def perform_create(self, serializer):
        pagamento = serializer.save()
        if getattr(pagamento, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=pagamento,
            request=self.request,
            justificativa=self.justificativa(),
        )

    @action(detail=True, methods=["post"], url_path="estornar")
    def estornar(self, request, pk=None):
        pagamento = self.get_object()
        dados = EstornoPagamentoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        anteriores = snapshot(pagamento)
        pagamento = services.estornar_pagamento(
            pagamento_id=pagamento.pk,
            motivo=dados.validated_data["motivo"],
            usuario=usuario_da_request(request),
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=pagamento,
            dados_anteriores=anteriores,
            justificativa=dados.validated_data["motivo"],
            request=request,
        )
        return Response(self.get_serializer(pagamento).data)


class CaixaViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Caixa.objects.select_related(
        "usuario_abertura", "usuario_fechamento"
    ).all()
    serializer_class = CaixaSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["status"]
    search_fields = ["descricao", "observacoes", "observacoes_fechamento"]
    ordering_fields = ["data_abertura", "data_fechamento", "status", "created_at"]
    ordering = ["-data_abertura", "-created_at"]
    audit_entidade = "caixa"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": GESTAO,
        "fechar": GESTAO,
        "movimentacoes": LEITURA,
        "*": ADMIN,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        data_inicio = _data_param(self.request, "data_inicio")
        if data_inicio:
            qs = qs.filter(data_abertura__date__gte=data_inicio)
        data_fim = _data_param(self.request, "data_fim")
        if data_fim:
            qs = qs.filter(data_abertura__date__lte=data_fim)
        return qs

    def perform_create(self, serializer):
        caixa = serializer.save()
        if getattr(caixa, "criada_agora", True) is False:
            return
        registrar(
            usuario=usuario_da_request(self.request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=caixa,
            request=self.request,
            justificativa=self.justificativa(),
        )

    @action(detail=True, methods=["post"], url_path="fechar")
    def fechar(self, request, pk=None):
        caixa = self.get_object()
        dados = FechamentoCaixaSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        anteriores = snapshot(caixa)
        caixa = services.fechar_caixa(
            caixa_id=caixa.pk,
            usuario=usuario_da_request(request),
            **dados.validated_data,
        )
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=caixa,
            dados_anteriores=anteriores,
            justificativa=dados.validated_data.get("observacoes", ""),
            request=request,
        )
        return Response(self.get_serializer(caixa).data)

    @action(detail=True, methods=["get"], url_path="movimentacoes")
    def movimentacoes(self, request, pk=None):
        caixa = self.get_object()
        qs = caixa.movimentacoes.select_related(
            "forma_pagamento", "pagamento", "created_by"
        ).order_by("-data_hora", "-created_at")
        return Response(MovimentacaoCaixaSerializer(qs, many=True).data)


class MovimentacaoCaixaViewSet(
    AuditModelViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = MovimentacaoCaixa.objects.select_related(
        "caixa", "forma_pagamento", "pagamento", "created_by"
    ).all()
    serializer_class = MovimentacaoCaixaSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["caixa", "tipo", "forma_pagamento"]
    search_fields = ["descricao", "caixa__descricao"]
    ordering_fields = ["data_hora", "valor", "tipo", "created_at"]
    ordering = ["-data_hora", "-created_at"]
    audit_entidade = "movimentacao_caixa"
    role_policy = {
        "list": LEITURA,
        "retrieve": LEITURA,
        "create": GESTAO,
        "*": ADMIN,
    }

    def get_queryset(self):
        qs = super().get_queryset()
        data_inicio = _data_param(self.request, "data_inicio")
        if data_inicio:
            qs = qs.filter(data_hora__date__gte=data_inicio)
        data_fim = _data_param(self.request, "data_fim")
        if data_fim:
            qs = qs.filter(data_hora__date__lte=data_fim)
        return qs

    def perform_create(self, serializer):
        tipo = serializer.validated_data.get("tipo")
        user = usuario_da_request(self.request)
        if (
            tipo == MovimentacaoCaixa.Tipo.AJUSTE
            and not getattr(user, "is_superuser", False)
            and not user.groups.filter(name="admin").exists()
        ):
            raise PermissionDenied("Somente administradores podem registrar ajustes.")
        movimentacao = serializer.save()
        if getattr(movimentacao, "criada_agora", True) is False:
            return
        registrar(
            usuario=user,
            acao=AuditLog.Acao.CRIACAO,
            instancia=movimentacao,
            request=self.request,
            justificativa=self.justificativa(),
        )


class _RelatorioView(APIView):
    role_policy = {"GET": LEITURA, "*": ADMIN}

    def periodo(self, request):
        return (
            _data_param(request, "data_inicio"),
            _data_param(request, "data_fim"),
        )


class FinanceiroDashboardView(_RelatorioView):
    def get(self, request):
        dados = relatorios.dashboard_financeiro()
        ultimos = Pagamento.objects.select_related(
            "conta", "conta__tutor", "forma_pagamento", "caixa", "estornado_por"
        ).prefetch_related("aplicacoes", "aplicacoes__parcela").order_by(
            "-data_hora"
        )[:8]
        dados["ultimos_pagamentos"] = PagamentoSerializer(
            ultimos, many=True, context={"request": request}
        ).data
        return Response(dados)


class ReceitaPeriodoView(_RelatorioView):
    def get(self, request):
        inicio, fim = self.periodo(request)
        agrupamento = request.query_params.get("agrupamento", "dia")
        if agrupamento not in {"dia", "mes"}:
            raise ValidationError(
                {"agrupamento": ["Use 'dia' ou 'mes'."]}
            )
        return Response(
            relatorios.receita_periodo(inicio, fim, agrupamento=agrupamento)
        )


class ReceitaServicoView(_RelatorioView):
    def get(self, request):
        inicio, fim = self.periodo(request)
        return Response(relatorios.receita_por_servico(inicio, fim))


class RecebimentosView(_RelatorioView):
    def get(self, request):
        inicio, fim = self.periodo(request)
        return Response(relatorios.recebimentos_por_forma(inicio, fim))


class ContasPendentesView(_RelatorioView):
    def get(self, request):
        vencimento_ate = _data_param(request, "vencimento_ate")
        tutor = request.query_params.get("tutor")
        qs = relatorios.contas_pendentes(
            vencimento_ate=vencimento_ate, tutor=tutor
        )
        total = sum((conta.saldo for conta in qs), services.ZERO)
        return Response(
            {
                "total": total,
                "quantidade": qs.count(),
                "linhas": ContaReceberSerializer(
                    qs, many=True, context={"request": request}
                ).data,
            }
        )


class InadimplenciaView(_RelatorioView):
    def get(self, request):
        tutor = request.query_params.get("tutor")
        qs = relatorios.inadimplencia(tutor=tutor)
        total = sum((conta.saldo for conta in qs), services.ZERO)
        return Response(
            {
                "total": total,
                "quantidade": qs.count(),
                "linhas": ContaReceberSerializer(
                    qs, many=True, context={"request": request}
                ).data,
            }
        )


class FluxoCaixaView(_RelatorioView):
    def get(self, request):
        inicio, fim = self.periodo(request)
        return Response(relatorios.fluxo_caixa(inicio, fim))
