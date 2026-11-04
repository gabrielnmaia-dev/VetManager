import hashlib

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


def _hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:40]


class UserBurstRateThrottle(UserRateThrottle):
    """Limite curto (picos) por usuário autenticado / IP anônimo."""

    scope = "user_burst"


class UserSustainedRateThrottle(UserRateThrottle):
    """Limite longo (uso contínuo) por usuário autenticado / IP anônimo."""

    scope = "user_sustained"


class _IPRateThrottle(SimpleRateThrottle):
    """Throttle sempre por IP (mesmo se houver usuário autenticado)."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginRateThrottle(SimpleRateThrottle):
    """Login: limita por USUÁRIO informado, não por IP.

    Atrás do Tailscale Funnel/nginx todos os clientes chegam com o mesmo IP
    (o do proxy). Chavear por IP transformava o limite em um teto global da
    clínica inteira: poucos logins derrubavam todos com 429. O username é a
    dimensão certa para proteger cada conta.
    """

    scope = "login"

    def get_cache_key(self, request, view):
        try:
            username = (request.data.get("username") or "").strip().lower()
        except Exception:
            username = ""
        ident = _hash(username) if username else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class TokenRefreshRateThrottle(SimpleRateThrottle):
    """Refresh: limita por token de refresh (fallback: IP)."""

    scope = "token_refresh"

    def get_cache_key(self, request, view):
        try:
            token = request.data.get("refresh") or ""
        except Exception:
            token = ""
        if not token:
            token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME, "")
        ident = _hash(token) if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AlterarSenhaRateThrottle(UserRateThrottle):
    """Limite por usuário para troca de senha (evita força bruta da senha atual)."""

    scope = "alterar_senha"


class TokenLogoutRateThrottle(UserRateThrottle):
    """Limite por usuário para logout."""

    scope = "token_logout"
