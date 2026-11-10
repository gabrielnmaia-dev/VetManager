"""Administração interna do portal (convites, acessos, solicitações e liberações).

Estes endpoints continuam dentro da API interna e exigem autenticação JWT
normal + grupos internos. Eles nunca aceitam token de portal.
"""

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.models import AuditLog
from apps.auditoria.services import registrar, snapshot
from apps.documentos.models import DocumentoClinico, DocumentoVeterinario
from apps.prescricao.models import Prescricao

from . import services
from .models import AcessoPortal, ConviteAcessoPortal, NotificacaoPortal, SolicitacaoAgendamento
from .serializers import (
    AcessoPortalSerializer,
    ConviteAcessoPortalCreateSerializer,
    ConviteAcessoPortalSerializer,
    LiberacaoDocumentoSerializer,
    NotificacaoPortalCreateSerializer,
    PortalNotificacaoSerializer,
    SolicitacaoAgendamentoAdminSerializer,
)

ADMIN = ("admin",)
GESTAO = ("admin", "recepcao")
EQUIPE = ("admin", "veterinario", "recepcao")


class ConviteAcessoPortalViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ConviteAcessoPortalSerializer
    queryset = ConviteAcessoPortal.objects.select_related("tutor").all()
    filterset_fields = ["tutor"]
    search_fields = ["email", "tutor__nome"]
    ordering = ["-created_at"]
    role_policy = {
        "list": GESTAO,
        "retrieve": GESTAO,
        "create": GESTAO,
        "revogar": ADMIN,
    }

    def create(self, request, *args, **kwargs):
        entrada = ConviteAcessoPortalCreateSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            convite, token = services.criar_convite(
                tutor=entrada.validated_data["tutor"],
                email=entrada.validated_data.get("email", ""),
                nome=entrada.validated_data.get("nome", ""),
                usuario=request.user,
                request=request,
            )
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjangoValidationError

            if isinstance(exc, DjangoValidationError):
                raise ValidationError(exc.messages)
            raise
        dados = ConviteAcessoPortalSerializer(convite).data
        dados["token"] = token
        return Response(dados, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="revogar")
    def revogar(self, request, pk=None):
        convite = self.get_object()
        services.revogar_convite(convite, usuario=request.user, request=request)
        return Response(ConviteAcessoPortalSerializer(convite).data)


class AcessoPortalViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AcessoPortalSerializer
    queryset = AcessoPortal.objects.select_related("user", "tutor").all()
    filterset_fields = ["tutor", "ativo"]
    search_fields = ["user__username", "user__email", "tutor__nome"]
    ordering = ["-created_at"]
    role_policy = {
        "list": GESTAO,
        "retrieve": GESTAO,
        "revogar": ADMIN,
        "sessoes": GESTAO,
    }

    @action(detail=True, methods=["post"], url_path="revogar")
    def revogar(self, request, pk=None):
        acesso = self.get_object()
        motivo = (request.data.get("motivo") or "").strip()
        services.revogar_acesso(
            acesso, usuario=request.user, motivo=motivo, request=request
        )
        return Response(AcessoPortalSerializer(acesso).data)

    @action(detail=True, methods=["get"], url_path="sessoes")
    def sessoes(self, request, pk=None):
        acesso = self.get_object()
        dados = [
            {
                "id": str(sessao.id),
                "criada_em": sessao.created_at,
                "expira_em": sessao.expira_em,
                "ativa": sessao.ativa,
                "revogada_em": sessao.revogada_em,
                "ip": sessao.ip,
                "user_agent": sessao.user_agent,
            }
            for sessao in acesso.sessoes.filter(is_deleted=False).order_by("-created_at")
        ]
        return Response(dados)


class SolicitacaoAgendamentoAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = SolicitacaoAgendamentoAdminSerializer
    queryset = SolicitacaoAgendamento.objects.select_related(
        "tutor", "pet", "atendimento"
    ).all()
    filterset_fields = ["status", "tutor", "pet", "tipo_servico"]
    search_fields = ["tutor__nome", "pet__nome", "observacoes"]
    ordering = ["-created_at"]
    role_policy = {
        "list": EQUIPE,
        "retrieve": EQUIPE,
        "aprovar": EQUIPE,
        "recusar": EQUIPE,
    }

    def _responder(self, request, pk, novo_status):
        solicitacao = self.get_object()
        if solicitacao.status != SolicitacaoAgendamento.Status.PENDENTE:
            raise ValidationError({"detail": "Solicitação já respondida."})
        resposta = (request.data.get("resposta") or "").strip()
        solicitacao.status = novo_status
        solicitacao.resposta = resposta
        solicitacao.respondido_em = timezone.now()
        solicitacao.respondido_por = request.user
        atendimento_id = request.data.get("atendimento")
        if atendimento_id:
            from apps.atendimentos.models import Atendimento

            atendimento = Atendimento.objects.filter(
                pk=atendimento_id,
                pet=solicitacao.pet,
                is_deleted=False,
            ).first()
            if atendimento is None:
                raise ValidationError(
                    {"atendimento": ["Atendimento inválido para este animal."]}
                )
            solicitacao.atendimento = atendimento
        solicitacao.save(
            update_fields=[
                "status",
                "resposta",
                "respondido_em",
                "respondido_por",
                "atendimento",
                "updated_at",
            ]
        )
        registrar(
            usuario=request.user,
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=solicitacao,
            justificativa=f"Solicitação de agendamento {novo_status} pelo interno.",
            request=request,
        )
        return Response(
            SolicitacaoAgendamentoAdminSerializer(solicitacao).data
        )

    @action(detail=True, methods=["post"], url_path="aprovar")
    def aprovar(self, request, pk=None):
        return self._responder(request, pk, SolicitacaoAgendamento.Status.APROVADA)

    @action(detail=True, methods=["post"], url_path="recusar")
    def recusar(self, request, pk=None):
        return self._responder(request, pk, SolicitacaoAgendamento.Status.RECUSADA)


class NotificacaoPortalAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PortalNotificacaoSerializer
    queryset = NotificacaoPortal.objects.select_related("tutor", "pet").all()
    filterset_fields = ["tutor", "pet", "lida", "tipo"]
    search_fields = ["titulo", "mensagem", "tutor__nome"]
    ordering = ["-created_at"]
    role_policy = {
        "list": EQUIPE,
        "retrieve": EQUIPE,
        "create": EQUIPE,
    }

    def create(self, request, *args, **kwargs):
        entrada = NotificacaoPortalCreateSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        notificacao = services.criar_notificacao(
            tutor=entrada.validated_data["tutor"],
            pet=entrada.validated_data.get("pet"),
            tipo=entrada.validated_data.get("tipo", NotificacaoPortal.Tipo.GERAL),
            titulo=entrada.validated_data["titulo"],
            mensagem=entrada.validated_data["mensagem"],
            usuario=request.user,
        )
        return Response(
            PortalNotificacaoSerializer(notificacao).data,
            status=status.HTTP_201_CREATED,
        )


class LiberacaoDocumentoView(APIView):
    """Liga/desliga a exposição de um documento ou prescrição no portal."""

    role_policy = {"POST": ADMIN}

    def post(self, request, *args, **kwargs):
        entrada = LiberacaoDocumentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        tipo = entrada.validated_data["tipo"]
        objeto_id = entrada.validated_data["id"]
        liberado = entrada.validated_data["liberado"]
        motivo = entrada.validated_data.get("motivo", "")

        if tipo == "clinico":
            objeto = DocumentoClinico.objects.filter(pk=objeto_id, is_deleted=False).first()
            campo = "liberado_portal"
        elif tipo == "veterinario":
            objeto = DocumentoVeterinario.objects.filter(pk=objeto_id, is_deleted=False).first()
            campo = "liberado_portal"
        else:
            objeto = Prescricao.objects.filter(pk=objeto_id, is_deleted=False).first()
            campo = "liberado_portal"

        if objeto is None:
            raise ValidationError({"id": ["Registro não encontrado."]})

        anteriores = snapshot(objeto)
        setattr(objeto, campo, liberado)
        if liberado:
            objeto.liberado_portal_em = timezone.now()
            objeto.liberado_portal_por = request.user
            update_fields = [campo, "liberado_portal_em", "liberado_portal_por", "updated_at"]
        else:
            objeto.liberado_portal_em = None
            objeto.liberado_portal_por = None
            update_fields = [campo, "liberado_portal_em", "liberado_portal_por", "updated_at"]
        objeto.save(update_fields=update_fields)
        registrar(
            usuario=request.user,
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=objeto,
            dados_anteriores=anteriores,
            justificativa=motivo
            or (
                "Documento liberado no portal do tutor."
                if liberado
                else "Documento removido do portal do tutor."
            ),
            request=request,
        )
        return Response(
            {
                "tipo": tipo,
                "id": str(objeto.id),
                "liberado": liberado,
                "liberado_portal_em": getattr(objeto, "liberado_portal_em", None),
            }
        )
