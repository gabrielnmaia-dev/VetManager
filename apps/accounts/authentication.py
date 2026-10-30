from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication


class JWTCookieAuthentication(JWTAuthentication):
    """
    Autenticação JWT que lê o access token do cookie httpOnly `access`
    (definido pelo backend em /token/ e /token/refresh/) em vez de exigir
    o header Authorization: Bearer.

    Mantém compatibilidade com o header Authorization para clientes que ainda
    o enviem (ex.: navegador, Swagger, cURL).
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            raw_token = request.COOKIES.get(
                settings.SIMPLE_JWT.get("AUTH_ACCESS_COOKIE_NAME", "access")
            )
            if raw_token is None:
                return None
        else:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
