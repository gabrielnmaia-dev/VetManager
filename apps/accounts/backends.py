from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied

from . import lockout


class LockoutModelBackend(ModelBackend):
    """
    ModelBackend com bloqueio após tentativas falhas.

    Vale para o login JWT (/api/v1/token/) e para o /admin, pois ambos
    passam por django.contrib.auth.authenticate().
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)

        ip = lockout.get_client_ip(request)

        if lockout.is_locked(username, ip):
            # PermissionDenied interrompe a cadeia de backends; o usuário
            # recebe a mesma mensagem genérica de credenciais inválidas.
            raise PermissionDenied("Muitas tentativas de login. Tente mais tarde.")

        user = super().authenticate(request, username=username, password=password, **kwargs)

        if user is None:
            if username:
                lockout.register_failure(username, ip)
        else:
            lockout.reset(username, ip)
        return user
