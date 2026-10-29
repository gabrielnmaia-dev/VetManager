import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()

URL_PRONTUARIOS = "/api/v1/prontuarios/"


class GruposPadraoTests(TestCase):
    """Os grupos precisam existir no banco desde o deploy (migration)."""

    def test_migration_cria_grupos_padrao(self):
        for nome in ("admin", "veterinario", "recepcao"):
            self.assertTrue(
                Group.objects.filter(name=nome).exists(),
                f"grupo {nome!r} não foi criado pela migration",
            )

    def test_setup_inicial_e_idempotente(self):
        call_command("setup_inicial", stdout=StringIO())
        call_command("setup_inicial", stdout=StringIO())

        self.assertEqual(
            Group.objects.filter(
                name__in=["admin", "veterinario", "recepcao"]
            ).count(),
            3,
        )

    @patch.dict(
        os.environ,
        {
            "DJANGO_RECEPCAO_USERNAME": "atendente",
            "DJANGO_RECEPCAO_PASSWORD": "senha-super-secreta-123",
            "DJANGO_RECEPCAO_EMAIL": "atendente@vetmanager.local",
        },
    )
    def test_setup_inicial_cria_usuario_de_recepcao_no_grupo(self):
        call_command("setup_inicial", stdout=StringIO())

        user = User.objects.get(username="atendente")
        self.assertTrue(user.check_password("senha-super-secreta-123"))
        self.assertTrue(user.groups.filter(name="recepcao").exists())

    def test_setup_inicial_vincula_superusuario_ao_grupo_admin(self):
        superuser = User.objects.create_superuser(
            username="root", email="root@vetmanager.local", password="x"
        )

        call_command("setup_inicial", stdout=StringIO())

        self.assertTrue(superuser.groups.filter(name="admin").exists())


class LoginJwtTests(TestCase):
    def test_login_de_atendente_devolve_grupo_recepcao(self):
        user = User.objects.create_user(
            username="atendente", password="senha-super-secreta-123"
        )
        user.groups.add(Group.objects.get(name="recepcao"))

        response = self.client.post(
            "/api/v1/token/",
            {"username": "atendente", "password": "senha-super-secreta-123"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["groups"], ["recepcao"])


class ProntuarioPermissaoTests(TestCase):
    """Prontuários continuam restritos a admin/veterinário (recepção não vê)."""

    def setUp(self):
        self.client = APIClient()

    def criar_usuario(self, username, grupo=None):
        user = User.objects.create_user(
            username=username, password="senha-super-secreta-123"
        )
        if grupo:
            user.groups.add(Group.objects.get(name=grupo))
        self.client.force_authenticate(user)
        return user

    def test_admin_e_veterinario_acessam_prontuarios(self):
        for grupo in ("admin", "veterinario"):
            self.criar_usuario(f"usuario-{grupo}", grupo)
            response = self.client.get(URL_PRONTUARIOS)
            self.assertEqual(response.status_code, 200, grupo)

    def test_recepcao_nao_acessa_prontuarios(self):
        self.criar_usuario("atendente", "recepcao")
        response = self.client.get(URL_PRONTUARIOS)
        self.assertEqual(response.status_code, 403)

    def test_usuario_sem_grupo_nao_acessa_prontuarios(self):
        self.criar_usuario("sem-grupo")
        response = self.client.get(URL_PRONTUARIOS)
        self.assertEqual(response.status_code, 403)
