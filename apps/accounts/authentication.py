from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication

SAFE_METHODS = ("GET", "HEAD", "OPTIONS", "TRACE")


def enforce_csrf(request) -> None:
    """Valida o token CSRF em requisições autenticadas por cookie.

    O JWT em cookie httpOnly viaja automaticamente no navegador. Sem esta
    checagem, um site terceiro poderia disparar POST/PATCH/DELETE em nome do
    usuário logado (CSRF). Requisições com ``Authorization: Bearer`` continuam
    isentas — o header não é enviado automaticamente pelo navegador.
    """

    if request.method in SAFE_METHODS:
        return

    def dummy_get_response(req):
        return None

    check = CSRFCheck(dummy_get_response)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f"CSRF inválido: {reason}")


class JWTCookieAuthentication(JWTAuthentication):
    """Lê o access token do cookie httpOnly definido pelo backend.

    Mantém compatibilidade com ``Authorization: Bearer`` (Swagger, cURL,
    integrações). Quando a credencial vem do cookie, exige CSRF nas operações
    que alteram estado.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        token_veio_do_cookie = False

        if header is None:
            raw_token = request.COOKIES.get(
                getattr(settings, "JWT_ACCESS_COOKIE_NAME", "access")
            )
            if raw_token is None:
                return None
            token_veio_do_cookie = True
        else:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        validated_token = self.get_validated_token(raw_token)

        # Um token de portal carrega a claim tipo="portal". Ele nunca deve
        # abrir endpoints administrativos, mesmo que o usuário exista.
        if validated_token.get("tipo") == "portal":
            raise exceptions.AuthenticationFailed(
                "Token do portal do tutor não é aceito na API interna."
            )

        if token_veio_do_cookie:
            enforce_csrf(request)

        return self.get_user(validated_token), validated_token
