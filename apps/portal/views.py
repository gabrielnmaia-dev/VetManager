"""Endpoints do portal externo do tutor.

Todos os acessos autenticados usam ``PortalJWTCookieAuthentication`` e
``IsPortalAuthenticated``. O conjunto de dados visível é sempre derivado de
``request.portal_acesso.tutor``, nunca de um id enviado pelo cliente.
"""

from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, Http404
from django.core.files.storage import default_storage
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.atendimentos.models import Atendimento
from apps.auditoria.models import AuditLog
from apps.auditoria.services import registrar, snapshot
from apps.documentos.models import DocumentoClinico, DocumentoVeterinario
from apps.pets.models import Pet
from apps.prescricao.models import Prescricao
from apps.prontuario.models import Vacina

from . import services
from .authentication import PortalJWTCookieAuthentication
from .models import AcessoPortal, NotificacaoPortal, SolicitacaoAgendamento
from .permissions import IsPortalAuthenticated
from .serializers import (
    AlterarSenhaPortalSerializer,
    PortalAgendamentoSerializer,
    PortalLoginSerializer,
    PortalNotificacaoSerializer,
    PortalPerfilSerializer,
    PortalPetSerializer,
    PortalPrescricaoSerializer,
    PortalSolicitacaoAgendamentoSerializer,
    PortalSolicitacaoCreateSerializer,
    PortalVacinaSerializer,
)
from .throttles import (
    PortalEscritaRateThrottle,
    PortalLoginRateThrottle,
    PortalRecuperacaoRateThrottle,
    PortalRefreshRateThrottle,
)

PORTAL_AUTH = [PortalJWTCookieAuthentication]
PORTAL_ALLOWED = [IsPortalAuthenticated]


def _cookie_kwargs():
    return {
        "httponly": True,
        "secure": settings.JWT_COOKIE_SECURE,
        "samesite": settings.JWT_COOKIE_SAMESITE,
        "domain": getattr(settings, "JWT_COOKIE_DOMAIN", None),
        "path": getattr(settings, "PORTAL_COOKIE_PATH", "/"),
    }


def _set_portal_cookies(response, access_token, refresh_token=None):
    kwargs = _cookie_kwargs()
    response.set_cookie(
        getattr(settings, "PORTAL_ACCESS_COOKIE_NAME", "portal_access"),
        access_token,
        max_age=int(getattr(settings, "PORTAL_ACCESS_MINUTOS", 30)) * 60,
        **kwargs,
    )
    if refresh_token is not None:
        response.set_cookie(
            getattr(settings, "PORTAL_REFRESH_COOKIE_NAME", "portal_refresh"),
            refresh_token,
            max_age=int(getattr(settings, "PORTAL_REFRESH_DIAS", 7)) * 86400,
            **kwargs,
        )


def _clear_portal_cookies(response):
    kwargs = _cookie_kwargs()
    kwargs.pop("httponly", None)
    kwargs.pop("secure", None)
    response.delete_cookie(
        getattr(settings, "PORTAL_ACCESS_COOKIE_NAME", "portal_access"), **kwargs
    )
    response.delete_cookie(
        getattr(settings, "PORTAL_REFRESH_COOKIE_NAME", "portal_refresh"), **kwargs
    )


class PortalScopedMixin:
    """Restringe o queryset ao tutor da sessão atual."""

    def get_tutor_portal(self):
        return self.request.portal_acesso.tutor


