"""Tokens JWT específicos do portal.

Os tokens do portal carregam a claim ``tipo = "portal"``. A API interna
recusa explicitamente essa claim (ver ``apps.accounts.authentication``), e o
portal recusa tokens sem ela. Os dois universos de autenticação compartilham
a mesma chave de assinatura, mas nunca são intercambiáveis.
"""

from rest_framework_simplejwt.tokens import RefreshToken

TIPO_PORTAL = "portal"


class PortalRefreshToken(RefreshToken):
    """Refresh token do portal do tutor."""

    @classmethod
    def for_user(cls, user):
        token = super().for_user(user)
        token["tipo"] = TIPO_PORTAL
        return token


def token_e_portal(token) -> bool:
    return token.get("tipo") == TIPO_PORTAL
