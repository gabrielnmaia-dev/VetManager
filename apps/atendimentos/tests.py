from contextlib import contextmanager
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, connection
from django.db.models import ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from apps.pets.models import Especie, Pet, Raca
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional

from .models import Atendimento
from .services import criar_atendimento_rapido

User = get_user_model()

URL_RAPIDO = "/api/v1/atendimentos/rapido/"
URL_ATENDIMENTOS = "/api/v1/atendimentos/"


class AtendimentoApiTestCase(TestCase):
    """Base com usuário autenticado (os endpoints exigem IsAuthenticated)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="recepcao", password="senha-super-secreta-123"
        )
        from django.contrib.auth.models import Group
        grupo, _ = Group.objects.get_or_create(name="recepcao")
        self.user.groups.add(grupo)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        # Catálogos controlados para pets de teste.
        self.especie_cao, _ = Especie.objects.get_or_create(nome="Cão")
        self.especie_gato, _ = Especie.objects.get_or_create(nome="Gato")
        self.raca_srd, _ = Raca.objects.get_or_create(
            especie=self.especie_cao, nome="SRD"
        )

    def criar_tutor(self, nome="Joana Reis", telefone="11 91111-1111"):
        return Tutor.objects.create(nome=nome, telefone=telefone)

    def criar_pet(self, tutor, nome="Rex", especie=None):
        if especie is None:
            especie = self.especie_cao
        elif isinstance(especie, str):
            especie_obj, _ = Especie.objects.get_or_create(nome=especie)
            especie = especie_obj
        return Pet.objects.create(
            tutor=tutor, nome=nome, especie=especie
        )

    def criar_profissional(self, nome="Dra. Ana Souza", cargo="Veterinário"):
        return Profissional.objects.create(nome=nome, cargo=cargo)

    def criar_atendimento_direto(self, pet, **extra):
        """Cria Atendimento direto no banco (sem HTTP), para montar cenários."""
        dados = {
            "nome_profissional": "Dra. Ana Souza",
            "tipo_servico": "consulta",
            "data_hora_inicio": timezone.make_aware(datetime(2026, 10, 20, 9, 0)),
        }
        dados.update(extra)
        return Atendimento.objects.create(pet=pet, **dados)

    def payload_base(self, **extra):
        dados = {
            "nome_profissional": "Dra. Ana Souza",
            "tipo_servico": "consulta",
            "data_hora_inicio": "2026-10-20T09:00:00Z",
            "queixa": "Vomito desde ontem",
        }
        dados.update(extra)
        return dados

    @contextmanager
    def assertNumQueriesReais(self, esperadas):
        """Conta só queries de dados, ignorando SAVEPOINT/RELEASE gerados
        pelo transaction.atomic (dentro do TestCase o atomic vira savepoint)."""
        with CaptureQueriesContext(connection) as ctx:
            yield
        reais = [
            q["sql"].lstrip().upper()
            for q in ctx.captured_queries
            if not q["sql"].lstrip().upper().startswith(
                ("SAVEPOINT", "RELEASE SAVEPOINT")
            )
        ]
        self.assertEqual(
            len(reais),
            esperadas,
            f"Esperava {esperadas} queries reais, veio {len(reais)}: {reais}",
        )


class AtendimentoRapidoTests(AtendimentoApiTestCase):
    def test_tutor_existente_e_pet_existente(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        payload = self.payload_base(tutor_id=str(tutor.id), pet_id=str(pet.id))

        # busca do tutor + busca do pet (select_related) + insert = 3 queries
        # de dados + 1 query de checagem de grupo do RBAC + 1 query para
        # buscar o nome da espécie no response serializer = 5 totais.
        with self.assertNumQueriesReais(5):
            response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()

        # Respostas com tutor e pet resumidos.
        self.assertEqual(
            data["tutor"],
            {
                "id": str(tutor.id),
                "nome": "Joana Reis",
                "telefone": "11 91111-1111",
                "cpf": "",
            },
        )
        self.assertEqual(
            data["pet"],
            {
                "id": str(pet.id),
                "nome": "Rex",
                "especie": str(self.especie_cao.id),
                "especie_nome": "Cão",
                "raca": None,
            },
        )
        self.assertEqual(data["pet_nome"], "Rex")
        self.assertEqual(data["tutor_nome"], "Joana Reis")

        # Dados do atendimento.
        self.assertEqual(data["nome_profissional"], "Dra. Ana Souza")
        self.assertEqual(data["tipo_servico"], "consulta")
        self.assertEqual(data["tipo_servico_display"], "Consulta")
        self.assertEqual(data["duracao_minutos"], 30)
        self.assertEqual(data["status"], "agendado")
        self.assertEqual(data["queixa"], "Vomito desde ontem")

        # Nada de cascata foi criado.
        self.assertEqual(Atendimento.objects.count(), 1)
        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 1)
        self.assertEqual(Atendimento.objects.get().pet, pet)

    def test_tutor_existente_e_pet_novo(self):
        tutor = self.criar_tutor()
        payload = self.payload_base(
            tutor_id=str(tutor.id),
            pet={
                "nome": "Mel",
                "especie": str(self.especie_cao.id),
                "raca": str(self.raca_srd.id),
                "sexo": "F",
            },
        )

        # busca do tutor + validação da espécie + validação da raça +
        # insert do pet + insert do atendimento = 4 queries de dados
        # + 1 query de checagem de grupo do RBAC + 1 query para buscar
        # o nome da espécie no response serializer = 6 totais.
        with self.assertNumQueriesReais(6):
            response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 1)
        pet = Pet.objects.get()
        self.assertEqual(pet.tutor, tutor)
        self.assertEqual(data["pet"]["id"], str(pet.id))
        self.assertEqual(data["pet"]["nome"], "Mel")
        self.assertEqual(data["tutor"]["id"], str(tutor.id))
        self.assertEqual(Atendimento.objects.get().pet, pet)

    def test_tutor_novo_e_pet_novo(self):
        payload = self.payload_base(
            tutor={"nome": "Tutor Novo", "telefone": "11 92222-3333"},
            pet={"nome": "Pipoca", "especie": str(self.especie_gato.id)},
        )

        # insert do tutor + insert do pet + insert do atendimento = 3 queries
        # de dados + 1 query de checagem de grupo do RBAC + 1 query para
        # buscar o nome da espécie no response serializer = 5 totais.
        with self.assertNumQueriesReais(5):
            response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()

        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 1)
        tutor = Tutor.objects.get()
        pet = Pet.objects.get()
        self.assertEqual(pet.tutor, tutor)
        self.assertEqual(data["tutor"]["id"], str(tutor.id))
        self.assertEqual(data["tutor"]["nome"], "Tutor Novo")
        self.assertEqual(data["pet"]["nome"], "Pipoca")

    def test_pet_que_nao_pertence_ao_tutor_retorna_400(self):
        tutor_a = self.criar_tutor(nome="Dona Alves")
        pet_de_a = self.criar_pet(tutor_a)
        tutor_b = self.criar_tutor(nome="Outro Tutor", telefone="11 94444-5555")
        payload = self.payload_base(
            tutor_id=str(tutor_b.id), pet_id=str(pet_de_a.id)
        )

        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"pet_id": ["O pet informado não pertence ao tutor informado."]},
        )
        # Nada foi criado.
        self.assertEqual(Atendimento.objects.count(), 0)
        self.assertEqual(Tutor.objects.count(), 2)
        self.assertEqual(Pet.objects.count(), 1)

    def test_payload_ambiguo_tutor_id_e_tutor_retorna_400(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        payload = self.payload_base(
            tutor_id=str(tutor.id),
            tutor={"nome": "Tutor Duplicado", "telefone": "11 95555-6666"},
            pet_id=str(pet.id),
        )

        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"tutor_id": ["Não informe tutor_id e tutor ao mesmo tempo."]},
        )
        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_payload_ambiguo_pet_id_e_pet_retorna_400(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        payload = self.payload_base(
            tutor_id=str(tutor.id),
            pet_id=str(pet.id),
            pet={
                "nome": "Outro Pet",
                "especie": str(self.especie_cao.id),
            },
        )

        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"pet_id": ["Não informe pet_id e pet ao mesmo tempo."]},
        )
        self.assertEqual(Pet.objects.count(), 1)
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_sem_tutor_retorna_400(self):
        tutor = self.criar_tutor()
        payload = self.payload_base(pet_id=str(self.criar_pet(tutor).id))

        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"tutor": ["Informe tutor_id ou tutor."]}
        )
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_sem_pet_retorna_400(self):
        tutor = self.criar_tutor()
        payload = self.payload_base(tutor_id=str(tutor.id))

        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"pet": ["Informe pet_id ou pet."]})
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_dados_do_atendimento_obrigatorios_em_portugues(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)

        response = self.client.post(
            URL_RAPIDO,
            {"tutor_id": str(tutor.id), "pet_id": str(pet.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        erros = response.json()
        self.assertEqual(
            erros["tipo_servico"], ["Informe o tipo de serviço."]
        )
        self.assertEqual(
            erros["data_hora_inicio"], ["Informe a data e hora de início."]
        )
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_sem_profissional_retorna_400_em_portugues(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        payload = self.payload_base(
            tutor_id=str(tutor.id), pet_id=str(pet.id)
        )
        payload.pop("nome_profissional")  # nem profissional_id, nem nome

        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"profissional": ["Informe profissional_id ou nome_profissional."]},
        )
        self.assertEqual(Atendimento.objects.count(), 0)


class AtendimentoRapidoServiceTests(TestCase):
    """Regras do service direto (sem HTTP): validação e rollback."""

    def setUp(self):
        self.especie_cao, _ = Especie.objects.get_or_create(nome="Cão")
        self.especie_gato, _ = Especie.objects.get_or_create(nome="Gato")

    def dados_validos(self, **extra):
        dados = {
            "tutor": {"nome": "Rollback", "telefone": "11 90000-0000"},
            "pet": {
                "nome": "Pipoca",
                "especie": self.especie_gato,
            },
            "nome_profissional": "Dra. Ana",
            "tipo_servico": "consulta",
            "data_hora_inicio": timezone.make_aware(
                datetime(2026, 10, 20, 10, 0)
            ),
        }
        dados.update(extra)
        return dados

    def test_rollback_quando_falha_a_criacao_do_atendimento(self):
        with patch.object(
            Atendimento.objects,
            "create",
            side_effect=IntegrityError("falha simulada no banco"),
        ):
            with self.assertRaises(IntegrityError):
                criar_atendimento_rapido(self.dados_validos())

        # Tutor e pet chegaram a ser criados e mesmo assim foram desfeitos.
        self.assertEqual(Tutor.objects.count(), 0)
        self.assertEqual(Pet.objects.count(), 0)
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_pet_existente_de_outro_tutor_dispara_erro_sem_criar_nada(self):
        tutor_a = Tutor.objects.create(nome="Dona Alves", telefone="11 91111-1111")
        especie_cao, _ = Especie.objects.get_or_create(nome="Cão")
        pet_de_a = Pet.objects.create(
            tutor=tutor_a, nome="Rex", especie=especie_cao
        )
        tutor_b = Tutor.objects.create(
            nome="Outro Tutor", telefone="11 94444-5555"
        )

        dados = self.dados_validos(tutor_id=tutor_b, pet_id=pet_de_a)
        dados.pop("tutor")
        dados.pop("pet")

        with self.assertRaises(DRFValidationError) as ctx:
            criar_atendimento_rapido(dados)

        self.assertEqual(
            ctx.exception.detail,
            {"pet_id": ["O pet informado não pertence ao tutor informado."]},
        )
        self.assertEqual(Atendimento.objects.count(), 0)
        self.assertEqual(Tutor.objects.count(), 2)
        self.assertEqual(Pet.objects.count(), 1)

    def test_cria_tutor_pet_e_atendimento(self):
        atendimento = criar_atendimento_rapido(self.dados_validos())

        self.assertEqual(Tutor.objects.count(), 1)
        self.assertEqual(Pet.objects.count(), 1)
        self.assertEqual(Atendimento.objects.count(), 1)
        self.assertEqual(atendimento.pet.tutor.nome, "Rollback")
        self.assertEqual(atendimento.duracao_minutos, 30)
        self.assertEqual(atendimento.status, "agendado")


class AtendimentoEndpointsLegadosTests(AtendimentoApiTestCase):
    """Os endpoints originais de /atendimentos/ continuam funcionando."""

    def test_create_legado_com_pet_fk(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        payload = {
            "pet": str(pet.id),
            "nome_profissional": "Dr. Paulo Lima",
            "tipo_servico": "vacina",
            "data_hora_inicio": "2026-10-20T11:00:00Z",
        }

        response = self.client.post(URL_ATENDIMENTOS, payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["pet"], str(pet.id))
        self.assertEqual(Atendimento.objects.count(), 1)

    def test_list_e_search_continuam_funcionando(self):
        tutor = self.criar_tutor(nome="Ze Mane")
        pet = self.criar_pet(tutor, nome="Totoca")
        Atendimento.objects.create(
            pet=pet,
            nome_profissional="Dr. Paulo Lima",
            tipo_servico="consulta",
            data_hora_inicio=timezone.make_aware(datetime(2026, 10, 20, 9, 0)),
        )

        response = self.client.get(URL_ATENDIMENTOS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

        response = self.client.get(URL_ATENDIMENTOS, {"search": "Totoca"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

        response = self.client.get(URL_ATENDIMENTOS, {"search": "Paulo"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)


class ProfissionalIdTests(AtendimentoApiTestCase):
    """Escrita e leitura via profissional_id (Fase 4)."""

    def test_create_legado_com_profissional_id_espelha_o_nome(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        prof = self.criar_profissional(nome="Dr. Paulo Lima")
        payload = {
            "pet": str(pet.id),
            "profissional_id": str(prof.id),
            "tipo_servico": "consulta",
            "data_hora_inicio": "2026-10-20T11:00:00Z",
        }

        response = self.client.post(URL_ATENDIMENTOS, payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["profissional_id"], str(prof.id))
        self.assertEqual(
            data["profissional"],
            {"id": str(prof.id), "nome": "Dr. Paulo Lima", "cargo": "Veterinário"},
        )
        # nome_profissional espelhado a partir da FK.
        self.assertEqual(data["nome_profissional"], "Dr. Paulo Lima")
        self.assertEqual(Atendimento.objects.get().profissional, prof)

    def test_create_legado_sem_nenhum_profissional_retorna_400(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        payload = {
            "pet": str(pet.id),
            "tipo_servico": "consulta",
            "data_hora_inicio": "2026-10-20T11:00:00Z",
        }

        response = self.client.post(URL_ATENDIMENTOS, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"profissional": ["Informe profissional_id ou nome_profissional."]},
        )
        self.assertEqual(Atendimento.objects.count(), 0)

    def test_rapido_com_profissional_id(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        prof = self.criar_profissional()
        payload = self.payload_base(
            tutor_id=str(tutor.id), pet_id=str(pet.id)
        )
        payload.pop("nome_profissional")
        payload["profissional_id"] = str(prof.id)

        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["profissional_id"], str(prof.id))
        self.assertEqual(data["profissional"]["nome"], "Dra. Ana Souza")
        # FK vence quando vêm os dois formatos.
        self.assertEqual(data["nome_profissional"], "Dra. Ana Souza")

    def test_atualizacao_troca_profissional_e_espelha(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        prof_a = self.criar_profissional(nome="Dra. Ana Souza")
        prof_b = self.criar_profissional(nome="Dr. Novo Nome", cargo="tosador")
        atendimento = self.criar_atendimento_direto(
            pet, profissional=prof_a, nome_profissional="Dra. Ana Souza"
        )

        # Atualização de atendimento é restrita a admin/veterinário (RBAC).
        self.user.groups.clear()
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.user.groups.add(grupo_vet)

        response = self.client.patch(
            f"{URL_ATENDIMENTOS}{atendimento.id}/",
            {"profissional_id": str(prof_b.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nome_profissional"], "Dr. Novo Nome")
        atendimento.refresh_from_db()
        self.assertEqual(atendimento.profissional, prof_b)
        self.assertEqual(atendimento.nome_profissional, "Dr. Novo Nome")

    def test_search_por_nome_do_profissional_via_fk(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        prof = self.criar_profissional(nome="Dra. Carolina Dias")
        # nome_profissional propositalmente diferente: o join da FK é que vale.
        self.criar_atendimento_direto(
            pet,
            profissional=prof,
            nome_profissional="Nome Antigo Diferente",
        )

        response = self.client.get(URL_ATENDIMENTOS, {"search": "Carolina"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_filtro_por_profissional(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        prof_a = self.criar_profissional(nome="Dra. Ana Souza")
        prof_b = self.criar_profissional(nome="Dr. Bruno Luz", cargo="tosador")
        self.criar_atendimento_direto(pet, profissional=prof_a)
        self.criar_atendimento_direto(
            pet,
            profissional=prof_b,
            data_hora_inicio=timezone.make_aware(datetime(2026, 10, 21, 10, 0)),
        )

        response = self.client.get(
            URL_ATENDIMENTOS, {"profissional": str(prof_a.id)}
        )

        self.assertEqual(response.status_code, 200)
        resultados = response.json()["results"]
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["profissional_id"], str(prof_a.id))

    def test_profissional_com_atendimento_e_protegido(self):
        tutor = self.criar_tutor()
        pet = self.criar_pet(tutor)
        prof = self.criar_profissional()
        self.criar_atendimento_direto(pet, profissional=prof)

        # Soft delete substitui o hard delete no fluxo comum: não há erro.
        prof.delete(user=self.user)
        self.assertEqual(Profissional.objects.count(), 0)
        self.assertEqual(Profissional.all_objects.count(), 1)

        # A remoção física (hard_delete) continua protegida por PROTECT da FK.
        with self.assertRaises(ProtectedError):
            prof.hard_delete()

        self.assertEqual(Profissional.objects.count(), 0)
        self.assertEqual(Profissional.all_objects.count(), 1)


class ConflitoHorarioTests(AtendimentoApiTestCase):
    """Regra: o mesmo profissional não pode ter dois atendimentos sobrepostos."""

    def setUp(self):
        super().setUp()
        self.tutor = self.criar_tutor()
        self.pet = self.criar_pet(self.tutor)
        self.prof = self.criar_profissional()

    def payload_legado(self, **extra):
        dados = {
            "pet": str(self.pet.id),
            "profissional_id": str(self.prof.id),
            "tipo_servico": "consulta",
            "data_hora_inicio": "2026-10-20T09:00:00Z",
            "duracao_minutos": 30,
        }
        dados.update(extra)
        return dados

    def test_conflito_retorna_400_em_portugues(self):
        primeiro = self.client.post(
            URL_ATENDIMENTOS, self.payload_legado(), format="json"
        )
        self.assertEqual(primeiro.status_code, 201)

        response = self.client.post(
            URL_ATENDIMENTOS,
            self.payload_legado(data_hora_inicio="2026-10-20T09:15:00Z"),
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        erros = response.json()
        self.assertIn("data_hora_inicio", erros)
        self.assertIn("Conflito de horário", erros["data_hora_inicio"][0])
        self.assertIn("Dra. Ana Souza", erros["data_hora_inicio"][0])
        # Nada foi criado no segundo POST.
        self.assertEqual(Atendimento.objects.count(), 1)

    def test_horarios_adjacentes_sao_permitidos(self):
        primeiro = self.client.post(
            URL_ATENDIMENTOS, self.payload_legado(), format="json"
        )
        segundo = self.client.post(
            URL_ATENDIMENTOS,
            self.payload_legado(data_hora_inicio="2026-10-20T09:30:00Z"),
            format="json",
        )

        self.assertEqual(primeiro.status_code, 201)
        self.assertEqual(segundo.status_code, 201)
        self.assertEqual(Atendimento.objects.count(), 2)

    def test_conflito_ignora_profissional_diferente(self):
        outro = self.criar_profissional(nome="Dr. Bruno Luz", cargo="tosador")
        primeiro = self.client.post(
            URL_ATENDIMENTOS, self.payload_legado(), format="json"
        )
        segundo = self.client.post(
            URL_ATENDIMENTOS,
            self.payload_legado(
                data_hora_inicio="2026-10-20T09:15:00Z",
                profissional_id=str(outro.id),
            ),
            format="json",
        )

        self.assertEqual(primeiro.status_code, 201)
        self.assertEqual(segundo.status_code, 201)
        self.assertEqual(Atendimento.objects.count(), 2)

    def test_existente_cancelado_nao_conflita(self):
        self.criar_atendimento_direto(
            self.pet,
            profissional=self.prof,
            nome_profissional=self.prof.nome,
            status=Atendimento.Status.CANCELADO,
        )

        response = self.client.post(
            URL_ATENDIMENTOS,
            self.payload_legado(data_hora_inicio="2026-10-20T09:15:00Z"),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Atendimento.objects.count(), 2)

    def test_novo_cancelado_nao_conflita(self):
        self.criar_atendimento_direto(
            self.pet, profissional=self.prof, nome_profissional=self.prof.nome
        )

        response = self.client.post(
            URL_ATENDIMENTOS,
            self.payload_legado(
                data_hora_inicio="2026-10-20T09:15:00Z",
                status=Atendimento.Status.CANCELADO,
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Atendimento.objects.count(), 2)

    def test_edicao_do_proprio_atendimento_nao_conflita_consigo(self):
        primeiro = self.client.post(
            URL_ATENDIMENTOS, self.payload_legado(), format="json"
        )
        id_atendimento = primeiro.json()["id"]

        # Atualização exige veterinário (RBAC).
        self.user.groups.clear()
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.user.groups.add(grupo_vet)

        # 09:00 + 45min: sem ignorar o próprio registro daria conflito consigo.
        response = self.client.patch(
            f"{URL_ATENDIMENTOS}{id_atendimento}/",
            {"duracao_minutos": 45},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["duracao_minutos"], 45)

    def test_edicao_com_conflito_em_outro_retorna_400(self):
        primeiro = self.client.post(
            URL_ATENDIMENTOS, self.payload_legado(), format="json"
        )
        segundo = self.client.post(
            URL_ATENDIMENTOS,
            self.payload_legado(data_hora_inicio="2026-10-20T10:00:00Z"),
            format="json",
        )
        self.assertEqual(primeiro.status_code, 201)
        self.assertEqual(segundo.status_code, 201)

        # Atualização exige veterinário (RBAC).
        self.user.groups.clear()
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.user.groups.add(grupo_vet)

        response = self.client.patch(
            f"{URL_ATENDIMENTOS}{segundo.json()['id']}/",
            {"data_hora_inicio": "2026-10-20T09:15:00Z"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Conflito de horário",
            response.json()["data_hora_inicio"][0],
        )
        # Horário do segundo não mudou.
        obj = Atendimento.objects.get(pk=segundo.json()["id"])
        self.assertEqual(
            obj.data_hora_inicio,
            timezone.make_aware(datetime(2026, 10, 20, 10, 0), dt_timezone.utc),
        )

    def test_legado_sem_fk_nao_verifica_conflito(self):
        """Sem FK não há identidade do profissional: dois registros legados
        com o mesmo texto livre sobrepostos são aceitos (documentado)."""
        payload = {
            "pet": str(self.pet.id),
            "nome_profissional": "Dra. Ana Souza",
            "tipo_servico": "consulta",
            "data_hora_inicio": "2026-10-20T09:00:00Z",
            "duracao_minutos": 30,
        }
        primeiro = self.client.post(URL_ATENDIMENTOS, payload, format="json")
        payload["data_hora_inicio"] = "2026-10-20T09:15:00Z"
        segundo = self.client.post(URL_ATENDIMENTOS, payload, format="json")

        self.assertEqual(primeiro.status_code, 201)
        self.assertEqual(segundo.status_code, 201)
        self.assertEqual(Atendimento.objects.count(), 2)

    def test_rapido_com_conflito_retorna_400(self):
        payload = self.payload_base(
            tutor_id=str(self.tutor.id),
            pet_id=str(self.pet.id),
            profissional_id=str(self.prof.id),
        )
        payload.pop("nome_profissional")
        primeiro = self.client.post(URL_RAPIDO, payload, format="json")
        self.assertEqual(primeiro.status_code, 201)

        payload["data_hora_inicio"] = "2026-10-20T09:15:00Z"
        response = self.client.post(URL_RAPIDO, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn(
            "Conflito de horário",
            response.json()["data_hora_inicio"][0],
        )
        self.assertEqual(Atendimento.objects.count(), 1)


class AgendaStatusTests(AtendimentoApiTestCase):
    """Testes de transições de status: confirmar, cancelar, reagendar, faltou."""

    def setUp(self):
        super().setUp()
        self.tutor = self.criar_tutor()
        self.pet = self.criar_pet(self.tutor)
        self.prof = self.criar_profissional()
        self.atendimento = Atendimento.objects.create(
            pet=self.pet,
            profissional=self.prof,
            tipo_servico="consulta",
            data_hora_inicio=timezone.make_aware(
                datetime(2026, 10, 20, 9, 0), dt_timezone.utc
            ),
            duracao_minutos=30,
            status="agendado",
        )

    def test_confirmar_atendimento_agendado(self):
        self.user.groups.clear()
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.user.groups.add(grupo_rec)
        resp = self.client.post(
            f"/api/v1/atendimentos/{self.atendimento.id}/confirmar/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.atendimento.refresh_from_db()
        self.assertEqual(self.atendimento.status, "confirmado")
        self.assertIsNotNone(self.atendimento.data_confirmacao)

    def test_cancelar_atendimento_com_motivo(self):
        self.user.groups.clear()
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.user.groups.add(grupo_rec)
        resp = self.client.post(
            f"/api/v1/atendimentos/{self.atendimento.id}/cancelar/",
            {"motivo": "Paciente desistiu"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.atendimento.refresh_from_db()
        self.assertEqual(self.atendimento.status, "cancelado")
        self.assertEqual(self.atendimento.motivo_cancelamento, "Paciente desistiu")
        self.assertIsNotNone(self.atendimento.data_cancelamento)

    def test_reagendar_atendimento(self):
        self.user.groups.clear()
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.user.groups.add(grupo_rec)
        resp = self.client.post(
            f"/api/v1/atendimentos/{self.atendimento.id}/reagendar/",
            {"data_hora_inicio": "2026-10-20T10:00:00Z"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.atendimento.refresh_from_db()
        self.assertEqual(self.atendimento.reagendado_de_id, self.atendimento.pk)
        # O reagendamento cria um NOVO registro; o antigo continua cancelado? Não,
        # o reagendamento atualiza o mesmo registro e registra o original.

    def test_marcar_faltou(self):
        self.user.groups.clear()
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.user.groups.add(grupo_vet)
        resp = self.client.post(
            f"/api/v1/atendimentos/{self.atendimento.id}/faltou/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.atendimento.refresh_from_db()
        self.assertEqual(self.atendimento.status, "faltou")

    def test_realizar_atendimento(self):
        self.user.groups.clear()
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.user.groups.add(grupo_vet)
        resp = self.client.post(
            f"/api/v1/atendimentos/{self.atendimento.id}/realizar/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.atendimento.refresh_from_db()
        self.assertEqual(self.atendimento.status, "realizado")


class AgendaSalaTests(AtendimentoApiTestCase):
    """Testes de conflito de sala."""

    def setUp(self):
        super().setUp()
        from apps.veterinarios.models import SalaConsultorio

        self.sala = SalaConsultorio.objects.create(nome="Sala A", ativo=True)
        self.tutor = self.criar_tutor()
        self.pet = self.criar_pet(self.tutor)
        self.prof = self.criar_profissional()

    def test_conflito_de_sala(self):
        from django.utils import timezone as tz

        # Profissional diferente para o atendimento existente na mesma sala
        prof_outro = self.criar_profissional(nome="Dr. Outro", cargo="Veterinário")
        # Outro pet para o atendimento existente
        pet_outro = self.criar_pet(self.tutor, nome="Rex2")
        Atendimento.objects.create(
            pet=pet_outro,
            profissional=prof_outro,
            sala=self.sala,
            tipo_servico="consulta",
            data_hora_inicio=tz.make_aware(
                datetime(2026, 10, 20, 9, 0), dt_timezone.utc
            ),
            duracao_minutos=30,
            status="agendado",
        )
        # Mesmo horário sobreposto, mesma sala, profissional diferente -> conflito de sala.
        resp = self.client.post(
            URL_ATENDIMENTOS,
            {
                "pet": str(self.pet.id),
                "profissional_id": str(self.prof.id),
                "sala": str(self.sala.id),
                "tipo_servico": "consulta",
                "data_hora_inicio": "2026-10-20T09:15:00Z",
                "duracao_minutos": 30,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("sala", resp.json())


class AgendaHistoricoStatusTests(AtendimentoApiTestCase):
    """Testes de histórico de mudanças de status."""

    def setUp(self):
        super().setUp()
        self.tutor = self.criar_tutor()
        self.pet = self.criar_pet(self.tutor)
        self.prof = self.criar_profissional()
        self.atendimento = Atendimento.objects.create(
            pet=self.pet,
            profissional=self.prof,
            tipo_servico="consulta",
            data_hora_inicio=timezone.make_aware(
                datetime(2026, 10, 20, 9, 0), dt_timezone.utc
            ),
            duracao_minutos=30,
            status="agendado",
        )

    def test_historico_registra_mudanca_de_status(self):
        from apps.veterinarios.models import HistoricoStatusAtendimento

        self.user.groups.clear()
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.user.groups.add(grupo_rec)

        before = HistoricoStatusAtendimento.objects.count()
        self.client.post(
            f"/api/v1/atendimentos/{self.atendimento.id}/confirmar/",
            {},
            format="json",
        )
        self.assertEqual(
            HistoricoStatusAtendimento.objects.count(), before + 1
        )
        historico = HistoricoStatusAtendimento.objects.latest("data_operacao")
        self.assertEqual(historico.status_anterior, "agendado")
        self.assertEqual(historico.status_novo, "confirmado")
        self.assertEqual(historico.usuario, self.user)
