"""Testes do modelo e API de medições de sinais vitais (MedicaoVital)."""

from decimal import Decimal
from datetime import datetime, timezone as dt_timezone, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from apps.pets.models import MedicaoVital, Pet, Especie
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional

User = get_user_model()


def fazer_usuario(username, grupo, senha="senha123"):
    user = User.objects.create_user(username=username, password=senha)
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


def autenticar(client, user):
    client.force_authenticate(user)
    return client


class MedicaoVitalTests(TestCase):
    """Testes de criação, validação, filtros e ordenação de medições vitais."""

    def setUp(self):
        self.admin = fazer_usuario("admin_mv", "admin")
        self.vet = fazer_usuario("vet_mv", "veterinario")
        self.rec = fazer_usuario("rec_mv", "recepcao")
        self.client = APIClient()

        # Cenário: pet com tutor
        self.tutor = Tutor.objects.create(nome="Tutor Teste", telefone="11 99999-9999")
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor,
            nome="Rex",
            especie=self.especie,
        )
        self.prof = Profissional.objects.create(
            nome="Dr. Vet Teste", cargo="Veterinário"
        )

        # Medições existentes para testes de ordenação e filtro
        self.m1 = MedicaoVital.objects.create(
            pet=self.pet,
            profissional=self.prof,
            data_hora=datetime(2026, 10, 1, 9, 0, tzinfo=dt_timezone.utc),
            peso=10.0,
            temperatura=38.5,
        )
        self.m2 = MedicaoVital.objects.create(
            pet=self.pet,
            profissional=self.prof,
            data_hora=datetime(2026, 10, 15, 10, 0, tzinfo=dt_timezone.utc),
            peso=10.5,
            temperatura=39.0,
            frequencia_cardíaca=100,
        )
        self.m3 = MedicaoVital.objects.create(
            pet=self.pet,
            profissional=self.prof,
            data_hora=datetime(2026, 10, 20, 11, 0, tzinfo=dt_timezone.utc),
            peso=11.0,
            frequencia_respiratoria=20,
            observacoes="Melhora clínica.",
        )

    def test_criacao_medicao_vital(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        data_hora = "2026-11-01T09:00:00Z"
        payload = {
            "pet": str(self.pet.id),
            "profissional": str(self.prof.id),
            "data_hora": data_hora,
            "peso": "12.00",
            "temperatura": "38.8",
        }
        resp = self.client.post("/api/v1/medicoes-vitais/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(MedicaoVital.objects.count(), 4)
        mv = MedicaoVital.objects.get(peso=12.00)
        self.assertEqual(mv.pet, self.pet)
        self.assertEqual(mv.profissional, self.prof)
        self.assertEqual(mv.temperatura, Decimal("38.8"))

    def test_cria_somente_com_campo_opcional(self):
        """Não é obrigatório preencher todos os parâmetros."""
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        payload = {
            "pet": str(self.pet.id),
            "profissional": str(self.prof.id),
            "data_hora": "2026-11-01T09:00:00Z",
            "pressao_arterial": "120/80",
        }
        resp = self.client.post("/api/v1/medicoes-vitais/", payload, format="json")
        self.assertEqual(resp.status_code, 201)
        mv = MedicaoVital.objects.get(pressao_arterial="120/80")
        self.assertIsNone(mv.peso)
        self.assertIsNone(mv.temperatura)

    def test_rejeita_sem_nenhum_parametro_medido(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        payload = {
            "pet": str(self.pet.id),
            "profissional": str(self.prof.id),
            "data_hora": "2026-11-01T09:00:00Z",
        }
        resp = self.client.post("/api/v1/medicoes-vitais/", payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_rejeita_saturacao_fora_do_intervalo(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        payload = {
            "pet": str(self.pet.id),
            "profissional": str(self.prof.id),
            "data_hora": "2026-11-01T09:00:00Z",
            "saturacao": 150,
        }
        resp = self.client.post("/api/v1/medicoes-vitais/", payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_listar_medicoes_vitais(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        resp = self.client.get("/api/v1/medicoes-vitais/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 3)

    def test_filtro_por_pet(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        # Cria outro pet para teste de filtro
        outro_tutor = Tutor.objects.create(nome="Outro Tutor", telefone="11 88888-8888")
        outro_pet = Pet.objects.create(
            tutor=outro_tutor, nome="Miau", especie=self.especie
        )
        MedicaoVital.objects.create(
            pet=outro_pet,
            profissional=self.prof,
            data_hora=datetime(2026, 10, 25, 9, 0, tzinfo=dt_timezone.utc),
            peso=5.0,
        )

        resp = self.client.get("/api/v1/medicoes-vitais/", {"pet": str(self.pet.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 3)
        self.assertTrue(
            all(r["pet"] == str(self.pet.id) for r in resp.json()["results"])
        )

    def test_filtro_por_periodo(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        resp = self.client.get(
            "/api/v1/medicoes-vitais/",
            {
                "data_inicio": "2026-10-10",
                "data_fim": "2026-10-20",
            },
        )
        self.assertEqual(resp.status_code, 200)
        # Apenas a medição de 15/10 (dentro do período)
        self.assertEqual(len(resp.json()["results"]), 1)
        self.assertEqual(resp.json()["results"][0]["peso"], "10.50")

    def test_ordenacao_cronologica_decrescente(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        resp = self.client.get("/api/v1/medicoes-vitais/")
        self.assertEqual(resp.status_code, 200)
        resultados = resp.json()["results"]
        datas = [r["data_hora"] for r in resultados]
        self.assertEqual(datas, sorted(datas, reverse=True))

    def test_ultima_medicao(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        resp = self.client.get(
            "/api/v1/medicoes-vitais/ultima/", {"pet": str(self.pet.id)}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["peso"], "11.00")
        self.assertEqual(resp.json()["observacoes"], "Melhora clínica.")

    def test_ultima_medicao_sem_pet(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        resp = self.client.get("/api/v1/medicoes-vitais/ultima/")
        self.assertEqual(resp.status_code, 400)

    def test_nao_autenticado_negado(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/medicoes-vitais/")
        self.assertEqual(resp.status_code, 401)

    def test_recepcao_pode_listar(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        resp = self.client.get("/api/v1/medicoes-vitais/")
        self.assertEqual(resp.status_code, 200)


User = get_user_model()
