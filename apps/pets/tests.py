"""Testes do app pets: catálogos, cadastro, validações e exclusão lógica."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.tutores.models import Tutor

from .models import Especie, HistoricoResponsabilidadePet, Pet, Raca

User = get_user_model()


def fazer_usuario(username, grupo="recepcao"):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class PetApiTestCase(TestCase):
    def setUp(self):
        self.user = fazer_usuario("recepcao_pets")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.especie_cao = Especie.objects.create(nome="Cão")
        self.especie_gato = Especie.objects.create(nome="Gato")
        self.raca_srd = Raca.objects.create(especie=self.especie_cao, nome="SRD")
        self.raca_siames = Raca.objects.create(
            especie=self.especie_gato, nome="Siamês"
        )

        self.tutor = Tutor.objects.create(
            nome="Ana Pets", telefone="11 99999-1111"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Bruno Pets", telefone="11 99999-2222"
        )
        self.pet = Pet.objects.create(
            tutor=self.tutor,
            especie=self.especie_cao,
            raca=self.raca_srd,
            nome="Rex",
        )
        self.outro_pet = Pet.objects.create(
            tutor=self.outro_tutor,
            especie=self.especie_gato,
            raca=self.raca_siames,
            nome="Mia",
        )


class PetCadastroTests(PetApiTestCase):
    def test_criar_pet_registra_autoria_e_idade_calculada(self):
        nascimento = timezone.localdate() - timedelta(days=365 * 3 + 2)
        response = self.client.post(
            "/api/v1/pets/",
            {
                "tutor": str(self.tutor.id),
                "especie": str(self.especie_cao.id),
                "raca": str(self.raca_srd.id),
                "nome": "Bolt",
                "sexo": "M",
                "data_nascimento": nascimento.isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        pet = Pet.objects.get(pk=response.data["id"])
        self.assertEqual(pet.created_by, self.user)
        self.assertEqual(response.data["idade_calculada"], 3)

    def test_raca_de_outra_especie_e_rejeitada(self):
        response = self.client.post(
            "/api/v1/pets/",
            {
                "tutor": str(self.tutor.id),
                "especie": str(self.especie_cao.id),
                "raca": str(self.raca_siames.id),
                "nome": "Pet Invalido",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("raca", response.data)

    def test_idade_calculada_nao_fica_negativa_para_data_futura(self):
        pet = Pet.objects.create(
            tutor=self.tutor,
            especie=self.especie_cao,
            nome="Filhote",
            data_nascimento=timezone.localdate() + timedelta(days=30),
        )
        self.assertEqual(pet.idade_calculada, 0)

    def test_pet_sem_data_de_nascimento_nao_tem_idade_calculada(self):
        self.assertIsNone(self.pet.idade_calculada)

    def test_listagem_filtra_por_tutor_e_busca_por_nome(self):
        response = self.client.get(
            "/api/v1/pets/", {"tutor": str(self.outro_tutor.id)}
        )
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(self.outro_pet.id)})

        response = self.client.get("/api/v1/pets/", {"search": "Rex"})
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(self.pet.id)})


class PetHistoricoResponsabilidadeTests(PetApiTestCase):
    def test_endpoint_de_historico_retorna_responsaveis_do_pet(self):
        HistoricoResponsabilidadePet.objects.create(
            pet=self.pet,
            tutor=self.tutor,
            data_inicio=timezone.localdate() - timedelta(days=10),
        )
        response = self.client.get(
            f"/api/v1/pets/{self.pet.id}/historico-responsaveis/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["tutor_nome"], self.tutor.nome)
        self.assertIsNone(response.data[0]["data_fim"])

    def test_historico_de_outro_pet_nao_vaza_na_listagem(self):
        HistoricoResponsabilidadePet.objects.create(
            pet=self.pet, tutor=self.tutor
        )
        HistoricoResponsabilidadePet.objects.create(
            pet=self.outro_pet, tutor=self.outro_tutor
        )
        response = self.client.get(
            "/api/v1/historicos-responsabilidade-pet/",
            {"pet": str(self.outro_pet.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["pet"], self.outro_pet.id
        )


class PetExclusaoLogicaTests(PetApiTestCase):
    def test_delete_marca_exclusao_logica_e_preserva_registro(self):
        response = self.client.delete(f"/api/v1/pets/{self.pet.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Pet.objects.filter(pk=self.pet.pk).exists())
        registro = Pet.all_objects.get(pk=self.pet.pk)
        self.assertTrue(registro.is_deleted)
        self.assertEqual(registro.deleted_by, self.user)

    def test_pet_excluido_nao_aparece_na_listagem(self):
        self.pet.delete()
        response = self.client.get("/api/v1/pets/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertNotIn(str(self.pet.id), ids)
        self.assertIn(str(self.outro_pet.id), ids)


class CatalogosPetTests(PetApiTestCase):
    def test_especies_ativas_retorna_somente_ativas(self):
        Especie.objects.create(nome="Ave", ativo=False)
        response = self.client.get("/api/v1/especies/ativas/")
        self.assertEqual(response.status_code, 200)
        nomes = {item["nome"] for item in response.data}
        self.assertEqual(nomes, {"Cão", "Gato"})

    def test_racas_ativas_filtram_por_especie(self):
        response = self.client.get(
            "/api/v1/racas/ativas/", {"especie": str(self.especie_gato.id)}
        )
        self.assertEqual(response.status_code, 200)
        nomes = {item["nome"] for item in response.data}
        self.assertEqual(nomes, {"Siamês"})

    def test_raca_duplicada_na_mesma_especie_e_rejeitada(self):
        response = self.client.post(
            "/api/v1/racas/",
            {
                "especie": str(self.especie_cao.id),
                "nome": "srd",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("nome", response.data)
