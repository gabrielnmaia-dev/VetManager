"""Rate limits específicos do portal."""

import hashlib

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


def _hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:40]


class PortalLoginRateThrottle(SimpleRateThrottle):
    """Limita por usuário informado; fallback por IP."""

    scope = "portal_login"

    def get_cache_key(self, request, view):
        try:
            username = (request.data.get("username") or "").strip().lower()
        except Exception:
            username = ""
        ident = _hash(username) if username else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PortalRecuperacaoRateThrottle(SimpleRateThrottle):
    """Limita pedidos de recuperação por e-mail; fallback por IP."""

    scope = "portal_recuperacao"

    def get_cache_key(self, request, view):
        try:
            email = (request.data.get("email") or "").strip().lower()
        except Exception:
            email = ""
        ident = _hash(email) if email else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PortalRefreshRateThrottle(SimpleRateThrottle):
    """Limita renovação por token de refresh; fallback por IP."""

    scope = "portal_refresh"

    def get_cache_key(self, request, view):
        try:
            token = request.data.get("refresh") or ""
        except Exception:
            token = ""
        if not token:
            token = request.COOKIES.get(
                getattr(settings, "PORTAL_REFRESH_COOKIE_NAME", "portal_refresh"),
                "",
            )
        ident = _hash(token) if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PortalEscritaRateThrottle(SimpleRateThrottle):
    """Limita operações de escrita autenticadas no portal."""

    scope = "portal_escrita"

    def get_cache_key(self, request, view):
        acesso = getattr(request, "portal_acesso", None)
        ident = str(acesso.id) if acesso else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
