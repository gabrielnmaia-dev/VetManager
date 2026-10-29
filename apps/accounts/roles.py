"""
Nomes dos grupos (perfis) usados pelo RBAC.

O frontend recebe esses nomes no login (claim "groups" do JWT) e o backend
usa os mesmos nomes em `role_policy` (ver apps/accounts/permissions.py).
Como o Django não cria grupos sozinho, o deploy roda `setup_inicial` para
garantir que eles existam no banco.
"""

GRUPO_ADMIN = "admin"
GRUPO_VETERINARIO = "veterinario"
GRUPO_RECEPCAO = "recepcao"

# Ordem usada na criação e nos comandos de setup.
GRUPOS_PADRAO = (
    GRUPO_ADMIN,
    GRUPO_VETERINARIO,
    GRUPO_RECEPCAO,
)
