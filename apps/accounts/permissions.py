"""
RBAC simples baseado em grupos do Django (ex.: "admin", "veterinario").

Uso em uma view/viewset:

    role_policy = ("admin", "veterinario")          # vale para todas as ações

    role_policy = {                                 # por ação/método
        "list": ("admin", "veterinario", "recepcao"),
        "retrieve": ("admin", "veterinario", "recepcao"),
        "*": ("admin",),                            # demais ações
    }

Views SEM `role_policy` não são restringidas por esta classe (continuam
protegidas por IsAuthenticated). Superusuários sempre têm acesso.
"""

from rest_framework.permissions import BasePermission


def _required_roles(request, view):
    policy = getattr(view, "role_policy", None)
    if policy is None:
        return None
    if isinstance(policy, dict):
        action = getattr(view, "action", None)
        for key in (action, request.method.upper(), "*"):
            if key and key in policy:
                return policy[key]
        # Ação não listada e sem "*": nega.
        return ()
    return policy


class RoleBasedPermission(BasePermission):
    message = "Acesso restrito."

    def has_permission(self, request, view):
        roles = _required_roles(request, view)
        if roles is None:
            return True

        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if not roles:
            return False
        return user.groups.filter(name__in=list(roles)).exists()
