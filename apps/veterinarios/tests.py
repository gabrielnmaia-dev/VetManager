"""Testes de integridade do vínculo Profissional <-> Veterinário (CRMV).

Cobrem o bug que impedia criar prontuários: era possível cadastrar um
profissional com cargo "Veterinário" sem registro de ``Veterinario`` (e sem
CRMV), ficando de fora dos seletores clínicos; além disso, a criação podia
deixar um profissional órfão quando o CRMV era omitido.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Profissional, Veterinario

User = get_user_model()

GRUPO_ADMIN = "admin"
GRUPO_VET = "veterinario"
GRUPO_REC = "recepcao"


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class ProfissionalVeterinarioWriteTests(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_vet", GRUPO_ADMIN)
        self.vet = fazer_usuario("vet_vet", GRUPO_VET)
        self.rec = fazer_usuario("rec_vet", GRUPO_REC)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _criar(self, **dados):
        payload = {"nome": "Dr. Teste", "cargo": "Veterinário"}
        payload.update(dados)
        return self.client.post("/api/v1/profissionais/", payload, format="json")

    # ----- criação -----
    def test_criar_veterinario_sem_crmv_e_rejeitado_sem_orfao(self):
        antes = Profissional.objects.count()
        resp = self._criar()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("crmv", resp.json())
        self.assertEqual(Profissional.objects.count(), antes)

    def test_criar_veterinario_com_crmv_cria_vinculo(self):
        resp = self._criar(crmv="CRMV-100", especialidade="Clínica")
        self.assertEqual(resp.status_code, 201)
        profissional = Profissional.objects.get(id=resp.json()["id"])
        self.assertEqual(profissional.veterinario.crmv, "CRMV-100")
        self.assertEqual(profissional.veterinario.especialidade, "Clínica")
        self.assertEqual(resp.json()["veterinario"]["crmv"], "CRMV-100")

    def test_criar_tosador_com_crmv_e_rejeitado(self):
        resp = self._criar(nome="Tosador", cargo="tosador", crmv="CRMV-101")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("crmv", resp.json())

    def test_crmv_duplicado_e_rejeitado(self):
        self.assertEqual(self._criar(crmv="CRMV-102").status_code, 201)
        resp = self._criar(nome="Outro Vet", crmv="CRMV-102")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("crmv", resp.json())

    # ----- edição -----
    def test_editar_profissional_legado_adiciona_crmv(self):
        """Profissional antigo sem vínculo pode ser corrigido pela edição."""
        legado = Profissional.objects.create(nome="Legado", cargo="Veterinário")
        resp = self.client.patch(
            f"/api/v1/profissionais/{legado.id}/",
            {"crmv": "CRMV-103"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        legado.refresh_from_db()
        self.assertEqual(legado.veterinario.crmv, "CRMV-103")

    def test_editar_veterinario_atualiza_crmv_e_especialidade(self):
        prof = Profissional.objects.create(nome="Vet", cargo="Veterinário")
        Veterinario.objects.create(profissional=prof, crmv="CRMV-104")
        resp = self.client.patch(
            f"/api/v1/profissionais/{prof.id}/",
            {"crmv": "CRMV-105", "especialidade": "Cirurgia"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        prof.refresh_from_db()
        self.assertEqual(prof.veterinario.crmv, "CRMV-105")
        self.assertEqual(prof.veterinario.especialidade, "Cirurgia")

    def test_editar_sem_crmv_mantem_valor_existente(self):
        prof = Profissional.objects.create(nome="Vet", cargo="Veterinário")
        Veterinario.objects.create(profissional=prof, crmv="CRMV-106")
        resp = self.client.patch(
            f"/api/v1/profissionais/{prof.id}/",
            {"telefone": "11 90000-0000"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        prof.refresh_from_db()
        self.assertEqual(prof.veterinario.crmv, "CRMV-106")

    def test_mudar_cargo_de_veterinario_com_vinculo_e_rejeitado(self):
        prof = Profissional.objects.create(nome="Vet", cargo="Veterinário")
        Veterinario.objects.create(profissional=prof, crmv="CRMV-107")
        resp = self.client.patch(
            f"/api/v1/profissionais/{prof.id}/",
            {"cargo": "tosador"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cargo", resp.json())
        prof.refresh_from_db()
        self.assertEqual(prof.cargo, "Veterinário")

    # ----- endpoint direto de veterinários -----
    def test_criar_veterinario_direto(self):
        prof = Profissional.objects.create(nome="Vet Direto", cargo="Veterinário")
        resp = self.client.post(
            "/api/v1/veterinarios/",
            {"profissional": str(prof.id), "crmv": "CRMV-108"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Veterinario.objects.filter(crmv="CRMV-108").exists())

    def test_criar_veterinario_direto_para_nao_veterinario_e_rejeitado(self):
        prof = Profissional.objects.create(nome="Banhista", cargo="banhista")
        resp = self.client.post(
            "/api/v1/veterinarios/",
            {"profissional": str(prof.id), "crmv": "CRMV-109"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    # ----- exclusão -----
    def test_excluir_profissional_desativa_vinculo_veterinario(self):
        """Exclusão lógica do profissional não pode deixar veterinário ativo."""
        resp = self._criar(nome="Vet Excluir", crmv="CRMV-120")
        self.assertEqual(resp.status_code, 201)
        prof_id = resp.json()["id"]
        vet_id = resp.json()["veterinario"]["id"]

        del_resp = self.client.delete(f"/api/v1/profissionais/{prof_id}/")
        self.assertEqual(del_resp.status_code, 204)
        self.assertFalse(Veterinario.objects.filter(id=vet_id).exists())

        listados = self.client.get("/api/v1/veterinarios/").json()
        ids = [v["id"] for v in listados.get("results", listados)]
        self.assertNotIn(vet_id, ids)

    def test_veterinario_de_profissional_excluido_nao_aparece(self):
        prof = Profissional.objects.create(nome="Vet Sumiu", cargo="Veterinário")
        vet = Veterinario.objects.create(profissional=prof, crmv="CRMV-121")
        prof.delete(user=self.admin)
        listados = self.client.get("/api/v1/veterinarios/").json()
        ids = [v["id"] for v in listados.get("results", listados)]
        self.assertNotIn(str(vet.id), ids)

    # ----- RBAC -----
    def test_recepcao_pode_listar_veterinarios_mas_nao_criar(self):
        self.client.force_authenticate(self.rec)
        self.assertEqual(
            self.client.get("/api/v1/veterinarios/").status_code, 200
        )
        prof = Profissional.objects.create(nome="Vet RBAC", cargo="Veterinário")
        resp = self.client.post(
            "/api/v1/veterinarios/",
            {"profissional": str(prof.id), "crmv": "CRMV-110"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_veterinario_pode_listar_mas_nao_criar_veterinarios(self):
        self.client.force_authenticate(self.vet)
        self.assertEqual(self.client.get("/api/v1/veterinarios/").status_code, 200)
        prof = Profissional.objects.create(nome="Vet RBAC 2", cargo="Veterinário")
        resp = self.client.post(
            "/api/v1/veterinarios/",
            {"profissional": str(prof.id), "crmv": "CRMV-111"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
