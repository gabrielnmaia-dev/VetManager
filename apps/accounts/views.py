from django.conf import settings
from django.middleware.csrf import get_token
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken
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
    TokenLogoutRateThrottle,
    TokenRefreshRateThrottle,
)


def _cookie_kwargs():
    """Atributos comuns dos cookies JWT (usados no set e no delete)."""
    return {
        "httponly": True,
        "secure": settings.JWT_COOKIE_SECURE,
        "samesite": settings.JWT_COOKIE_SAMESITE,
        "domain": getattr(settings, "JWT_COOKIE_DOMAIN", None),
        "path": settings.JWT_COOKIE_PATH,
    }


def _max_age(delta):
    """Converte timedelta em segundos (None se não for timedelta)."""
    try:
        return int(delta.total_seconds())
    except (AttributeError, TypeError, ValueError):
        return None


def _set_jwt_cookies(response, access_token, refresh_token=None):
    """Define os tokens JWT em cookies httpOnly (inacessíveis via JS).

    Usa Max-Age para o cookie sobreviver ao fechamento do navegador no
    celular (cookies de sessão são descartados com mais frequência no iOS).
    """
    kwargs = _cookie_kwargs()
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE_NAME,
        access_token,
        max_age=_max_age(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]),
        **kwargs,
    )
    if refresh_token is not None:
        response.set_cookie(
            settings.JWT_REFRESH_COOKIE_NAME,
            refresh_token,
            max_age=_max_age(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]),
            **kwargs,
        )


def _clear_jwt_cookies(response):
    """Remove os cookies httpOnly de JWT (logout).

    Repete path/domain/samesite do Set-Cookie (identidade do cookie);
    sem isso alguns navegadores mantêm o cookie antigo no lugar.
    """
    # delete_cookie() nao aceita httponly/secure: esses atributos nao fazem
    # parte da identidade do cookie (que e nome + domain + path). Removê-los
    # evita TypeError no logout; path/domain/samesite continuam iguais ao Set.
    kwargs = _cookie_kwargs()
    kwargs.pop("httponly", None)
    kwargs.pop("secure", None)
    response.delete_cookie(settings.JWT_ACCESS_COOKIE_NAME, **kwargs)
    response.delete_cookie(settings.JWT_REFRESH_COOKIE_NAME, **kwargs)


class VetTokenObtainPairView(TokenObtainPairView):
    """Login JWT com rate limit por IP (escopo "login").

    Emite os tokens em cookies httpOnly `access` e `refresh` (Set-Cookie)
    para que o navegador os armazene sem expô-los a XSS.
    """

    throttle_classes = [LoginRateThrottle]

    def post(self, request, *args, **kwargs):
        # get_token() marca o request para o CsrfViewMiddleware gravar o
        # cookie csrftoken na resposta. Sem isso o SPA não tinha cookie para
        # ecoar no header X-CSRFToken e todo POST/PATCH/DELETE autenticado por
        # cookie falhava com "CSRF cookie not set".
        get_token(request)
        response = super().post(request, *args, **kwargs)
        access = response.data.get("access")
        refresh = response.data.get("refresh")
        if access:
            _set_jwt_cookies(response, access, refresh)
        response["Cache-Control"] = "no-store"
        return response


class VetTokenRefreshView(TokenRefreshView):
    """Refresh JWT com rate limit por IP (escopo "token_refresh").

    Lê o refresh token do cookie httpOnly (se não vier no body) e emite um
    novo access (e refresh, com rotação) em cookies httpOnly.
    """

    throttle_classes = [TokenRefreshRateThrottle]

    def post(self, request, *args, **kwargs):
        # Se o cliente não enviar o refresh no body, tenta ler do cookie httpOnly.
        # request.data pode ser imutável (QueryDict de formulário), então
        # copiamos antes de injetar o cookie em vez de mutar o original.
        if not request.data.get("refresh"):
            refresh_cookie = request.COOKIES.get(
                settings.JWT_REFRESH_COOKIE_NAME, ""
            )
            if refresh_cookie:
                dados = (
                    request.data.copy()
                    if hasattr(request.data, "copy")
                    else dict(request.data)
                )
                dados["refresh"] = refresh_cookie
                request._full_data = dados
        # Renova também o cookie CSRF a cada refresh, para que sessões longas
        # continuem conseguindo enviar o header nas operações de escrita.
        get_token(request)
        response = super().post(request, *args, **kwargs)
        access = response.data.get("access")
        refresh = response.data.get("refresh")
        if access:
            _set_jwt_cookies(response, access, refresh)
        response["Cache-Control"] = "no-store"
        return response


class CsrfCookieView(APIView):
    """Garante o cookie CSRF e devolve o token para o SPA.

    O front em staging roda em outro domínio (Netlify) e, por isso, não
    consegue ler o cookie ``csrftoken`` via ``document.cookie``. Este endpoint
    público cria o cookie e devolve em JSON um token mascarado equivalente; o
    SPA guarda o valor em memória e o envia no header ``X-CSRFToken``,
    completando o double-submit. Não expõe dados e não autentica ninguém.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Autenticação"],
        summary="Obtém/renova o token CSRF",
        description=(
            "Define o cookie csrftoken (se ainda não existir) e retorna um "
            "token equivalente em `csrfToken` para ser enviado no header "
            "X-CSRFToken pelas requisições de escrita."
        ),
    )
    def get(self, request, *args, **kwargs):
        token = get_token(request)
        response = Response({"csrfToken": token})
        response["Cache-Control"] = "no-store"
        return response


class TokenLogoutView(APIView):
    """Logout: blacklista o refresh token e limpa os cookies httpOnly."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [TokenLogoutRateThrottle]

    def post(self, request, *args, **kwargs):
        refresh = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if refresh:
            try:
                token = RefreshToken(refresh)
                token.blacklist()
            except Exception:
                # Token inválido ou já blacklistado — prossegue com a limpeza.
                pass
        response = Response({"detail": "Logout realizado com sucesso."})
        _clear_jwt_cookies(response)
        return response


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
        access = str(novo_refresh.access_token)
        refresh = str(novo_refresh)

        response = Response(
            {
                "detail": "Senha alterada com sucesso.",
                "access": access,
                "refresh": refresh,
            },
            status=status.HTTP_200_OK,
        )
        _set_jwt_cookies(response, access, refresh)
        response["Cache-Control"] = "no-store"
        return response
