"""Autenticação exclusiva do portal do tutor.

Lê o access token do cookie httpOnly ``portal_access`` (ou de um header
``Authorization: Bearer`` explícito), exige a claim ``tipo = "portal"`` e
confirma que a sessão e o vínculo ainda estão ativos.

A API interna usa outro nome de cookie e recusa a claim de portal, então um
token de tutor nunca abre endpoints administrativos — e vice-versa.
"""

from django.conf import settings
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.accounts.authentication import enforce_csrf

from .models import AcessoPortal, SessaoPortal
from .tokens import TIPO_PORTAL


class PortalJWTCookieAuthentication(JWTAuthentication):
    """Autentica somente sessões do portal, com revogação por sessão."""

    def authenticate_header(self, request):
        # Garante 401 (e não 403) quando a sessão do portal está ausente.
        return "Portal"

    def authenticate(self, request):
        header = self.get_header(request)
        token_veio_do_cookie = False

        if header is None:
            raw_token = request.COOKIES.get(
                getattr(settings, "PORTAL_ACCESS_COOKIE_NAME", "portal_access")
            )
            if raw_token is None:
                return None
            token_veio_do_cookie = True
        else:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None

        validated_token = self.get_validated_token(raw_token)
        if validated_token.get("tipo") != TIPO_PORTAL:
            raise exceptions.AuthenticationFailed(
                "Token inválido para o portal do tutor."
            )

        if token_veio_do_cookie:
            enforce_csrf(request)

        acesso_id = validated_token.get("acesso_id")
        sessao_id = validated_token.get("sid")
        if not acesso_id or not sessao_id:
            raise exceptions.AuthenticationFailed("Sessão do portal incompleta.")

        acesso = (
            AcessoPortal.objects.select_related("user", "tutor")
            .filter(pk=acesso_id, ativo=True, is_deleted=False)
            .first()
        )
        if acesso is None or not acesso.valido:
            raise exceptions.AuthenticationFailed(
                "Acesso ao portal revogado ou inativo."
            )
        if not acesso.user.is_active:
            raise exceptions.AuthenticationFailed("Conta inativa.")

        sessao = (
            SessaoPortal.objects.filter(
                pk=sessao_id,
                acesso=acesso,
                revogada_em__isnull=True,
                is_deleted=False,
            )
            .first()
        )
        if sessao is None or not sessao.ativa:
            raise exceptions.AuthenticationFailed("Sessão expirada ou revogada.")

        # Disponibiliza o vínculo para as views, sem depender de query extra.
        request.portal_acesso = acesso
        request.portal_sessao = sessao
        return acesso.user, validated_token
