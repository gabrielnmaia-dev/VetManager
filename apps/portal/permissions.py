from rest_framework.permissions import BasePermission


class IsPortalAuthenticated(BasePermission):
    """Exige uma sessão de portal válida (não basta estar logado no interno)."""

    message = "Autenticação do portal do tutor necessária."

    def has_permission(self, request, view):
        return bool(
            getattr(request, "portal_acesso", None) is not None
            and request.user is not None
            and request.user.is_authenticated
        )
