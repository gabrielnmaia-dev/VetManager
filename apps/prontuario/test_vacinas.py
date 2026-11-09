"""Testes do módulo de vacinação (Prompt 08)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import AuditLog
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


class VacinaTests(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_vac", "admin")
        self.vet_user = fazer_usuario("vet_vac", "veterinario")
        self.recepcao = fazer_usuario("rec_vac", "recepcao")

        self.tutor = Tutor.objects.create(
            nome="Tutor Vacina", telefone="11 99999-0000", cpf="111.222.333-44"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor Vacina", telefone="11 98888-0000"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex Vacina", especie=self.especie
        )
        self.outro_pet = Pet.objects.create(
            tutor=self.outro_tutor, nome="Mia Vacina", especie=self.especie
        )
        self.profissional = Profissional.objects.create(
            nome="Dra. Vacina", cargo="Veterinário"
        )
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional,
            crmv="CRMV-VAC-1",
            especialidade="Clínica",
        )
        self.prontuario = Prontuario.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
        )
        self.prontuario_outro_pet = Prontuario.objects.create(
            pet=self.outro_pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
        )
        self.client = APIClient()
        self.hoje = timezone.localdate()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def autenticar(self, user):
        self.client.force_authenticate(user)
        return self.client

    def payload(self, **extra):
        dados = {
            "pet": str(self.pet.id),
            "nome_vacina": "V10",
            "data_aplicacao": (self.hoje - timedelta(days=30)).isoformat(),
            "data_retorno": (self.hoje + timedelta(days=335)).isoformat(),
            "veterinario": str(self.veterinario.id),
            "lote": "LOTE-001",
            "fabricante": "Fabricante Teste",
            "via_aplicacao": "subcutanea",
            "dose": "1 ml",
            "observacoes": "Sem reação.",
        }
        dados.update(extra)
        return dados

    def criar_vacina_modelo(self, **extra):
        dados = {
            "pet": self.pet,
            "nome_vacina": "V10",
            "data_aplicacao": self.hoje - timedelta(days=30),
        }
        dados.update(extra)
        return Vacina.objects.create(**dados)

    # ------------------------------------------------------------------
    # RBAC
    # ------------------------------------------------------------------
    def test_recepcao_lista_mas_nao_cria(self):
        self.criar_vacina_modelo()

        self.autenticar(self.recepcao)
        listagem = self.client.get("/api/v1/vacinas/")
        self.assertEqual(listagem.status_code, 200)
        self.assertEqual(listagem.data["count"], 1)

        criacao = self.client.post(
            "/api/v1/vacinas/", self.payload(), format="json"
        )
        self.assertEqual(criacao.status_code, 403)

    def test_recepcao_nao_edita_nem_exclui(self):
        vacina = self.criar_vacina_modelo()
        self.autenticar(self.recepcao)

        edicao = self.client.patch(
            f"/api/v1/vacinas/{vacina.id}/",
            {"nome_vacina": "Outra"},
            format="json",
        )
        self.assertEqual(edicao.status_code, 403)

        exclusao = self.client.delete(f"/api/v1/vacinas/{vacina.id}/")
        self.assertEqual(exclusao.status_code, 403)

    def test_veterinario_cria_com_auditoria_e_autoria(self):
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vacinas/", self.payload(), format="json"
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        vacina = Vacina.objects.get(pk=resposta.data["id"])
        self.assertEqual(vacina.created_by, self.vet_user)
        self.assertEqual(vacina.updated_by, self.vet_user)
        self.assertEqual(vacina.lote, "LOTE-001")
        self.assertEqual(vacina.via_aplicacao, "subcutanea")

        log = AuditLog.objects.filter(
            entidade="prontuario.vacina", entidade_id=str(vacina.id)
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.acao, AuditLog.Acao.CRIACAO)
        self.assertEqual(log.usuario, self.vet_user)

    # ------------------------------------------------------------------
    # Validações
    # ------------------------------------------------------------------
    def test_data_aplicacao_futura_rejeitada(self):
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vacinas/",
            self.payload(
                data_aplicacao=(self.hoje + timedelta(days=1)).isoformat(),
                data_retorno=None,
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("data_aplicacao", resposta.data)

    def test_retorno_anterior_a_aplicacao_rejeitado(self):
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vacinas/",
            self.payload(
                data_aplicacao=(self.hoje - timedelta(days=10)).isoformat(),
                data_retorno=(self.hoje - timedelta(days=11)).isoformat(),
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("data_retorno", resposta.data)

    def test_prontuario_de_outro_pet_rejeitado(self):
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vacinas/",
            self.payload(prontuario=str(self.prontuario_outro_pet.id)),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("prontuario", resposta.data)

    def test_veterinario_com_cargo_invalido_rejeitado(self):
        # Simula um vínculo inconsistente (não é possível criar pelo model).
        Profissional.objects.filter(pk=self.profissional.pk).update(
            cargo="tosador"
        )
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vacinas/", self.payload(), format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("veterinario", resposta.data)

    # ------------------------------------------------------------------
    # Situação calculada e filtros
    # ------------------------------------------------------------------
    def test_situacao_calculada(self):
        atrasada = self.criar_vacina_modelo(
            nome_vacina="Atrasada",
            data_aplicacao=self.hoje - timedelta(days=400),
            data_retorno=self.hoje - timedelta(days=1),
        )
        proxima = self.criar_vacina_modelo(
            nome_vacina="Próxima",
            data_aplicacao=self.hoje - timedelta(days=350),
            data_retorno=self.hoje + timedelta(days=10),
        )
        em_dia = self.criar_vacina_modelo(
            nome_vacina="Em dia",
            data_aplicacao=self.hoje - timedelta(days=10),
            data_retorno=self.hoje + timedelta(days=90),
        )
        sem_retorno = self.criar_vacina_modelo(
            nome_vacina="Sem retorno",
            data_aplicacao=self.hoje - timedelta(days=5),
        )

        self.assertEqual(atrasada.situacao, Vacina.Situacao.ATRASADA)
        self.assertEqual(proxima.situacao, Vacina.Situacao.PROXIMA)
        self.assertEqual(em_dia.situacao, Vacina.Situacao.EM_DIA)
        self.assertEqual(sem_retorno.situacao, Vacina.Situacao.SEM_RETORNO)
        self.assertEqual(atrasada.dias_para_retorno, -1)

        self.autenticar(self.recepcao)
        resposta = self.client.get(f"/api/v1/vacinas/?pet={self.pet.id}")
        self.assertEqual(resposta.status_code, 200)
        por_nome = {item["nome_vacina"]: item for item in resposta.data["results"]}
        self.assertEqual(por_nome["Atrasada"]["situacao"], "atrasada")
        self.assertEqual(
            por_nome["Próxima"]["situacao_display"], "Próxima do retorno"
        )

    def test_filtro_por_situacao(self):
        self.criar_vacina_modelo(
            nome_vacina="Atrasada",
            data_aplicacao=self.hoje - timedelta(days=400),
            data_retorno=self.hoje - timedelta(days=1),
        )
        self.criar_vacina_modelo(
            nome_vacina="Em dia",
            data_aplicacao=self.hoje - timedelta(days=10),
            data_retorno=self.hoje + timedelta(days=90),
        )
        self.autenticar(self.vet_user)

        resposta = self.client.get("/api/v1/vacinas/?situacao=atrasada")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 1)
        self.assertEqual(resposta.data["results"][0]["nome_vacina"], "Atrasada")

    def test_busca_por_tutor_e_lote(self):
        self.criar_vacina_modelo(nome_vacina="V8", lote="LOTE-ABC")
        self.autenticar(self.vet_user)

        por_tutor = self.client.get("/api/v1/vacinas/?search=Tutor Vacina")
        self.assertEqual(por_tutor.data["count"], 1)

        por_lote = self.client.get("/api/v1/vacinas/?search=LOTE-ABC")
        self.assertEqual(por_lote.data["count"], 1)

    def test_resumo_por_situacao(self):
        self.criar_vacina_modelo(
            data_aplicacao=self.hoje - timedelta(days=400),
            data_retorno=self.hoje - timedelta(days=1),
        )
        self.criar_vacina_modelo(
            data_aplicacao=self.hoje - timedelta(days=350),
            data_retorno=self.hoje + timedelta(days=10),
        )
        self.criar_vacina_modelo(
            data_aplicacao=self.hoje - timedelta(days=10),
            data_retorno=self.hoje + timedelta(days=90),
        )
        self.criar_vacina_modelo(
            data_aplicacao=self.hoje - timedelta(days=5),
        )
        self.autenticar(self.recepcao)

        resposta = self.client.get(f"/api/v1/vacinas/resumo/?pet={self.pet.id}")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.data,
            {
                "total": 4,
                "em_dia": 1,
                "proxima": 1,
                "atrasada": 1,
                "sem_retorno": 1,
            },
        )

    # ------------------------------------------------------------------
    # Exclusão lógica e compatibilidade
    # ------------------------------------------------------------------
    def test_exclusao_logica_preserva_historico(self):
        vacina = self.criar_vacina_modelo()
        self.autenticar(self.vet_user)

        resposta = self.client.delete(f"/api/v1/vacinas/{vacina.id}/")
        self.assertEqual(resposta.status_code, 204)
        self.assertEqual(Vacina.objects.count(), 0)
        self.assertEqual(Vacina.all_objects.count(), 1)

        registro = Vacina.all_objects.get(pk=vacina.id)
        self.assertTrue(registro.is_deleted)
        self.assertEqual(registro.deleted_by, self.vet_user)
        self.assertTrue(
            AuditLog.objects.filter(
                entidade="prontuario.vacina",
                entidade_id=str(vacina.id),
                acao=AuditLog.Acao.EXCLUSAO,
            ).exists()
        )

    def test_registro_legado_sem_campos_novos_continua_valido(self):
        vacina = self.criar_vacina_modelo(nome_vacina="Antiga")
        self.autenticar(self.recepcao)

        resposta = self.client.get(f"/api/v1/vacinas/{vacina.id}/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["nome_vacina"], "Antiga")
        self.assertEqual(resposta.data["lote"], "")
        self.assertIsNone(resposta.data["veterinario"])
        self.assertEqual(resposta.data["situacao"], "sem_retorno")

    def test_paginacao_estavel_com_mesma_data(self):
        for indice in range(25):
            self.criar_vacina_modelo(nome_vacina=f"Vacina {indice}")
        self.autenticar(self.recepcao)

        primeira = self.client.get("/api/v1/vacinas/")
        segunda = self.client.get("/api/v1/vacinas/?page=2")
        self.assertEqual(primeira.data["count"], 25)
        self.assertEqual(len(primeira.data["results"]), 20)
        self.assertEqual(len(segunda.data["results"]), 5)

        ids_primeira = {item["id"] for item in primeira.data["results"]}
        ids_segunda = {item["id"] for item in segunda.data["results"]}
        self.assertFalse(ids_primeira & ids_segunda)
