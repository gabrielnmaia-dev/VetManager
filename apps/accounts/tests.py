import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
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


URL_PERFIL = "/api/v1/perfil/"
URL_ALTERAR_SENHA = "/api/v1/perfil/alterar-senha/"

SENHA_ATUAL = "senha-super-secreta-123"
SENHA_NOVA = "senha-nova-super-456"


class PerfilTests(TestCase):
    """GET/PATCH do próprio perfil (nome, e-mail) e campos protegidos."""

    def setUp(self):
        cache.clear()  # evita throttling acumulado entre testes
        self.user = User.objects.create_user(
            username="atendente",
            password=SENHA_ATUAL,
            first_name="Ana",
            last_name="Souza",
            email="ana@vetmanager.local",
        )
        self.user.groups.add(Group.objects.get(name="recepcao"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_exige_autenticacao(self):
        self.assertEqual(APIClient().get(URL_PERFIL).status_code, 401)

    def test_get_devolve_dados_do_usuario_logado(self):
        response = self.client.get(URL_PERFIL)

        self.assertEqual(response.status_code, 200)
        dados = response.json()
        self.assertEqual(dados["username"], "atendente")
        self.assertEqual(dados["first_name"], "Ana")
        self.assertEqual(dados["groups"], ["recepcao"])
        self.assertNotIn("password", dados)

    def test_patch_atualiza_nome_e_email(self):
        response = self.client.patch(
            URL_PERFIL,
            {"first_name": "Marina", "email": "marina@vetmanager.local"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Marina")
        self.assertEqual(self.user.last_name, "Souza")
        self.assertEqual(self.user.email, "marina@vetmanager.local")

    def test_patch_ignora_campos_protegidos(self):
        response = self.client.patch(
            URL_PERFIL,
            {
                "username": "outro-usuario",
                "is_staff": True,
                "is_superuser": True,
                "groups": ["admin"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "atendente")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
        self.assertEqual(
            list(self.user.groups.values_list("name", flat=True)), ["recepcao"]
        )


class AlterarSenhaTests(TestCase):
    """Troca de senha exige a senha atual e revoga os tokens antigos."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="atendente", password=SENHA_ATUAL
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def alterar(self, senha_atual=SENHA_ATUAL, nova=SENHA_NOVA, confirmar=None):
        return self.client.post(
            URL_ALTERAR_SENHA,
            {
                "senha_atual": senha_atual,
                "nova_senha": nova,
                "confirmar_nova_senha": nova if confirmar is None else confirmar,
            },
            format="json",
        )

    def test_exige_autenticacao(self):
        response = APIClient().post(URL_ALTERAR_SENHA, {}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_senha_atual_incorreta_nao_altera(self):
        response = self.alterar(senha_atual="senha-errada-000")

        self.assertEqual(response.status_code, 400)
        self.assertIn("senha_atual", response.json())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(SENHA_ATUAL))

    def test_confirmacao_diferente_nao_altera(self):
        response = self.alterar(confirmar="outra-senha-qualquer-789")

        self.assertEqual(response.status_code, 400)
        self.assertIn("confirmar_nova_senha", response.json())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(SENHA_ATUAL))

    def test_senha_fraca_e_rejeitada_pelos_validadores(self):
        response = self.alterar(nova="123456", confirmar="123456")

        self.assertEqual(response.status_code, 400)
        self.assertIn("nova_senha", response.json())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(SENHA_ATUAL))

    def test_nova_senha_igual_a_atual_e_rejeitada(self):
        response = self.alterar(nova=SENHA_ATUAL)

        self.assertEqual(response.status_code, 400)
        self.assertIn("nova_senha", response.json())

    def test_altera_senha_e_revoga_refresh_token_antigo(self):
        login = APIClient().post(
            "/api/v1/token/",
            {"username": "atendente", "password": SENHA_ATUAL},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        refresh_antigo = login.json()["refresh"]

        response = self.alterar()

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(SENHA_NOVA))
        self.assertFalse(self.user.check_password(SENHA_ATUAL))

        # O refresh emitido antes da troca deixa de valer...
        antigo = APIClient().post(
            "/api/v1/token/refresh/", {"refresh": refresh_antigo}, format="json"
        )
        self.assertEqual(antigo.status_code, 401)

        # ...e o par devolvido na resposta funciona.
        dados = response.json()
        self.assertIn("access", dados)
        self.assertIn("refresh", dados)
        novo = APIClient().post(
            "/api/v1/token/refresh/", {"refresh": dados["refresh"]}, format="json"
        )
        self.assertEqual(novo.status_code, 200)

    def test_login_com_a_nova_senha(self):
        self.assertEqual(self.alterar().status_code, 200)

        response = APIClient().post(
            "/api/v1/token/",
            {"username": "atendente", "password": SENHA_NOVA},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

