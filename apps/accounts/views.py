from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    AlterarSenhaResponseSerializer,
    AlterarSenhaSerializer,
    PerfilSerializer,
    VetTokenObtainPairSerializer,
)
from .throttles import (
    AlterarSenhaRateThrottle,
    LoginRateThrottle,
    TokenRefreshRateThrottle,
)


class VetTokenObtainPairView(TokenObtainPairView):
    """Login JWT com rate limit por IP (escopo "login")."""

    throttle_classes = [LoginRateThrottle]


class VetTokenRefreshView(TokenRefreshView):
    """Refresh JWT com rate limit por IP (escopo "token_refresh")."""

    throttle_classes = [TokenRefreshRateThrottle]


class PerfilView(RetrieveUpdateAPIView):
    """Perfil do usuário autenticado.

    GET   /api/v1/perfil/  -> dados do próprio usuário
    PATCH /api/v1/perfil/  -> atualiza nome, sobrenome e e-mail
    """

    serializer_class = PerfilSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    @extend_schema(
        tags=["Perfil"],
        summary="Dados do usuário logado",
        description=(
            "Retorna o perfil do usuário dono do token: username, nome, "
            "e-mail, grupos (perfis) e permissões."
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["Perfil"],
        summary="Atualizar o próprio perfil",
        description=(
            "Atualiza apenas `first_name`, `last_name` e `email`. "
            "`username`, grupos e permissões são somente leitura (geridos no /admin)."
        ),
        examples=[
            OpenApiExample(
                "Exemplo",
                value={
                    "first_name": "Ana",
                    "last_name": "Souza",
                    "email": "ana@vetmanager.local",
                },
                request_only=True,
            )
        ],
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)

    @extend_schema(tags=["Perfil"], summary="Atualizar parcialmente o próprio perfil")
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)


class AlterarSenhaView(APIView):
    """Troca de senha do próprio usuário, exigindo a senha atual.

    POST /api/v1/perfil/alterar-senha/
    Body: {"senha_atual": "...", "nova_senha": "...", "confirmar_nova_senha": "..."}

    Por segurança, todos os refresh tokens antigos do usuário são revogados
    (as outras sessões/dispositivos são deslogados) e um novo par de tokens é
    devolvido na resposta, para o app continuar logado sem novo login.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [AlterarSenhaRateThrottle]

    @extend_schema(
        tags=["Perfil"],
        summary="Alterar a própria senha",
        description=(
            "Exige a senha atual. A nova senha passa pelos validadores do "
            "Django (AUTH_PASSWORD_VALIDATORS). Ao concluir, os refresh tokens "
            "anteriores são revogados e um novo par `access`/`refresh` é "
            "retornado — o app deve substituir os tokens que já guarda. Os "
            "outros dispositivos precisarão fazer login de novo."
        ),
        request=AlterarSenhaSerializer,
        responses={200: AlterarSenhaResponseSerializer},
        examples=[
            OpenApiExample(
                "Exemplo",
                value={
                    "senha_atual": "senha-antiga-123",
                    "nova_senha": "senha-nova-456",
                    "confirmar_nova_senha": "senha-nova-456",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = AlterarSenhaSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Invalida os refresh tokens emitidos antes da troca de senha.
        for token in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=token)

        # Emite um par novo (com os mesmos claims do login) para o app atual.
        novo_refresh = VetTokenObtainPairSerializer.get_token(user)

        return Response(
            {
                "detail": "Senha alterada com sucesso.",
                "access": str(novo_refresh.access_token),
                "refresh": str(novo_refresh),
            },
            status=status.HTTP_200_OK,
        )
