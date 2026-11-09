"""Testes do módulo de vermifugação (Prompt 09)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import AuditLog
from apps.pets.models import Especie, Pet
from apps.prontuario.models import Prontuario, Vermifugacao
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional, Veterinario

User = get_user_model()


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class VermifugacaoTests(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_verm", "admin")
        self.vet_user = fazer_usuario("vet_verm", "veterinario")
        self.recepcao = fazer_usuario("rec_verm", "recepcao")

        self.tutor = Tutor.objects.create(
            nome="Tutor Vermifugo", telefone="11 99999-1111", cpf="222.333.444-55"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor Vermifugo", telefone="11 98888-1111"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex Vermifugo", especie=self.especie
        )
        self.outro_pet = Pet.objects.create(
            tutor=self.outro_tutor, nome="Mia Vermifuga", especie=self.especie
        )
        self.profissional = Profissional.objects.create(
            nome="Dra. Vermifuga", cargo="Veterinário"
        )
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional,
            crmv="CRMV-VERM-1",
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
            "produto": "Vermifugo Teste",
            "principio_ativo": "Praziquantel",
            "data_aplicacao": (self.hoje - timedelta(days=30)).isoformat(),
            "data_retorno": (self.hoje + timedelta(days=335)).isoformat(),
            "veterinario": str(self.veterinario.id),
            "peso_kg": "12.50",
            "dose": "1 comprimido",
            "lote": "LOTE-VERM-001",
            "via_administracao": "oral",
            "observacoes": "Sem reação.",
        }
        dados.update(extra)
        return dados

    def criar_vermifugacao_modelo(self, **extra):
        dados = {
            "pet": self.pet,
            "produto": "Vermifugo Teste",
            "data_aplicacao": self.hoje - timedelta(days=30),
        }
        dados.update(extra)
        return Vermifugacao.objects.create(**dados)

    # ------------------------------------------------------------------
    # RBAC
    # ------------------------------------------------------------------
    def test_recepcao_lista_mas_nao_cria(self):
        self.criar_vermifugacao_modelo()

        self.autenticar(self.recepcao)
        listagem = self.client.get("/api/v1/vermifugacoes/")
        self.assertEqual(listagem.status_code, 200)
        self.assertEqual(listagem.data["count"], 1)

        criacao = self.client.post(
            "/api/v1/vermifugacoes/", self.payload(), format="json"
        )
        self.assertEqual(criacao.status_code, 403)

    def test_recepcao_nao_edita_nem_exclui(self):
        vermifugacao = self.criar_vermifugacao_modelo()
        self.autenticar(self.recepcao)

        edicao = self.client.patch(
            f"/api/v1/vermifugacoes/{vermifugacao.id}/",
            {"produto": "Outro"},
            format="json",
        )
        self.assertEqual(edicao.status_code, 403)

        exclusao = self.client.delete(
            f"/api/v1/vermifugacoes/{vermifugacao.id}/"
        )
        self.assertEqual(exclusao.status_code, 403)

    def test_veterinario_cria_com_auditoria_e_autoria(self):
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vermifugacoes/", self.payload(), format="json"
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        vermifugacao = Vermifugacao.objects.get(pk=resposta.data["id"])
        self.assertEqual(vermifugacao.created_by, self.vet_user)
        self.assertEqual(vermifugacao.updated_by, self.vet_user)
        self.assertEqual(vermifugacao.lote, "LOTE-VERM-001")
        self.assertEqual(vermifugacao.via_administracao, "oral")
        self.assertEqual(str(vermifugacao.peso_kg), "12.50")

        log = AuditLog.objects.filter(
            entidade="prontuario.vermifugacao",
            entidade_id=str(vermifugacao.id),
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
            "/api/v1/vermifugacoes/",
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
            "/api/v1/vermifugacoes/",
            self.payload(
                data_aplicacao=(self.hoje - timedelta(days=10)).isoformat(),
                data_retorno=(self.hoje - timedelta(days=11)).isoformat(),
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("data_retorno", resposta.data)

    def test_peso_invalido_rejeitado(self):
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vermifugacoes/",
            self.payload(peso_kg="0"),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("peso_kg", resposta.data)

    def test_prontuario_de_outro_pet_rejeitado(self):
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vermifugacoes/",
            self.payload(prontuario=str(self.prontuario_outro_pet.id)),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("prontuario", resposta.data)

    def test_veterinario_com_cargo_invalido_rejeitado(self):
        Profissional.objects.filter(pk=self.profissional.pk).update(
            cargo="tosador"
        )
        self.autenticar(self.vet_user)
        resposta = self.client.post(
            "/api/v1/vermifugacoes/", self.payload(), format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("veterinario", resposta.data)

    # ------------------------------------------------------------------
    # Situação calculada e filtros
    # ------------------------------------------------------------------
    def test_situacao_calculada(self):
        atrasada = self.criar_vermifugacao_modelo(
            produto="Atrasada",
            data_aplicacao=self.hoje - timedelta(days=400),
            data_retorno=self.hoje - timedelta(days=1),
        )
        proxima = self.criar_vermifugacao_modelo(
            produto="Próxima",
            data_aplicacao=self.hoje - timedelta(days=350),
            data_retorno=self.hoje + timedelta(days=10),
        )
        em_dia = self.criar_vermifugacao_modelo(
            produto="Em dia",
            data_aplicacao=self.hoje - timedelta(days=10),
            data_retorno=self.hoje + timedelta(days=90),
        )
        sem_retorno = self.criar_vermifugacao_modelo(
            produto="Sem retorno",
            data_aplicacao=self.hoje - timedelta(days=5),
        )

        self.assertEqual(atrasada.situacao, Vermifugacao.Situacao.ATRASADA)
        self.assertEqual(proxima.situacao, Vermifugacao.Situacao.PROXIMA)
        self.assertEqual(em_dia.situacao, Vermifugacao.Situacao.EM_DIA)
        self.assertEqual(
            sem_retorno.situacao, Vermifugacao.Situacao.SEM_RETORNO
        )
        self.assertEqual(atrasada.dias_para_retorno, -1)

        self.autenticar(self.recepcao)
        resposta = self.client.get(f"/api/v1/vermifugacoes/?pet={self.pet.id}")
        self.assertEqual(resposta.status_code, 200)
        por_produto = {
            item["produto"]: item for item in resposta.data["results"]
        }
        self.assertEqual(por_produto["Atrasada"]["situacao"], "atrasada")
        self.assertEqual(
            por_produto["Próxima"]["situacao_display"],
            "Próxima do retorno",
        )

    def test_filtro_por_situacao(self):
        self.criar_vermifugacao_modelo(
            produto="Atrasada",
            data_aplicacao=self.hoje - timedelta(days=400),
            data_retorno=self.hoje - timedelta(days=1),
        )
        self.criar_vermifugacao_modelo(
            produto="Em dia",
            data_aplicacao=self.hoje - timedelta(days=10),
            data_retorno=self.hoje + timedelta(days=90),
        )
        self.autenticar(self.vet_user)

        resposta = self.client.get(
            "/api/v1/vermifugacoes/?situacao=atrasada"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 1)
        self.assertEqual(resposta.data["results"][0]["produto"], "Atrasada")

    def test_busca_por_tutor_principio_e_lote(self):
        self.criar_vermifugacao_modelo(
            produto="Vermifugo X",
            principio_ativo="Ivermectina",
            lote="LOTE-ABC",
        )
        self.autenticar(self.vet_user)

        por_tutor = self.client.get(
            "/api/v1/vermifugacoes/?search=Tutor Vermifugo"
        )
        self.assertEqual(por_tutor.data["count"], 1)

        por_principio = self.client.get(
            "/api/v1/vermifugacoes/?search=Ivermectina"
        )
        self.assertEqual(por_principio.data["count"], 1)

        por_lote = self.client.get("/api/v1/vermifugacoes/?search=LOTE-ABC")
        self.assertEqual(por_lote.data["count"], 1)

    def test_resumo_por_situacao(self):
        self.criar_vermifugacao_modelo(
            data_aplicacao=self.hoje - timedelta(days=400),
            data_retorno=self.hoje - timedelta(days=1),
        )
        self.criar_vermifugacao_modelo(
            data_aplicacao=self.hoje - timedelta(days=350),
            data_retorno=self.hoje + timedelta(days=10),
        )
        self.criar_vermifugacao_modelo(
            data_aplicacao=self.hoje - timedelta(days=10),
            data_retorno=self.hoje + timedelta(days=90),
        )
        self.criar_vermifugacao_modelo(
            data_aplicacao=self.hoje - timedelta(days=5),
        )
        self.autenticar(self.recepcao)

        resposta = self.client.get(
            f"/api/v1/vermifugacoes/resumo/?pet={self.pet.id}"
        )
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
    # Exclusão lógica e paginação
    # ------------------------------------------------------------------
    def test_exclusao_logica_preserva_historico(self):
        vermifugacao = self.criar_vermifugacao_modelo()
        self.autenticar(self.vet_user)

        resposta = self.client.delete(
            f"/api/v1/vermifugacoes/{vermifugacao.id}/"
        )
        self.assertEqual(resposta.status_code, 204)
        self.assertEqual(Vermifugacao.objects.count(), 0)
        self.assertEqual(Vermifugacao.all_objects.count(), 1)

        registro = Vermifugacao.all_objects.get(pk=vermifugacao.id)
        self.assertTrue(registro.is_deleted)
        self.assertEqual(registro.deleted_by, self.vet_user)
        self.assertTrue(
            AuditLog.objects.filter(
                entidade="prontuario.vermifugacao",
                entidade_id=str(vermifugacao.id),
                acao=AuditLog.Acao.EXCLUSAO,
            ).exists()
        )

    def test_paginacao_estavel_com_mesma_data(self):
        for indice in range(25):
            self.criar_vermifugacao_modelo(produto=f"Vermifugo {indice}")
        self.autenticar(self.recepcao)

        primeira = self.client.get("/api/v1/vermifugacoes/")
        segunda = self.client.get("/api/v1/vermifugacoes/?page=2")
        self.assertEqual(primeira.data["count"], 25)
        self.assertEqual(len(primeira.data["results"]), 20)
        self.assertEqual(len(segunda.data["results"]), 5)

        ids_primeira = {item["id"] for item in primeira.data["results"]}
        ids_segunda = {item["id"] for item in segunda.data["results"]}
        self.assertFalse(ids_primeira & ids_segunda)
