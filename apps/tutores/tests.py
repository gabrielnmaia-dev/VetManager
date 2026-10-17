from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.pets.models import Pet

from .models import Tutor
from .services import criar_tutor_com_pets

User = get_user_model()


class TutorApiTestCase(TestCase):
    """Base com usuário autenticado (os endpoints exigem IsAuthenticated)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="recepcao", password="senha-super-secreta-123"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def criar_tutor(self, nome, telefone, cpf="", pets=()):
        tutor = Tutor.objects.create(nome=nome, telefone=telefone, cpf=cpf)
        for pet in pets:
            Pet.objects.create(tutor=tutor, **pet)
        return tutor


class TutorListComPetsTests(TutorApiTestCase):
    def test_lista_retorna_pets_aninhados_sem_queries_extras(self):
        for i in range(3):
            self.criar_tutor(
                nome=f"Tutor {i}",
                telefone=f"11 99999-000{i}",
                pets=[
                    {"nome": f"Pet {i}A", "especie": "Cao", "raca": "SRD"},
                    {"nome": f"Pet {i}B", "especie": "Gato", "raca": "Siames"},
                ],
            )

        # 3 queries = count da paginacao + pagina + prefetch de pets.
        # Sem prefetch seriam 3 + 1 query por tutor (N+1).
        with self.assertNumQueries(3):
            response = self.client.get("/api/v1/tutores/")

        self.assertEqual(response.status_code, 200)
        resultados = response.json()["results"]
        self.assertEqual(len(resultados), 3)

        tutor0 = next(r for r in resultados if r["nome"] == "Tutor 0")
        self.assertCountEqual(
            [p["nome"] for p in tutor0["pets"]], ["Pet 0A", "Pet 0B"]
        )
        for pet in tutor0["pets"]:
            self.assertEqual(
                sorted(pet.keys()), ["especie", "id", "nome", "raca"]
            )

    def test_lista_com_dois_tutores_mantem_num_queries_estavel(self):
        """Garante que o numero de queries nao cresce com a quantidade de tutores."""
        self.criar_tutor(
            nome="Ana",
            telefone="11 91111-1111",
            pets=[{"nome": "Bidu", "especie": "Cao"}],
        )
        self.criar_tutor(nome="Bruno", telefone="11 92222-2222")

        with self.assertNumQueries(3):
            response = self.client.get("/api/v1/tutores/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 2)
        bruno = next(
            r for r in response.json()["results"] if r["nome"] == "Bruno"
        )
        self.assertEqual(bruno["pets"], [])

    def test_retrieve_retorna_pets_aninhados(self):
        tutor = self.criar_tutor(
            nome="Maria Silva",
            telefone="11 98888-7777",
            pets=[{"nome": "Rex", "especie": "Cao", "raca": "Labrador"}],
        )
        rex = tutor.pets.get()

        # get_object + prefetch dos pets = 2 queries.
        with self.assertNumQueries(2):
            response = self.client.get(f"/api/v1/tutores/{tutor.id}/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["nome"], "Maria Silva")
        self.assertEqual(len(data["pets"]), 1)
        self.assertEqual(data["pets"][0]["id"], str(rex.id))
        self.assertEqual(data["pets"][0]["nome"], "Rex")
        self.assertEqual(data["pets"][0]["especie"], "Cao")
        self.assertEqual(data["pets"][0]["raca"], "Labrador")


class TutorSearchTests(TutorApiTestCase):
    def setUp(self):
        super().setUp()
        self.joao = self.criar_tutor(
            nome="Joao Pereira", telefone="11 91234-5678"
        )
        self.ana = self.criar_tutor(nome="Ana Souza", telefone="21 99876-5432")
        self.carlos = Tutor.objects.create(
            nome="Carlos Lima",
            telefone="31 90000-1111",
            cpf="123.456.789-00",
        )

    def test_search_por_nome(self):
        response = self.client.get("/api/v1/tutores/", {"search": "Pereira"})
        self.assertEqual(response.status_code, 200)
        resultados = response.json()["results"]
        self.assertEqual([r["nome"] for r in resultados], ["Joao Pereira"])
        # Mesmo no search, os pets vao aninhados.
        self.assertEqual(resultados[0]["pets"], [])

    def test_search_por_telefone(self):
        response = self.client.get("/api/v1/tutores/", {"search": "99876"})
        self.assertEqual(response.status_code, 200)
        resultados = response.json()["results"]
        self.assertEqual([r["nome"] for r in resultados], ["Ana Souza"])

    def test_search_por_cpf(self):
        response = self.client.get("/api/v1/tutores/", {"search": "123.456"})
        self.assertEqual(response.status_code, 200)
        resultados = response.json()["results"]
        self.assertEqual([r["id"] for r in resultados], [str(self.carlos.id)])


class TutorCreateCascadeTests(TutorApiTestCase):
    """POST /api/v1/tutores/ com payload legado e com cascata de pets."""

    def test_cria_apenas_tutor_payload_legado(self):
        payload = {
            "nome": "Paula Nunes",
            "telefone": "11 95555-4444",
            "email": "paula@example.com",
            "cpf": "987.654.321-00",
        }

        response = self.client.post("/api/v1/tutores/", payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        # Campos do payload legado continuam presentes na resposta.
        for campo in [
            "id",
            "nome",
            "telefone",
            "email",
            "cpf",
            "endereco",
            "criado_em",
            "atualizado_em",
        ]:
            self.assertIn(campo, data)
        self.assertEqual(data["pets"], [])
        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 0)
        self.assertEqual(Tutor.objects.get().email, "paula@example.com")

    def test_cria_tutor_com_um_pet(self):
        payload = {
            "nome": "Ricardo Alves",
            "telefone": "11 96666-7777",
            "pets": [{"nome": "Totoca", "especie": "Cao", "raca": "SRD"}],
        }

        response = self.client.post("/api/v1/tutores/", payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 1)

        pet = Pet.objects.get()
        self.assertEqual(pet.tutor.nome, "Ricardo Alves")
        self.assertEqual(len(data["pets"]), 1)
        self.assertEqual(data["pets"][0]["id"], str(pet.id))
        self.assertEqual(data["pets"][0]["nome"], "Totoca")
        self.assertEqual(data["pets"][0]["especie"], "Cao")
        self.assertEqual(data["pets"][0]["raca"], "SRD")

    def test_cria_tutor_com_dois_pets(self):
        payload = {
            "nome": "Carla Dias",
            "telefone": "11 97777-8888",
            "pets": [
                {"nome": "Pretinha", "especie": "Gato", "raca": "Sem Raca"},
                {"nome": "Mel", "especie": "Cao", "sexo": "F"},
            ],
        }

        response = self.client.post("/api/v1/tutores/", payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 2)
        self.assertEqual(
            {p.tutor_id for p in Pet.objects.all()},
            {Tutor.objects.get().id},
        )
        self.assertEqual(
            sorted(p["nome"] for p in data["pets"]), ["Mel", "Pretinha"]
        )

    def test_pet_invalido_retorna_400_e_nao_cria_nada(self):
        payload = {
            "nome": "Tutor Novo",
            "telefone": "11 90000-1111",
            "pets": [
                {"nome": "Valido", "especie": "Cao"},
                {"nome": "Sem Especie"},  # especie obrigatoria -> 400
            ],
        }

        response = self.client.post("/api/v1/tutores/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        erros = response.json()
        self.assertIn("pets", erros)
        # Erros de lista aninhada sao indexados por posicao (DRF >= 3.15).
        item_invalido = (
            erros["pets"]["1"]
            if isinstance(erros["pets"], dict)
            else erros["pets"][1]
        )
        self.assertEqual(
            item_invalido["especie"], ["Informe a espécie do pet."]
        )
        # Rollback total: nem o tutor nem o pet valido foram criados.
        self.assertEqual(Tutor.objects.count(), 0)
        self.assertEqual(Pet.objects.count(), 0)

    def test_tutor_sem_nome_retorna_400_mensagem_em_portugues(self):
        response = self.client.post(
            "/api/v1/tutores/", {"telefone": "11 91234-0000"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["nome"], ["Informe o nome do tutor."])
        self.assertEqual(Tutor.objects.count(), 0)

    def test_update_continua_no_serializer_original(self):
        """PUT/PATCH não ganharam cascata: segue o TutorSerializer de antes."""
        tutor = self.criar_tutor(nome="Nome Antigo", telefone="11 91111-2222")

        response = self.client.patch(
            f"/api/v1/tutores/{tutor.id}/", {"nome": "Nome Novo"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        tutor.refresh_from_db()
        self.assertEqual(tutor.nome, "Nome Novo")
        self.assertNotIn("pets", response.json())


class TutorServiceRollbackTests(TestCase):
    """Rollback transacional no service (falha em nível de banco)."""

    def test_rollback_quando_segundo_pet_falha(self):
        tutor_data = {"nome": "Rollback", "telefone": "11 90000-0000"}
        pets_data = [
            {"nome": "Primeiro", "especie": "Cao"},
            {"nome": "Segundo", "especie": "Gato"},
        ]

        original_create = Pet.objects.create
        chamadas = {"n": 0}

        def create_que_falha_no_segundo(*args, **kwargs):
            chamadas["n"] += 1
            if chamadas["n"] > 1:
                raise IntegrityError("falha simulada no banco")
            return original_create(*args, **kwargs)

        with patch.object(
            Pet.objects, "create", side_effect=create_que_falha_no_segundo
        ):
            with self.assertRaises(IntegrityError):
                criar_tutor_com_pets(tutor_data, pets_data)

        # O primeiro pet chegou a ser criado e mesmo assim foi desfeito.
        self.assertEqual(chamadas["n"], 2)
        self.assertEqual(Tutor.objects.count(), 0)
        self.assertEqual(Pet.objects.count(), 0)

    def test_cria_tutor_e_pets_quando_nada_falha(self):
        tutor = criar_tutor_com_pets(
            {"nome": "Sucesso", "telefone": "11 91234-9999"},
            [{"nome": "Bela", "especie": "Cao"}],
        )

        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 1)
        self.assertEqual(Pet.objects.get().tutor, tutor)
