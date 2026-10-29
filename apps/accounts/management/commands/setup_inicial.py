import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.accounts.roles import GRUPO_ADMIN, GRUPO_RECEPCAO, GRUPOS_PADRAO


class Command(BaseCommand):
    help = (
        "Garante os grupos padrão (admin, veterinario, recepcao) e cria os "
        "usuários iniciais definidos nas variáveis de ambiente."
    )

    def handle(self, *args, **options):
        self._criar_grupos()
        self._criar_superusuario()
        self._criar_usuario_recepcao()
        self._vincular_superusuarios_ao_grupo_admin()

    def _criar_grupos(self):
        for nome in GRUPOS_PADRAO:
            _, criado = Group.objects.get_or_create(name=nome)
            if criado:
                self.stdout.write(self.style.SUCCESS(f"Grupo criado: {nome}"))
            else:
                self.stdout.write(f"Grupo já existe: {nome}")

    def _criar_superusuario(self):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not username or not password:
            return

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Superusuário já existe: {username}")
            return

        User.objects.create_superuser(
            username,
            os.environ.get("DJANGO_SUPERUSER_EMAIL", ""),
            password,
        )
        self.stdout.write(self.style.SUCCESS(f"Superusuário criado: {username}"))

    def _criar_usuario_recepcao(self):
        username = os.environ.get("DJANGO_RECEPCAO_USERNAME", "").strip()
        password = os.environ.get("DJANGO_RECEPCAO_PASSWORD", "")
        if not username or not password:
            return

        User = get_user_model()
        user, criado = User.objects.get_or_create(
            username=username,
            defaults={"email": os.environ.get("DJANGO_RECEPCAO_EMAIL", "")},
        )

        if criado:
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(
                self.style.SUCCESS(f"Usuário de recepção criado: {username}")
            )
        else:
            self.stdout.write(f"Usuário de recepção já existe: {username}")

        # Garante o perfil mesmo em usuários criados antes dos grupos existirem.
        user.groups.add(Group.objects.get(name=GRUPO_RECEPCAO))

    def _vincular_superusuarios_ao_grupo_admin(self):
        """
        Superusuário já passa por qualquer role_policy, mas o frontend se
        orienta pelos grupos do token. Sem isso o /admin aparece com
        "sem perfil" e menus podem ficar escondidos.
        """
        User = get_user_model()
        grupo_admin = Group.objects.get(name=GRUPO_ADMIN)
        for user in User.objects.filter(is_superuser=True):
            if not user.groups.filter(name=GRUPO_ADMIN).exists():
                user.groups.add(grupo_admin)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Superusuário vinculado ao grupo admin: {user.username}"
                    )
                )
