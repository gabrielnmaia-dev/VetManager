"""Testes da camada de segurança P0: RBAC, autoria, auditoria, soft delete,
proteção clínica, cookies JWT e CSRF."""

from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import AuditLog
from apps.pets.models import Especie, Pet, Raca
from apps.prontuario.models import Prontuario, Vacina
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional

User = get_user_model()

GRUPO_ADMIN = "admin"
GRUPO_VET = "veterinario"
GRUPO_REC = "recepcao"


def fazer_usuario(username, grupo, senha="senha123"):
    user = User.objects.create_user(username=username, password=senha)
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


def autenticar(client, user):
    client.force_authenticate(user)
    return client


class RBACViewSetTests(TestCase):
    """Cada papel tem acesso adequado a cada endpoint."""

    def setUp(self):
        self.admin = fazer_usuario("admin_t", GRUPO_ADMIN)
        self.vet = fazer_usuario("vet_t", GRUPO_VET)
        self.rec = fazer_usuario("rec_t", GRUPO_REC)
        self.client = APIClient()
        self.especie_cao, _ = Especie.objects.get_or_create(nome="Cão")
        self.tutor = Tutor.objects.create(nome="T", telefone="11 99999-9999")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex", especie=self.especie_cao
        )
        self.prof = Profissional.objects.create(
            nome="Dr. X", cargo="Veterinário"
        )

    def _grupo(self, cliente, usuario, grupo_nome):
        usuario.groups.clear()
        g, _ = Group.objects.get_or_create(name=grupo_nome)
        usuario.groups.add(g)

    # ----- tutores -----
    def test_recepcao_pode_criar_tutor(self):
        autenticar(self.client, self.rec)
        self._grupo(self.client, self.rec, GRUPO_REC)
        resp = self.client.post(
            "/api/v1/tutores/",
            {"nome": "Novo", "telefone": "11 98888-8888"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_recepcao_nao_pode_atualizar_atendimento(self):
        autenticar(self.client, self.rec)
        self._grupo(self.client, self.rec, GRUPO_REC)
        atendimento = self._criar_atendimento()
        resp = self.client.patch(
            f"/api/v1/atendimentos/{atendimento.id}/",
            {"observacoes": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_veterinario_pode_atualizar_atendimento(self):
        autenticar(self.client, self.vet)
        self._grupo(self.client, self.vet, GRUPO_VET)
        atendimento = self._criar_atendimento()
        resp = self.client.patch(
            f"/api/v1/atendimentos/{atendimento.id}/",
            {"observacoes": "x"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_recepcao_nao_pode_listar_prontuarios(self):
        autenticar(self.client, self.rec)
        self._grupo(self.client, self.rec, GRUPO_REC)
        resp = self.client.get("/api/v1/prontuarios/")
        self.assertEqual(resp.status_code, 403)

    def test_veterinario_pode_listar_prontuarios(self):
        autenticar(self.client, self.vet)
        self._grupo(self.client, self.vet, GRUPO_VET)
        resp = self.client.get("/api/v1/prontuarios/")
        self.assertEqual(resp.status_code, 200)

    # ----- profissionais (leitura para a agenda, gestão só admin) -----
    def test_recepcao_pode_listar_profissionais(self):
        """A recepção precisa listar profissionais para agendar."""
        autenticar(self.client, self.rec)
        self._grupo(self.client, self.rec, GRUPO_REC)
        resp = self.client.get("/api/v1/profissionais/")
        self.assertEqual(resp.status_code, 200)

    def test_veterinario_pode_listar_profissionais(self):
        autenticar(self.client, self.vet)
        self._grupo(self.client, self.vet, GRUPO_VET)
        resp = self.client.get("/api/v1/profissionais/")
        self.assertEqual(resp.status_code, 200)

    def test_recepcao_nao_pode_criar_profissional(self):
        """Gestão de profissionais continua restrita ao admin."""
        autenticar(self.client, self.rec)
        self._grupo(self.client, self.rec, GRUPO_REC)
        resp = self.client.post(
            "/api/v1/profissionais/",
            {"nome": "Novo Prof", "cargo": "tosador"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_veterinario_nao_pode_criar_profissional(self):
        autenticar(self.client, self.vet)
        self._grupo(self.client, self.vet, GRUPO_VET)
        resp = self.client.post(
            "/api/v1/profissionais/",
            {"nome": "Novo Prof", "cargo": "tosador"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_nao_autenticado_negado(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/tutores/")
        self.assertEqual(resp.status_code, 401)

    def _criar_atendimento(self):
        from apps.atendimentos.models import Atendimento

        return Atendimento.objects.create(
            pet=self.pet,
            profissional=self.prof,
            tipo_servico="consulta",
            data_hora_inicio=timezone.now(),
            status="agendado",
        )


class AutoriaTests(TestCase):
    """created_by/updated_by são preenchidos pelo backend, nunca pelo cliente."""

    def setUp(self):
        self.vet = fazer_usuario("vet_aut", GRUPO_VET)
        self.client = APIClient()
        self.client.force_authenticate(self.vet)
        self.tutor = Tutor.objects.create(nome="T", telefone="11 99999-9999")
        especie_cao, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex", especie=especie_cao
        )

    def test_tutor_recebe_created_by_automatico(self):
        resp = self.client.post(
            "/api/v1/tutores/",
            {"nome": "Autoria Tutor", "telefone": "11 91111-1111"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        tutor = Tutor.objects.get(nome="Autoria Tutor")
        self.assertEqual(tutor.created_by, self.vet)
        self.assertEqual(tutor.updated_by, self.vet)

    def test_atendimento_recebe_created_by_via_service(self):
        prof = Profissional.objects.create(nome="Dr. Y", cargo="Veterinário")
        resp = self.client.post(
            "/api/v1/atendimentos/rapido/",
            {
                "tutor_id": str(self.tutor.id),
                "pet_id": str(self.pet.id),
                "profissional_id": str(prof.id),
                "tipo_servico": "consulta",
                "data_hora_inicio": "2026-11-10T09:00:00Z",
                "duracao_minutos": 30,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        atendimento = resp.json()
        from apps.atendimentos.models import Atendimento

        a = Atendimento.objects.get(id=atendimento["id"])
        self.assertEqual(a.created_by, self.vet)
        self.assertEqual(a.updated_by, self.vet)


class SoftDeleteTests(TestCase):
    """Exclusão lógica: registros somam na lista comum, persistem no all_objects."""

    def setUp(self):
        self.admin = fazer_usuario("adm_sd", GRUPO_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.tutor = Tutor.objects.create(nome="SD", telefone="11 99999-9999")

    def test_soft_delete_remove_da_lista_mas_nao_apaga(self):
        resp = self.client.delete(f"/api/v1/tutores/{self.tutor.id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(Tutor.objects.count(), 0)
        self.assertEqual(Tutor.all_objects.count(), 1)
        self.tutor.refresh_from_db()
        self.assertTrue(self.tutor.is_deleted)
        self.assertEqual(self.tutor.deleted_by, self.admin)

    def test_recuperacao_controlada(self):
        self.tutor.delete(user=self.admin)
        self.tutor.restore(user=self.admin)
        self.tutor.refresh_from_db()
        self.assertFalse(self.tutor.is_deleted)
        self.assertIsNone(self.tutor.deleted_at)

    def test_vacina_soft_delete(self):
        especie_cao, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="RexSD", especie=especie_cao
        )
        vacina = Vacina.objects.create(
            pet=self.pet,
            nome_vacina="V10",
            data_aplicacao=datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )

        vacina.delete(user=self.admin)
        self.assertEqual(Vacina.objects.count(), 0)
        self.assertEqual(Vacina.all_objects.count(), 1)


class AuditoriaTests(TestCase):
    """Registro de auditoria é append-only e imutável."""

    def setUp(self):
        self.vet = fazer_usuario("vet_aud", GRUPO_VET)
        self.client = APIClient()
        self.client.force_authenticate(self.vet)
        self.tutor = Tutor.objects.create(nome="AUD", telefone="11 99999-9999")

    def test_criacao_registra_auditoria(self):
        antes = AuditLog.objects.count()
        resp = self.client.post(
            "/api/v1/tutores/",
            {"nome": "Auditoria Tutor", "telefone": "11 92222-2222"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(AuditLog.objects.count(), antes + 1)
        evento = AuditLog.objects.latest("criado_em")
        self.assertEqual(evento.acao, "criacao")
        self.assertEqual(evento.entidade, "tutores.tutor")
        self.assertEqual(evento.usuario, self.vet)

    def test_atualizacao_registra_antes_e_depois(self):
        resp = self.client.post(
            "/api/v1/tutores/",
            {"nome": "Antes", "telefone": "11 93333-3333"},
            format="json",
        )
        tutor_id = resp.json()["id"]
        antes = AuditLog.objects.count()
        self.client.patch(
            f"/api/v1/tutores/{tutor_id}/",
            {"nome": "Depois"},
            format="json",
        )
        self.assertEqual(AuditLog.objects.count(), antes + 1)
        evento = AuditLog.objects.latest("criado_em")
        self.assertEqual(evento.acao, "atualizacao")
        self.assertEqual(evento.dados_anteriores["nome"], "Antes")
        self.assertEqual(evento.dados_posteriores["nome"], "Depois")

    def test_auditoria_nao_pode_ser_alterada(self):
        resp = self.client.post(
            "/api/v1/tutores/",
            {"nome": "Imutavel", "telefone": "11 94444-4444"},
            format="json",
        )
        tutor_id = resp.json()["id"]
        evento_id = str(
            AuditLog.objects.get(entidade="tutores.tutor", entidade_id=tutor_id).id
        )
        # Tentativa de alteração via admin API não existe; testamos direto no model.
        evento = AuditLog.objects.get(id=evento_id)
        with self.assertRaises(Exception):
            evento.justificativa = "tentativa"
            evento.save()

    def test_auditoria_nao_pode_ser_excluida(self):
        resp = self.client.post(
            "/api/v1/tutores/",
            {"nome": "Indelével", "telefone": "11 95555-5555"},
            format="json",
        )
        tutor_id = resp.json()["id"]
        evento_id = str(
            AuditLog.objects.get(entidade="tutores.tutor", entidade_id=tutor_id).id
        )
        evento = AuditLog.objects.get(id=evento_id)
        with self.assertRaises(Exception):
            evento.delete()


class ProfissionalVeterinarioConsistenciaTests(TestCase):
    """Prontuário só aceita Veterinário (cargo), não qualquer Profissional."""

    def setUp(self):
        self.vet = fazer_usuario("vet_cons", GRUPO_VET)
        self.client = APIClient()
        self.client.force_authenticate(self.vet)
        self.tutor = Tutor.objects.create(nome="C", telefone="11 99999-9999")
        especie_cao, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Consist", especie=especie_cao
        )

    def test_prontuario_aceita_veterinario(self):
        prof_vet = Profissional.objects.create(
            nome="Dr. Vet", cargo="Veterinário"
        )
        from apps.veterinarios.models import Veterinario
        vet_rec = Veterinario.objects.create(
            profissional=prof_vet, crmv="CRMV-12345", especialidade="Clínica"
        )
        resp = self.client.post(
            "/api/v1/prontuarios/",
            {
                "pet": str(self.pet.id),
                "veterinario": str(vet_rec.pk),
                "data_consulta": "2026-11-10T09:00:00Z",
                "diagnostico": "OK",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_prontuario_rejeita_nao_veterinario(self):
        prof_tosador = Profissional.objects.create(
            nome="Tosador", cargo="tosador"
        )
        # Não é possível criar Veterinario para profissional não-veterinário
        # (validação no save do modelo). Tenta usar o ID do profissional
        # diretamente como veterinário: deve falhar porque não existe
        # registro de Veterinário com essa PK.
        resp = self.client.post(
            "/api/v1/prontuarios/",
            {
                "pet": str(self.pet.id),
                "veterinario": str(prof_tosador.id),
                "data_consulta": "2026-11-10T09:00:00Z",
                "diagnostico": "X",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
