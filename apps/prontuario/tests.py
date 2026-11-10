"""Testes do prontuário clínico: criação, RBAC e ordenação."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.pets.models import Especie, Pet
from apps.prontuario.models import Prontuario, Vacina
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional, Veterinario

User = get_user_model()


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class ProntuarioTestCase(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_pront", "admin")
        self.vet_user = fazer_usuario("vet_pront", "veterinario")
        self.recepcao = fazer_usuario("rec_pront", "recepcao")

        self.tutor = Tutor.objects.create(
            nome="Tutor Prontuário", telefone="11 99999-3333"
        )
        self.especie = Especie.objects.create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, especie=self.especie, nome="Rex Prontuário"
        )

        self.profissional = Profissional.objects.create(
            nome="Dra. Prontuário", cargo="Veterinário"
        )
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional, crmv="CRMV-PRONT-1"
        )
        self.tosador = Profissional.objects.create(
            nome="Tosador Prontuário", cargo="tosador"
        )

        self.client = APIClient()
        self.client.force_authenticate(self.vet_user)

    def criar_prontuario(self, **dados):
        payload = {
            "pet": str(self.pet.id),
            "veterinario": str(self.veterinario.id),
            "data_consulta": timezone.now().isoformat(),
            "diagnostico": "Animal saudável.",
        }
        payload.update(dados)
        return self.client.post("/api/v1/prontuarios/", payload, format="json")


class ProntuarioCriacaoTests(ProntuarioTestCase):
    def test_veterinario_cria_prontuario(self):
        response = self.criar_prontuario()
        self.assertEqual(response.status_code, 201, response.data)
        prontuario = Prontuario.objects.get(pk=response.data["id"])
        self.assertEqual(prontuario.pet, self.pet)
        self.assertEqual(response.data["pet_nome"], self.pet.nome)
        self.assertEqual(response.data["vacinas"], [])

    def test_profissional_nao_veterinario_e_rejeitado(self):
        response = self.criar_prontuario(veterinario=str(self.tosador.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("veterinario", response.data)

    def test_recepcao_nao_pode_listar_nem_criar_prontuario(self):
        self.client.force_authenticate(self.recepcao)
        self.assertEqual(
            self.client.get("/api/v1/prontuarios/").status_code, 403
        )
        self.assertEqual(self.criar_prontuario().status_code, 403)

    def test_admin_pode_criar_prontuario(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.criar_prontuario().status_code, 201)


class ProntuarioLeituraTests(ProntuarioTestCase):
    def test_listagem_ordena_pela_consulta_mais_recente(self):
        antigo = Prontuario.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now() - timedelta(days=10),
        )
        recente = Prontuario.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
        )
        response = self.client.get("/api/v1/prontuarios/")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.data["results"]]
        self.assertEqual(ids[:2], [str(recente.id), str(antigo.id)])

    def test_detalhe_inclui_vacinas_do_animal(self):
        prontuario = Prontuario.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
        )
        Vacina.objects.create(
            pet=self.pet,
            prontuario=prontuario,
            nome_vacina="V10",
            data_aplicacao=timezone.localdate() - timedelta(days=1),
        )
        response = self.client.get(f"/api/v1/prontuarios/{prontuario.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["vacinas"]), 1)
        self.assertEqual(response.data["vacinas"][0]["nome_vacina"], "V10")

    def test_filtro_por_pet_nao_retorna_prontuario_de_outro_animal(self):
        outro_tutor = Tutor.objects.create(
            nome="Outro Tutor", telefone="11 98888-4444"
        )
        outro_pet = Pet.objects.create(
            tutor=outro_tutor, especie=self.especie, nome="Outro Pet"
        )
        meu = Prontuario.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
        )
        Prontuario.objects.create(
            pet=outro_pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
        )
        response = self.client.get(
            "/api/v1/prontuarios/", {"pet": str(self.pet.id)}
        )
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(meu.id)})