class PortalPublicAPIView(APIView):
    """Base dos endpoints públicos do portal.

    Sem autenticadores, o DRF converte ``AuthenticationFailed`` em 403. O
    portal expõe o cabeçalho ``Portal`` para manter a semântica de 401 nas
    falhas de login/refresh.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        return "Portal"


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------


class PortalCsrfView(PortalPublicAPIView):
    def get(self, request, *args, **kwargs):
        token = get_token(request)
        response = Response({"csrfToken": token})
        response["Cache-Control"] = "no-store"
        return response


class PortalLoginView(PortalPublicAPIView):
    throttle_classes = [PortalLoginRateThrottle]

    def post(self, request, *args, **kwargs):
        from django.contrib.auth import authenticate

        serializer = PortalLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        user = authenticate(request, username=username, password=password)
        if user is None or not user.is_active:
            raise AuthenticationFailed("Usuário ou senha inválidos.")

        acesso = (
            AcessoPortal.objects.select_related("tutor")
            .filter(user=user, ativo=True, is_deleted=False)
            .first()
        )
        if acesso is None or not acesso.valido:
            # A conta existe, mas não está habilitada para o portal.
            raise AuthenticationFailed(
                "Este usuário não possui acesso ativo ao portal do tutor."
            )

        access, refresh, _ = services.criar_tokens(acesso=acesso, request=request)
        get_token(request)
        response = Response(
            {
                "usuario": {
                    "username": user.get_username(),
                    "tutor": str(acesso.tutor_id),
                    "tutor_nome": acesso.tutor.nome,
                }
            },
            status=status.HTTP_200_OK,
        )
        _set_portal_cookies(response, str(access), str(refresh))
        response["Cache-Control"] = "no-store"
        return response


class PortalRefreshView(PortalPublicAPIView):
    throttle_classes = [PortalRefreshRateThrottle]

    def post(self, request, *args, **kwargs):
        from .tokens import PortalRefreshToken

        raw = request.data.get("refresh") or request.COOKIES.get(
            getattr(settings, "PORTAL_REFRESH_COOKIE_NAME", "portal_refresh"), ""
        )
        if not raw:
            raise AuthenticationFailed("Sessão não informada.")
        try:
            token = PortalRefreshToken(raw)
        except TokenError:
            raise AuthenticationFailed("Sessão expirada. Entre novamente.")
        try:
            access, refresh, _ = services.renovar_tokens(
                refresh_token=token, request=request
            )
        except Exception as exc:
            raise AuthenticationFailed(str(exc))

        get_token(request)
        response = Response({"detail": "Sessão renovada."})
        _set_portal_cookies(response, str(access), str(refresh))
        response["Cache-Control"] = "no-store"
        return response


class PortalLogoutView(PortalPublicAPIView):
    def post(self, request, *args, **kwargs):
        raw = request.data.get("refresh") or request.COOKIES.get(
            getattr(settings, "PORTAL_REFRESH_COOKIE_NAME", "portal_refresh"), ""
        )
        if raw:
            try:
                token = RefreshToken(raw)
                sid = token.get("sid")
                if sid and token.get("tipo") == "portal":
                    from .models import SessaoPortal

                    SessaoPortal.objects.filter(pk=sid).update(
                        revogada_em=timezone.now(), updated_at=timezone.now()
                    )
                token.blacklist()
            except TokenError:
                pass
        response = Response({"detail": "Sessão encerrada."})
        _clear_portal_cookies(response)
        response["Cache-Control"] = "no-store"
        return response


class PortalRecuperarSenhaView(PortalPublicAPIView):
    throttle_classes = [PortalRecuperacaoRateThrottle]

    def post(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").strip()
        # Resposta uniforme: não revela se o e-mail existe.
        services.recuperar_senha(email=email, request=request)
        return Response(
            {
                "detail": (
                    "Se o e-mail estiver cadastrado no portal, enviaremos as "
                    "instruções de redefinição."
                )
            },
            status=status.HTTP_202_ACCEPTED,
        )


class PortalRedefinirSenhaView(PortalPublicAPIView):
    throttle_classes = [PortalRecuperacaoRateThrottle]

    def post(self, request, *args, **kwargs):
        token = request.data.get("token") or ""
        nova_senha = request.data.get("nova_senha") or ""
        confirmar = request.data.get("confirmar_nova_senha") or ""
        if nova_senha != confirmar:
            raise ValidationError(
                {"confirmar_nova_senha": ["As senhas não coincidem."]}
            )
        try:
            services.redefinir_senha(token=token, nova_senha=nova_senha)
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjangoValidationError

            if isinstance(exc, DjangoValidationError):
                raise ValidationError(exc.messages)
            raise
        return Response({"detail": "Senha redefinida. Entre com a nova senha."})


class PortalResgatarConviteView(PortalPublicAPIView):
    throttle_classes = [PortalLoginRateThrottle]

    def post(self, request, *args, **kwargs):
        token = request.data.get("token") or ""
        username = request.data.get("username") or ""
        password = request.data.get("password") or ""
        confirmar = request.data.get("confirmar_senha") or ""
        aceite = bool(request.data.get("aceite_privacidade"))
        if password != confirmar:
            raise ValidationError({"confirmar_senha": ["As senhas não coincidem."]})
        try:
            user, _ = services.resgatar_convite(
                token=token,
                username=username,
                password=password,
                aceite_privacidade=aceite,
            )
        except Exception as exc:
            from django.core.exceptions import ValidationError as DjangoValidationError

            if isinstance(exc, DjangoValidationError):
                raise ValidationError(exc.messages)
            raise
        return Response(
            {
                "detail": "Acesso criado com sucesso. Entre com seu usuário e senha.",
                "username": user.get_username(),
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Perfil e resumo
# ---------------------------------------------------------------------------


class PortalPerfilView(RetrieveUpdateAPIView):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    serializer_class = PortalPerfilSerializer

    def get_object(self):
        return self.request.portal_acesso.tutor

    def perform_update(self, serializer):
        anteriores = snapshot(serializer.instance)
        instance = serializer.save()
        registrar(
            usuario=self.request.user,
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=instance,
            dados_anteriores=anteriores,
            justificativa="Atualização de dados cadastrais pelo portal do tutor.",
            request=self.request,
        )
        return instance


class PortalAlterarSenhaView(APIView):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    throttle_classes = [PortalEscritaRateThrottle]

    def post(self, request, *args, **kwargs):
        serializer = AlterarSenhaPortalSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Mantém a sessão atual e derruba as demais após a troca de senha.
        services.revogar_sessoes(
            request.portal_acesso, exceto=request.portal_sessao
        )
        return Response({"detail": "Senha alterada com sucesso."})


class PortalResumoView(APIView):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED

    def get(self, request, *args, **kwargs):
        tutor = request.portal_acesso.tutor
        agora = timezone.now()
        pets = Pet.objects.filter(tutor=tutor, is_deleted=False)
        proximos = (
            Atendimento.objects.filter(
                pet__tutor=tutor,
                is_deleted=False,
                data_hora_inicio__gte=agora,
            )
            .exclude(status__in=[Atendimento.Status.CANCELADO, Atendimento.Status.FALTOU])
            .select_related("pet")
            .order_by("data_hora_inicio")[:5]
        )
        nao_lidas = NotificacaoPortal.objects.filter(
            tutor=tutor, lida=False, is_deleted=False
        ).count()
        return Response(
            {
                "tutor": {"id": str(tutor.id), "nome": tutor.nome},
                "pets": pets.count(),
                "proximos_agendamentos": PortalAgendamentoSerializer(
                    proximos, many=True, context={"request": request}
                ).data,
                "notificacoes_nao_lidas": nao_lidas,
                "solicitacoes_pendentes": SolicitacaoAgendamento.objects.filter(
                    tutor=tutor,
                    status=SolicitacaoAgendamento.Status.PENDENTE,
                    is_deleted=False,
                ).count(),
            }
        )


# ---------------------------------------------------------------------------
# Dados do animal
# ---------------------------------------------------------------------------


class PortalPetViewSet(
    PortalScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    serializer_class = PortalPetSerializer

    def get_queryset(self):
        return (
            Pet.objects.filter(tutor=self.get_tutor_portal(), is_deleted=False)
            .select_related("especie", "raca")
            .order_by("nome")
        )


class PortalAgendamentoViewSet(
    PortalScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    serializer_class = PortalAgendamentoSerializer
    filterset_fields = ["pet", "status", "tipo_servico"]
    ordering_fields = ["data_hora_inicio", "status"]
    ordering = ["-data_hora_inicio"]

    def get_queryset(self):
        return (
            Atendimento.objects.filter(
                pet__tutor=self.get_tutor_portal(), is_deleted=False
            )
            .select_related("pet", "profissional")
            .all()
        )


class PortalSolicitacaoAgendamentoViewSet(
    PortalScopedMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    throttle_classes = [PortalEscritaRateThrottle]

    def get_queryset(self):
        return SolicitacaoAgendamento.objects.filter(
            tutor=self.get_tutor_portal(), is_deleted=False
        ).select_related("pet")

    def get_serializer_class(self):
        if self.action == "create":
            return PortalSolicitacaoCreateSerializer
        return PortalSolicitacaoAgendamentoSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["portal_acesso"] = self.request.portal_acesso
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        solicitacao = serializer.save(
            tutor=request.portal_acesso.tutor,
            status=SolicitacaoAgendamento.Status.PENDENTE,
        )
        return Response(
            PortalSolicitacaoAgendamentoSerializer(
                solicitacao, context={"request": request}
            ).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _cancelar(request, pk=None, queryset=None):
        objeto = queryset.filter(pk=pk).first()
        if objeto is None:
            raise Http404
        if objeto.status != SolicitacaoAgendamento.Status.PENDENTE:
            raise ValidationError(
                {"detail": "Somente solicitações pendentes podem ser canceladas."}
            )
        objeto.status = SolicitacaoAgendamento.Status.CANCELADA
        objeto.save(update_fields=["status", "updated_at"])
        return Response(
            PortalSolicitacaoAgendamentoSerializer(
                objeto, context={"request": request}
            ).data
        )


class PortalSolicitacaoCancelarView(APIView):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    throttle_classes = [PortalEscritaRateThrottle]

    def post(self, request, pk=None, *args, **kwargs):
        queryset = SolicitacaoAgendamento.objects.filter(
            tutor=request.portal_acesso.tutor, is_deleted=False
        )
        return PortalSolicitacaoAgendamentoViewSet._cancelar(
            request, pk=pk, queryset=queryset
        )


class PortalVacinaViewSet(
    PortalScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    serializer_class = PortalVacinaSerializer
    filterset_fields = ["pet"]
    search_fields = ["nome_vacina"]
    ordering_fields = ["data_aplicacao"]
    ordering = ["-data_aplicacao"]

    def get_queryset(self):
        return Vacina.objects.filter(
            pet__tutor=self.get_tutor_portal(), is_deleted=False
        ).select_related("pet")


class PortalPrescricaoViewSet(
    PortalScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    serializer_class = PortalPrescricaoSerializer
    filterset_fields = ["pet", "status"]
    ordering = ["-data_prescricao"]

    def get_queryset(self):
        return (
            Prescricao.objects.filter(
                pet__tutor=self.get_tutor_portal(),
                liberado_portal=True,
                is_deleted=False,
            )
            .select_related("pet", "veterinario", "veterinario__profissional")
            .prefetch_related("itens", "itens__produto")
        )


class PortalNotificacaoViewSet(
    PortalScopedMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED
    serializer_class = PortalNotificacaoSerializer
    filterset_fields = ["lida", "tipo"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return NotificacaoPortal.objects.filter(
            tutor=self.get_tutor_portal(), is_deleted=False
        )

    def _marcar_lida(self, notificacao):
        if not notificacao.lida:
            notificacao.lida = True
            notificacao.lida_em = timezone.now()
            notificacao.save(update_fields=["lida", "lida_em", "updated_at"])

    @action(detail=True, methods=["post"], url_path="marcar-lida")
    def marcar_lida(self, request, pk=None, *args, **kwargs):
        notificacao = self.get_object()
        self._marcar_lida(notificacao)
        return Response({"detail": "Notificação marcada como lida."})


class PortalNotificacaoMarcarTodasView(APIView):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED

    def post(self, request, *args, **kwargs):
        NotificacaoPortal.objects.filter(
            tutor=request.portal_acesso.tutor,
            lida=False,
            is_deleted=False,
        ).update(lida=True, lida_em=timezone.now(), updated_at=timezone.now())
        return Response({"detail": "Notificações marcadas como lidas."})


# ---------------------------------------------------------------------------
# Documentos liberados (clínicos e veterinários)
# ---------------------------------------------------------------------------


def _documentos_liberados(tutor, pet_id=None):
    clinicos = DocumentoClinico.objects.filter(
        pet__tutor=tutor, liberado_portal=True, is_deleted=False
    ).select_related("pet")
    veterinarios = DocumentoVeterinario.objects.filter(
        tutor=tutor,
        liberado_portal=True,
        situacao="emitido",
        is_deleted=False,
    ).select_related("pet")
    if pet_id:
        clinicos = clinicos.filter(pet_id=pet_id)
        veterinarios = veterinarios.filter(pet_id=pet_id)

    itens = []
    for doc in clinicos:
        itens.append(
            {
                "id": str(doc.id),
                "origem": "clinico",
                "tipo": doc.tipo,
                "tipo_display": doc.get_tipo_display(),
                "titulo": doc.nome_original,
                "descricao": doc.descricao,
                "data": doc.data_exame or doc.data_envio,
                "pet": str(doc.pet_id),
                "pet_nome": doc.pet.nome,
                "mime_type": doc.mime_type,
                "tamanho": doc.tamanho,
                "liberado_portal": True,
                "download_url": f"/api/v1/portal/documentos/clinico/{doc.id}/download/",
            }
        )
    for doc in veterinarios:
        itens.append(
            {
                "id": str(doc.id),
                "origem": "veterinario",
                "tipo": doc.tipo,
                "tipo_display": doc.get_tipo_display(),
                "titulo": doc.titulo,
                "descricao": "",
                "data": doc.data_emissao,
                "pet": str(doc.pet_id),
                "pet_nome": doc.pet.nome,
                "mime_type": "application/pdf",
                "tamanho": doc.pdf_tamanho,
                "identificador": doc.identificador,
                "liberado_portal": True,
                "download_url": f"/api/v1/portal/documentos/veterinario/{doc.id}/download/",
            }
        )
    itens.sort(key=lambda item: item["data"] or timezone.now(), reverse=True)
    return itens


class PortalDocumentosView(APIView):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED

    def get(self, request, *args, **kwargs):
        pet_id = request.query_params.get("pet")
        if pet_id:
            import uuid

            try:
                uuid.UUID(str(pet_id))
            except (TypeError, ValueError):
                raise ValidationError({"pet": ["Identificador de animal inválido."]})
        return Response(_documentos_liberados(request.portal_acesso.tutor, pet_id))


class PortalDocumentoDownloadView(APIView):
    authentication_classes = PORTAL_AUTH
    permission_classes = PORTAL_ALLOWED

    def get(self, request, origem, pk, *args, **kwargs):
        tutor = request.portal_acesso.tutor
        if origem == "clinico":
            documento = DocumentoClinico.objects.filter(
                pk=pk, pet__tutor=tutor, liberado_portal=True, is_deleted=False
            ).first()
            if documento is None:
                raise Http404
            caminho = documento.caminho_arquivo
            nome = documento.nome_original
            mime = documento.mime_type or "application/octet-stream"
        elif origem == "veterinario":
            documento = DocumentoVeterinario.objects.filter(
                pk=pk,
                tutor=tutor,
                liberado_portal=True,
                situacao="emitido",
                is_deleted=False,
            ).first()
            if documento is None:
                raise Http404
            caminho = documento.pdf_caminho
            nome = f"{documento.identificador}.pdf"
            mime = "application/pdf"
        else:
            raise Http404

        if not caminho or not default_storage.exists(caminho):
            raise Http404
        arquivo = default_storage.open(caminho, "rb")
        response = FileResponse(arquivo, content_type=mime)
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(nome)}"
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response
