"""Testes de documentos veterinários gerados (receituário, atestado, etc.)."""

import hashlib
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import AuditLog
from apps.documentos.models import (
    DocumentoVeterinario,
    ModeloDocumento,
    SituacaoDocumento,
    StatusAssinatura,
)
from apps.pets.models import Especie, Pet
from apps.prontuario.models import Prontuario
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional, Veterinario

User = get_user_model()


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class DocumentoVeterinarioTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="vetmanager-doc-")
        self.override = override_settings(
            MEDIA_ROOT=self.media,
            DOCUMENTO_VERIFICACAO_URL="https://exemplo.test/validar",
            CLINICA_NOME="Clínica Teste",
            CLINICA_CIDADE="Fortaleza",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)

        self.admin = fazer_usuario("admin_dv", "admin")
        self.vet_user = fazer_usuario("vet_dv", "veterinario")
        self.rec = fazer_usuario("rec_dv", "recepcao")

        self.tutor = Tutor.objects.create(
            nome="Tutor Documento", telefone="11 99999-0000", cpf="123.456.789-00"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor", telefone="11 98888-0000"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex", especie=self.especie
        )
        self.outro_pet = Pet.objects.create(
            tutor=self.outro_tutor, nome="Mia", especie=self.especie
        )

        self.profissional = Profissional.objects.create(
            nome="Dra. Ana", cargo="Veterinário"
        )
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional, crmv="CRMV-TESTE-1", especialidade="Clínica"
        )
        self.prontuario = Prontuario.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
            diagnostico="Otite",
            prescricao="Antibiótico por 7 dias",
            observacoes="Sem complicações",
        )
        self.client = APIClient()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def autenticar(self, user):
        self.client.force_authenticate(user)
        return self.client

    def criar_rascunho(self, **extra):
        payload = {
            "tipo": "receituario",
            "pet": str(self.pet.id),
            "veterinario": str(self.veterinario.id),
            "titulo": "Receituário do Rex",
            "conteudo": "Prescrição: repouso e hidratação.",
        }
        payload.update(extra)
        self.autenticar(self.vet_user)
        return self.client.post(
            "/api/v1/documentos-veterinarios/", payload, format="json"
        )

    def emitir(self, doc_id):
        self.autenticar(self.vet_user)
        return self.client.post(
            f"/api/v1/documentos-veterinarios/{doc_id}/emitir/", {}, format="json"
        )

    def modelo_padrao(self, tipo="receituario"):
        return ModeloDocumento.objects.filter(tipo=tipo, versao=1).first()

    # ------------------------------------------------------------------
    # Criação e templates
    # ------------------------------------------------------------------
    def test_criar_rascunho_com_modelo_renderiza_marcadores(self):
        modelo = self.modelo_padrao()
        self.assertIsNotNone(modelo, "migração deve semear modelos padrão")
        resp = self.criar_rascunho(
            modelo=str(modelo.id),
            titulo="Receituário",
            conteudo="",
            prontuario=str(self.prontuario.id),
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        doc = DocumentoVeterinario.objects.get(pk=resp.data["id"])
        self.assertEqual(doc.situacao, SituacaoDocumento.RASCUNHO)
        self.assertIn("Rex", doc.conteudo)
        self.assertNotIn("{{", doc.conteudo)
        self.assertEqual(doc.hash_conteudo, DocumentoVeterinario.calcular_hash(doc.conteudo))
        self.assertTrue(doc.identificador.startswith("VM-"))
        self.assertEqual(doc.veterinario_id, self.veterinario.id)

    def test_criar_com_prontuario_preenche_veterinario(self):
        resp = self.criar_rascunho(
            veterinario=None,
            prontuario=str(self.prontuario.id),
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        doc = DocumentoVeterinario.objects.get(pk=resp.data["id"])
        self.assertEqual(doc.veterinario_id, self.veterinario.id)

    def test_rejeita_prontuario_de_outro_pet(self):
        outro_prontuario = Prontuario.objects.create(
            pet=self.outro_pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
        )
        resp = self.criar_rascunho(prontuario=str(outro_prontuario.id))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("prontuario", resp.data)

    def test_rejeita_tutor_divergente(self):
        resp = self.criar_rascunho(tutor=str(self.outro_tutor.id))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("tutor", resp.data)

    def test_declaracao_comparecimento_sem_veterinario(self):
        resp = self.criar_rascunho(
            tipo="declaracao_comparecimento",
            veterinario=None,
            conteudo="Declaro o comparecimento.",
        )
        self.assertEqual(resp.status_code, 201, resp.data)

    def test_conteudo_obrigatorio_sem_modelo(self):
        resp = self.criar_rascunho(conteudo="", modelo=None)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("conteudo", resp.data)

    # ------------------------------------------------------------------
    # Emissão, PDF e integridade
    # ------------------------------------------------------------------
    def test_emissao_gera_pdf_e_registra_auditoria(self):
        resp = self.criar_rascunho(prontuario=str(self.prontuario.id))
        doc_id = resp.data["id"]
        resp = self.emitir(doc_id)
        self.assertEqual(resp.status_code, 200, resp.data)

        doc = DocumentoVeterinario.objects.get(pk=doc_id)
        self.assertEqual(doc.situacao, SituacaoDocumento.EMITIDO)
        self.assertIsNotNone(doc.data_emissao)
        self.assertTrue(doc.pdf_caminho.endswith(".pdf"))
        self.assertGreater(doc.pdf_tamanho, 0)
        self.assertEqual(doc.emitido_por, self.vet_user)

        from django.core.files.storage import default_storage

        with default_storage.open(doc.pdf_caminho, "rb") as f:
            pdf = f.read()
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(hashlib.sha256(pdf).hexdigest(), doc.pdf_sha256)

        self.assertTrue(
            AuditLog.objects.filter(
                entidade="documentos.documentoveterinario",
                entidade_id=str(doc.id),
                acao=AuditLog.Acao.ATUALIZACAO,
                justificativa__icontains="Emissão",
            ).exists()
        )

    def test_download_exige_autenticacao(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)

        self.client.force_authenticate(None)
        resp = self.client.get(f"/api/v1/documentos-veterinarios/{doc_id}/download/")
        self.assertIn(resp.status_code, (401, 403))

        self.autenticar(self.rec)
        resp = self.client.get(f"/api/v1/documentos-veterinarios/{doc_id}/download/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_download_rascunho_sem_pdf_retorna_404(self):
        resp = self.criar_rascunho()
        self.autenticar(self.vet_user)
        resp = self.client.get(
            f"/api/v1/documentos-veterinarios/{resp.data['id']}/download/"
        )
        self.assertEqual(resp.status_code, 404)

    # ------------------------------------------------------------------
    # Permissões
    # ------------------------------------------------------------------
    def test_recepcao_nao_cria_mas_consulta(self):
        self.autenticar(self.rec)
        payload = {
            "tipo": "receituario",
            "pet": str(self.pet.id),
            "veterinario": str(self.veterinario.id),
            "titulo": "Tentativa",
            "conteudo": "Conteúdo",
        }
        resp = self.client.post(
            "/api/v1/documentos-veterinarios/", payload, format="json"
        )
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get("/api/v1/documentos-veterinarios/")
        self.assertEqual(resp.status_code, 200)

    def test_lista_veterinarios_expoe_id_e_nome_para_selecao(self):
        self.autenticar(self.vet_user)
        resp = self.client.get("/api/v1/veterinarios/")
        self.assertEqual(resp.status_code, 200, resp.data)
        resultados = resp.data.get("results", resp.data)
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["id"], str(self.veterinario.id))
        self.assertEqual(resultados[0]["profissional_nome"], "Dra. Ana")
        self.assertEqual(resultados[0]["crmv"], "CRMV-TESTE-1")

    def test_modelo_documento_somente_admin_escreve(self):
        self.autenticar(self.vet_user)
        resp = self.client.get("/api/v1/modelos-documento/")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            "/api/v1/modelos-documento/",
            {"tipo": "atestado", "nome": "Novo", "corpo": "Texto"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

        self.autenticar(self.admin)
        resp = self.client.post(
            "/api/v1/modelos-documento/",
            {"tipo": "atestado", "nome": "Novo", "corpo": "Texto"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def test_atualizar_emitido_bloqueado(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)
        self.autenticar(self.vet_user)
        resp = self.client.patch(
            f"/api/v1/documentos-veterinarios/{doc_id}/",
            {"conteudo": "Alterado"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_cancelar_exige_justificativa(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)
        self.autenticar(self.vet_user)
        resp = self.client.post(
            f"/api/v1/documentos-veterinarios/{doc_id}/cancelar/", {}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(
            f"/api/v1/documentos-veterinarios/{doc_id}/cancelar/",
            {"justificativa": "Erro de digitação"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        doc = DocumentoVeterinario.objects.get(pk=doc_id)
        self.assertEqual(doc.situacao, SituacaoDocumento.CANCELADO)
        self.assertEqual(doc.motivo_cancelamento, "Erro de digitação")

    def test_nova_versao_preserva_anterior(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)
        original = DocumentoVeterinario.objects.get(pk=doc_id)
        self.autenticar(self.vet_user)
        resp = self.client.post(
            f"/api/v1/documentos-veterinarios/{doc_id}/nova-versao/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        nova = DocumentoVeterinario.objects.get(pk=resp.data["id"])
        self.assertEqual(nova.versao, 2)
        self.assertEqual(nova.documento_anterior_id, original.id)
        self.assertEqual(nova.situacao, SituacaoDocumento.RASCUNHO)
        self.assertNotEqual(nova.identificador, original.identificador)

    # ------------------------------------------------------------------
    # Verificação pública de autenticidade
    # ------------------------------------------------------------------
    def test_verificar_publico_nao_expoe_conteudo(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)
        doc = DocumentoVeterinario.objects.get(pk=doc_id)

        self.client.force_authenticate(None)
        resp = self.client.get(
            f"/api/v1/documentos-veterinarios/verificar/{doc.identificador}/"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertNotIn("conteudo", resp.data)
        self.assertEqual(resp.data["identificador"], doc.identificador)
        self.assertTrue(resp.data["hash_confere"])
        self.assertTrue(resp.data["pdf_disponivel"])
        self.assertTrue(resp.data["pdf_hash_confere"])

    def test_verificar_detecta_conteudo_adulterado(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)
        doc = DocumentoVeterinario.objects.get(pk=doc_id)

        DocumentoVeterinario.objects.filter(pk=doc_id).update(conteudo="adulterado")

        self.client.force_authenticate(None)
        resp = self.client.get(
            f"/api/v1/documentos-veterinarios/verificar/{doc.identificador}/"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["hash_confere"])

    def test_verificar_codigo_inexistente_404(self):
        self.client.force_authenticate(None)
        resp = self.client.get(
            "/api/v1/documentos-veterinarios/verificar/VM-NAOEXISTE/"
        )
        self.assertEqual(resp.status_code, 404)

    # ------------------------------------------------------------------
    # Assinatura (apenas metadados)
    # ------------------------------------------------------------------
    def test_assinatura_registra_metadados_sem_alegar_validade(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)
        self.autenticar(self.vet_user)

        resp = self.client.post(
            f"/api/v1/documentos-veterinarios/{doc_id}/preparar-assinatura/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        doc = DocumentoVeterinario.objects.get(pk=doc_id)
        self.assertEqual(doc.assinatura_status, StatusAssinatura.PREPARADO)

        resp = self.client.post(
            f"/api/v1/documentos-veterinarios/{doc_id}/registrar-assinatura/",
            {
                "provedor": "Provedor Externo",
                "referencia": "REF-123",
                "hash_assinatura": "a" * 64,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        doc = DocumentoVeterinario.objects.get(pk=doc_id)
        self.assertEqual(doc.assinatura_status, StatusAssinatura.ASSINADO_EXTERNO)
        self.assertEqual(doc.assinatura_provedor, "Provedor Externo")
        self.assertEqual(doc.assinatura_referencia, "REF-123")
        self.assertIsNotNone(doc.assinado_em)
        self.assertIn(
            "Não representam assinatura digital qualificada",
            resp.data["assinatura_aviso"],
        )

    # ------------------------------------------------------------------
    # Exclusão
    # ------------------------------------------------------------------
    def test_emitido_nao_pode_ser_excluido(self):
        resp = self.criar_rascunho()
        doc_id = resp.data["id"]
        self.emitir(doc_id)
        self.autenticar(self.admin)
        resp = self.client.delete(
            f"/api/v1/documentos-veterinarios/{doc_id}/",
            {"justificativa": "Tentativa"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(DocumentoVeterinario.objects.filter(pk=doc_id).exists())
