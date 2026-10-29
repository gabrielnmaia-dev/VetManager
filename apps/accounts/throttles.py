from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


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


class LoginRateThrottle(_IPRateThrottle):
    scope = "login"


class TokenRefreshRateThrottle(_IPRateThrottle):
    scope = "token_refresh"


class AlterarSenhaRateThrottle(UserRateThrottle):
    """Limite por usuário para troca de senha (evita força bruta da senha atual)."""

    scope = "alterar_senha"
