"""Testes do portal do tutor: autenticação, isolamento e privacidade."""

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.atendimentos.models import Atendimento
from apps.documentos.models import DocumentoClinico, DocumentoVeterinario
from apps.pets.models import Especie, Pet
from apps.prescricao.models import Prescricao
from apps.prontuario.models import Vacina
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional, Veterinario

from . import services
from .models import (
    AcessoPortal,
    ConviteAcessoPortal,
    NotificacaoPortal,
    SessaoPortal,
    SolicitacaoAgendamento,
)

User = get_user_model()

SENHA = "SenhaForte!2026"
NOVA_SENHA = "NovaSenhaForte!2026"


class PortalBaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.grupo_admin, _ = Group.objects.get_or_create(name="admin")
        cls.grupo_recepcao, _ = Group.objects.get_or_create(name="recepcao")

        cls.interno = User.objects.create_user(
            username="recepcao_portal", password=SENHA
        )
        cls.interno.groups.add(cls.grupo_recepcao)
        cls.interno.groups.add(cls.grupo_admin)

        cls.tutor = Tutor.objects.create(
            nome="Ana Tutor",
            telefone="11999990001",
            email="ana@example.com",
        )
        cls.outro_tutor = Tutor.objects.create(
            nome="Bruno Tutor",
            telefone="11999990002",
            email="bruno@example.com",
        )
        cls.especie = Especie.objects.create(nome="Cão")
        cls.pet = Pet.objects.create(
            tutor=cls.tutor, especie=cls.especie, nome="Rex"
        )
        cls.outro_pet = Pet.objects.create(
            tutor=cls.outro_tutor, especie=cls.especie, nome="Bolt"
        )

        cls.user_tutor, cls.acesso_tutor = services.resgatar_convite(
            token=services.criar_convite(
                tutor=cls.tutor, email=cls.tutor.email
            )[1],
            username="ana_portal",
            password=SENHA,
            aceite_privacidade=True,
        )
        cls.user_outro, cls.acesso_outro = services.resgatar_convite(
            token=services.criar_convite(
                tutor=cls.outro_tutor, email=cls.outro_tutor.email
            )[1],
            username="bruno_portal",
            password=SENHA,
            aceite_privacidade=True,
        )

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client_interno = APIClient()
        self.client_outro = APIClient()
        mail.outbox = []

    def entrar_portal(self, username="ana_portal", senha=SENHA, client=None):
        client = client or self.client
        response = client.post(
            "/api/v1/portal/auth/login/",
            {"username": username, "password": senha},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def entrar_interno(self, username="recepcao_portal", senha=SENHA, client=None):
        client = client or self.client_interno
        response = client.post(
            "/api/v1/token/",
            {"username": username, "password": senha},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def criar_atendimento(self, pet=None, status=Atendimento.Status.AGENDADO, horas=24):
        return Atendimento.objects.create(
            pet=pet or self.pet,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
            data_hora_inicio=timezone.now() + timedelta(hours=horas),
            status=status,
        )

    def criar_documento_clinico(self, pet=None, liberado=False):
        return DocumentoClinico.objects.create(
            pet=pet or self.pet,
            tipo="exame_laboratorial",
            nome_original="exame.pdf",
            nome_interno=f"arquivo-{timezone.now().timestamp()}.pdf",
            caminho_arquivo="documentos/nao-existe.pdf",
            tamanho=10,
            mime_type="application/pdf",
            liberado_portal=liberado,
        )

    def criar_documento_veterinario(self, pet=None, liberado=False):
        return DocumentoVeterinario.objects.create(
            tipo="receituario",
            pet=pet or self.pet,
            tutor=(pet or self.pet).tutor,
            titulo="Receituário",
            conteudo="Conteúdo clínico",
            situacao="emitido",
            data_emissao=timezone.now(),
            liberado_portal=liberado,
        )

    def criar_veterinario(self, nome="Dra. Carla", crmv="CRMV-123"):
        profissional = Profissional.objects.create(
            nome=nome, cargo=Profissional.Cargo.VETERINARIO
        )
        return Veterinario.objects.create(profissional=profissional, crmv=crmv)


class PortalAutenticacaoTests(PortalBaseTestCase):
    def test_login_cria_sessao_e_cookies_http_only(self):
        response = self.entrar_portal()
        self.assertIn("portal_access", response.cookies)
        self.assertIn("portal_refresh", response.cookies)
        self.assertTrue(response.cookies["portal_access"]["httponly"])
        self.assertTrue(response.cookies["portal_refresh"]["httponly"])
        self.assertEqual(
            SessaoPortal.objects.filter(acesso=self.acesso_tutor).count(), 1
        )

    def test_login_sem_vinculo_e_rejeitado(self):
        User.objects.create_user(username="sem_portal", password=SENHA)
        response = self.client.post(
            "/api/v1/portal/auth/login/",
            {"username": "sem_portal", "password": SENHA},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_token_interno_nao_abre_portal(self):
        self.entrar_interno()
        access_interno = self.client_interno.cookies["access"].value
        self.client.cookies["portal_access"] = access_interno
        response = self.client.get("/api/v1/portal/perfil/")
        self.assertEqual(response.status_code, 401)

    def test_token_de_portal_nao_abre_api_interna(self):
        self.entrar_portal()
        access_portal = self.client.cookies["portal_access"].value
        self.client_interno.cookies["access"] = access_portal
        response = self.client_interno.get("/api/v1/tutores/")
        self.assertEqual(response.status_code, 401)

    def test_refresh_rotaciona_e_rejeita_reuso(self):
        self.entrar_portal()
        refresh_antigo = self.client.cookies["portal_refresh"].value
        response = self.client.post("/api/v1/portal/auth/refresh/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(
            refresh_antigo, self.client.cookies["portal_refresh"].value
        )

        reuso = APIClient()
        reuso.cookies["portal_refresh"] = refresh_antigo
        response = reuso.post("/api/v1/portal/auth/refresh/", {}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_logout_revoga_sessao_e_limpa_cookies(self):
        self.entrar_portal()
        response = self.client.post("/api/v1/portal/auth/logout/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/portal/perfil/").status_code, 401)

    def test_recuperacao_e_redefinicao_de_senha(self):
        response = self.client.post(
            "/api/v1/portal/auth/recuperar-senha/",
            {"email": self.tutor.email},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        token = re.search(r"token=([\w\-]+)", mail.outbox[0].body).group(1)

        response = self.client.post(
            "/api/v1/portal/auth/redefinir-senha/",
            {
                "token": token,
                "nova_senha": NOVA_SENHA,
                "confirmar_nova_senha": NOVA_SENHA,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        # O token é de uso único.
        response = self.client.post(
            "/api/v1/portal/auth/redefinir-senha/",
            {
                "token": token,
                "nova_senha": NOVA_SENHA,
                "confirmar_nova_senha": NOVA_SENHA,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            self.client.post(
                "/api/v1/portal/auth/login/",
                {"username": "ana_portal", "password": SENHA},
                format="json",
            ).status_code,
            401,
        )
        self.entrar_portal(senha=NOVA_SENHA)

    def test_recuperacao_para_email_desconhecido_nao_revela_nada(self):
        response = self.client.post(
            "/api/v1/portal/auth/recuperar-senha/",
            {"email": "ninguem@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), 0)


class PortalConviteTests(PortalBaseTestCase):
    def test_convite_exige_usuario_interno_autorizado(self):
        self.entrar_portal()
        response = self.client.post(
            "/api/v1/portal-admin/convites/",
            {"tutor": str(self.tutor.id), "email": "novo@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)

    def test_resgate_cria_vinculo_e_nao_cria_grupo_interno(self):
        self.entrar_interno()
        response = self.client_interno.post(
            "/api/v1/portal-admin/convites/",
            {"tutor": str(self.outro_tutor.id), "email": "outro@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        token = response.data["token"]

        publico = APIClient()
        response = publico.post(
            "/api/v1/portal/convites/resgatar/",
            {
                "token": token,
                "username": "novo_portal",
                "password": SENHA,
                "confirmar_senha": SENHA,
                "aceite_privacidade": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        novo = User.objects.get(username="novo_portal")
        self.assertFalse(novo.is_staff)
        self.assertFalse(novo.groups.exists())
        acesso = AcessoPortal.objects.get(user=novo, tutor=self.outro_tutor)
        self.assertTrue(acesso.ativo)
        self.assertIsNotNone(acesso.consentimento_privacidade_em)

        # Reutilização do mesmo convite é recusada.
        response = publico.post(
            "/api/v1/portal/convites/resgatar/",
            {
                "token": token,
                "username": "outro_nome",
                "password": SENHA,
                "confirmar_senha": SENHA,
                "aceite_privacidade": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_resgate_sem_aceite_de_privacidade_falha(self):
        convite, token = services.criar_convite(
            tutor=self.tutor, email="semaceite@example.com"
        )
        response = APIClient().post(
            "/api/v1/portal/convites/resgatar/",
            {
                "token": token,
                "username": "semaceite",
                "password": SENHA,
                "confirmar_senha": SENHA,
                "aceite_privacidade": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="semaceite").exists())

    def test_convite_expirado_e_revogado_nao_sao_utilizaveis(self):
        convite, token = services.criar_convite(
            tutor=self.tutor, email="expira@example.com"
        )
        convite.expira_em = timezone.now() - timedelta(minutes=1)
        convite.save(update_fields=["expira_em", "updated_at"])
        with self.assertRaises(Exception):
            services.resgatar_convite(
                token=token,
                username="expirado",
                password=SENHA,
                aceite_privacidade=True,
            )

        convite2, token2 = services.criar_convite(
            tutor=self.tutor, email="revoga@example.com"
        )
        services.revogar_convite(convite2)
        with self.assertRaises(Exception):
            services.resgatar_convite(
                token=token2,
                username="revogado",
                password=SENHA,
                aceite_privacidade=True,
            )

    def test_revogacao_de_acesso_invalida_sessao(self):
        self.entrar_portal()
        self.assertEqual(
            self.client.get("/api/v1/portal/perfil/").status_code, 200
        )

        self.entrar_interno()
        response = self.client_interno.post(
            f"/api/v1/portal-admin/acessos/{self.acesso_tutor.id}/revogar/",
            {"motivo": "Teste de revogação"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.assertEqual(
            self.client.get("/api/v1/portal/perfil/").status_code, 401
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/portal/auth/login/",
                {"username": "ana_portal", "password": SENHA},
                format="json",
            ).status_code,
            401,
        )


class PortalIsolamentoTests(PortalBaseTestCase):
    def test_tutor_ve_somente_seus_animais(self):
        self.entrar_portal()
        response = self.client.get("/api/v1/portal/pets/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(self.pet.id)})

        response = self.client.get(f"/api/v1/portal/pets/{self.outro_pet.id}/")
        self.assertEqual(response.status_code, 404)

    def test_consultas_filtram_por_tutor_mesmo_com_pet_id_de_outro(self):
        self.entrar_portal()
        resposta = self.client.get(
            "/api/v1/portal/agendamentos/", {"pet": str(self.outro_pet.id)}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["results"], [])

        resposta = self.client.get(
            "/api/v1/portal/vacinas/", {"pet": str(self.outro_pet.id)}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["results"], [])

    def test_agendamentos_mostram_apenas_os_do_tutor(self):
        meu = self.criar_atendimento()
        self.criar_atendimento(pet=self.outro_pet)
        self.entrar_portal()
        response = self.client.get("/api/v1/portal/agendamentos/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(meu.id)})

    def test_solicitacao_nao_aceita_animal_de_outro_tutor(self):
        self.entrar_portal()
        response = self.client.post(
            "/api/v1/portal/solicitacoes-agendamento/",
            {
                "pet": str(self.outro_pet.id),
                "tipo_servico": "consulta",
                "data_preferida": (timezone.localdate() + timedelta(days=3)).isoformat(),
                "periodo": "manha",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_solicitacao_cria_e_pode_ser_cancelada_pelo_tutor(self):
        self.entrar_portal()
        response = self.client.post(
            "/api/v1/portal/solicitacoes-agendamento/",
            {
                "pet": str(self.pet.id),
                "tipo_servico": "consulta",
                "data_preferida": (timezone.localdate() + timedelta(days=3)).isoformat(),
                "periodo": "tarde",
                "observacoes": "Prefiro à tarde",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        solicitacao_id = response.data["id"]

        response = self.client.post(
            f"/api/v1/portal/solicitacoes-agendamento/{solicitacao_id}/cancelar/",
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "cancelada")

    def test_solicitacao_nao_pode_ser_cancelada_por_outro_tutor(self):
        solicitacao = SolicitacaoAgendamento.objects.create(
            tutor=self.outro_tutor,
            pet=self.outro_pet,
            tipo_servico="consulta",
            data_preferida=timezone.localdate() + timedelta(days=2),
        )
        self.entrar_portal()
        response = self.client.post(
            f"/api/v1/portal/solicitacoes-agendamento/{solicitacao.id}/cancelar/",
            format="json",
        )
        self.assertEqual(response.status_code, 404)


class PortalPrivacidadeTests(PortalBaseTestCase):
    def test_documentos_so_aparecem_quando_liberados(self):
        liberado = self.criar_documento_clinico(liberado=True)
        self.criar_documento_clinico(liberado=False)
        vet_liberado = self.criar_documento_veterinario(liberado=True)
        self.criar_documento_veterinario(liberado=False)

        self.entrar_portal()
        response = self.client.get("/api/v1/portal/documentos/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data}
        self.assertEqual(ids, {str(liberado.id), str(vet_liberado.id)})

    def test_documento_de_outro_tutor_nao_aparece(self):
        self.criar_documento_clinico(pet=self.outro_pet, liberado=True)
        self.entrar_portal()
        response = self.client.get("/api/v1/portal/documentos/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_prescricoes_so_aparecem_quando_liberadas(self):
        veterinario = self.criar_veterinario()
        liberada = Prescricao.objects.create(
            pet=self.pet, veterinario=veterinario, liberado_portal=True
        )
        Prescricao.objects.create(
            pet=self.pet, veterinario=veterinario, liberado_portal=False
        )
        Prescricao.objects.create(
            pet=self.outro_pet,
            veterinario=veterinario,
            liberado_portal=True,
        )

        self.entrar_portal()
        response = self.client.get("/api/v1/portal/prescricoes/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(liberada.id)})

    def test_vacinas_mostram_apenas_as_do_tutor(self):
        minha = Vacina.objects.create(
            pet=self.pet,
            nome_vacina="V10",
            data_aplicacao=timezone.localdate(),
        )
        Vacina.objects.create(
            pet=self.outro_pet,
            nome_vacina="Antirrábica",
            data_aplicacao=timezone.localdate(),
        )
        self.entrar_portal()
        response = self.client.get("/api/v1/portal/vacinas/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {minha.id})

    def test_notificacoes_sao_isoladas_e_marcadas_como_lidas(self):
        minha = NotificacaoPortal.objects.create(
            tutor=self.tutor, titulo="Sua vacina", mensagem="Rex está na hora."
        )
        alheia = NotificacaoPortal.objects.create(
            tutor=self.outro_tutor, titulo="Outro", mensagem="Privado."
        )
        self.entrar_portal()
        response = self.client.get("/api/v1/portal/notificacoes/")
        self.assertEqual(response.status_code, 200)
        ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(ids, {str(minha.id)})

        response = self.client.post(
            f"/api/v1/portal/notificacoes/{minha.id}/marcar-lida/", format="json"
        )
        self.assertEqual(response.status_code, 200)
        minha.refresh_from_db()
        self.assertTrue(minha.lida)

        response = self.client.post(
            f"/api/v1/portal/notificacoes/{alheia.id}/marcar-lida/", format="json"
        )
        self.assertEqual(response.status_code, 404)

    def test_perfil_nao_permite_alterar_cpf_nem_vinculo(self):
        self.entrar_portal()
        cpf_original = self.tutor.cpf
        response = self.client.patch(
            "/api/v1/portal/perfil/",
            {"nome": "Ana Maria", "cpf": "123.456.789-00", "email": "novo@example.com"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.tutor.refresh_from_db()
        self.assertEqual(self.tutor.nome, "Ana Maria")
        self.assertEqual(self.tutor.cpf, cpf_original)
        self.assertEqual(self.tutor.email, "novo@example.com")

    def test_alterar_senha_revoga_outras_sessoes(self):
        self.entrar_portal()
        outro_dispositivo = APIClient()
        self.entrar_portal(client=outro_dispositivo)

        response = self.client.post(
            "/api/v1/portal/perfil/alterar-senha/",
            {
                "senha_atual": SENHA,
                "nova_senha": NOVA_SENHA,
                "confirmar_nova_senha": NOVA_SENHA,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self.client.get("/api/v1/portal/perfil/").status_code, 200
        )
        self.assertEqual(
            outro_dispositivo.get("/api/v1/portal/perfil/").status_code, 401
        )


class PortalAdminTests(PortalBaseTestCase):
    def test_admin_aprova_solicitacao_e_gera_notificacao(self):
        self.entrar_portal()
        resposta = self.client.post(
            "/api/v1/portal/solicitacoes-agendamento/",
            {
                "pet": str(self.pet.id),
                "tipo_servico": "consulta",
                "data_preferida": (timezone.localdate() + timedelta(days=4)).isoformat(),
            },
            format="json",
        )
        solicitacao_id = resposta.data["id"]

        self.entrar_interno()
        response = self.client_interno.post(
            f"/api/v1/portal-admin/solicitacoes/{solicitacao_id}/aprovar/",
            {"resposta": "Confirmado para 10h."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "aprovada")

        response = self.client_interno.post(
            "/api/v1/portal-admin/notificacoes/",
            {
                "tutor": str(self.tutor.id),
                "pet": str(self.pet.id),
                "tipo": "agendamento",
                "titulo": "Agendamento confirmado",
                "mensagem": "Seu pedido foi aprovado.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        response = self.client.get("/api/v1/portal/notificacoes/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_liberacao_de_documento_exige_admin_e_audita(self):
        documento = self.criar_documento_clinico(liberado=False)
        self.entrar_interno()
        response = self.client_interno.post(
            "/api/v1/portal-admin/liberacoes/",
            {
                "tipo": "clinico",
                "id": str(documento.id),
                "liberado": True,
                "motivo": "Liberado a pedido do tutor",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        documento.refresh_from_db()
        self.assertTrue(documento.liberado_portal)

        self.entrar_portal()
        response = self.client.get("/api/v1/portal/documentos/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_liberacao_de_prescricao_reflete_no_portal(self):
        veterinario = self.criar_veterinario()
        prescricao = Prescricao.objects.create(
            pet=self.pet, veterinario=veterinario, liberado_portal=False
        )
        self.entrar_interno()
        response = self.client_interno.post(
            "/api/v1/portal-admin/liberacoes/",
            {"tipo": "prescricao", "id": str(prescricao.id), "liberado": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.entrar_portal()
        response = self.client.get("/api/v1/portal/prescricoes/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
