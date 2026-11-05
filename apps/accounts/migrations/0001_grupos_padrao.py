"""
Cria os grupos padrão do RBAC em qualquer banco (inclusive produção).

Antes desta migration os grupos só existiam se alguém os criasse manualmente
no /admin — por isso a tela de grupos ficava vazia após o deploy.
"""

from django.db import migrations

GRUPOS_PADRAO = ("admin", "veterinario", "recepcao")


def criar_grupos(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nome in GRUPOS_PADRAO:
        Group.objects.get_or_create(name=nome)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        # Reverter não deve apagar grupos: isso removeria as permissões dos
        # usuários já cadastrados. A operação é idempotente e segura de repetir.
        migrations.RunPython(criar_grupos, migrations.RunPython.noop),
    ]
