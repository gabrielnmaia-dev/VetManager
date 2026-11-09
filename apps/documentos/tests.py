"""Testes de documentos clínicos (upload, download, validação, permissões)."""

import os
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.auditoria.models import AuditLog
from apps.documentos.models import DocumentoClinico
from apps.pets.models import Pet, Especie
from apps.tutores.models import Tutor

User = get_user_model()


def fazer_usuario(username, grupo, senha="senha123"):
    user = User.objects.create_user(username=username, password=senha)
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


def autenticar(client, user):
    client.force_authenticate(user)
    return client


class DocumentoClinicoTests(TestCase):
    """Testes de upload, download, validação e permissões de documentos."""

    def setUp(self):
        self.admin = fazer_usuario("admin_doc", "admin")
        self.vet = fazer_usuario("vet_doc", "veterinario")
        self.rec = fazer_usuario("rec_doc", "recepcao")
        self.client = APIClient()

        self.tutor = Tutor.objects.create(nome="Tutor Doc", telefone="11 99999-9999")
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex", especie=self.especie
        )

    def _criar_arquivo_pdf(self, nome="teste.pdf", conteudo=b"%PDF-1.4 fake"):
        return SimpleUploadedFile(nome, conteudo, content_type="application/pdf")

    def _criar_arquivo_invalido(self, nome="malware.exe", conteudo=b"MZ"):
        return SimpleUploadedFile(nome, conteudo, content_type="application/x-msdownload")

    def test_upload_pdf_valido(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        arquivo = self._criar_arquivo_pdf()
        payload = {
            "pet": str(self.pet.id),
            "tipo": "exame_laboratorial",
            "data_exame": "2026-11-01",
            "descricao": "Hemograma completo",
            "arquivo": arquivo,
        }
        resp = self.client.post(
            "/api/v1/documentos-clinicos/", payload, format="multipart"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(DocumentoClinico.objects.count(), 1)
        doc = DocumentoClinico.objects.first()
        self.assertEqual(doc.nome_original, "teste.pdf")
        self.assertEqual(doc.tipo, "exame_laboratorial")
        self.assertEqual(doc.usuario, self.vet)
        self.assertTrue(doc.nome_interno.endswith(".pdf"))
        self.assertTrue(doc.tamanho > 0)
        self.assertEqual(doc.mime_type, "application/pdf")

    def test_upload_arquivo_executavel_rejeitado(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        arquivo = self._criar_arquivo_invalido()
        payload = {
            "pet": str(self.pet.id),
            "tipo": "outro",
            "arquivo": arquivo,
        }
        resp = self.client.post(
            "/api/v1/documentos-clinicos/", payload, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DocumentoClinico.objects.count(), 0)

    def test_upload_sem_arquivo_rejeitado(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        payload = {
            "pet": str(self.pet.id),
            "tipo": "outro",
        }
        resp = self.client.post(
            "/api/v1/documentos-clinicos/", payload, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DocumentoClinico.objects.count(), 0)

    def test_listar_documentos(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        # Cria alguns documentos
        for i in range(3):
            arquivo = self._criar_arquivo_pdf(f"doc{i}.pdf")
            DocumentoClinico.objects.create(
                pet=self.pet,
                usuario=self.vet,
                tipo="laudo",
                nome_original=arquivo.name,
                nome_interno=f"fake{i}.pdf",
                caminho_arquivo=f"documentos/fake{i}.pdf",
                tamanho=100,
                mime_type="application/pdf",
            )

        resp = self.client.get("/api/v1/documentos-clinicos/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 3)

    def test_filtro_por_pet(self):
        autenticar(self.client, self.rec)
        grupo_rec, _ = Group.objects.get_or_create(name="recepcao")
        self.rec.groups.add(grupo_rec)

        outro_tutor = Tutor.objects.create(nome="Outro Tutor", telefone="11 88888-8888")
        outro_pet = Pet.objects.create(tutor=outro_tutor, nome="Miau", especie=self.especie)

        arquivo1 = self._criar_arquivo_pdf(f"doc_pet1_{self.pet.id}.pdf")
        arquivo2 = self._criar_arquivo_pdf(f"doc_pet2_{outro_pet.id}.pdf")
        DocumentoClinico.objects.create(
            pet=self.pet,
            usuario=self.vet,
            tipo="laudo",
            nome_original=arquivo1.name,
            nome_interno=f"fake_{self.pet.id}_{arquivo1.name}",
            caminho_arquivo=f"documentos/fake_{self.pet.id}_{arquivo1.name}",
            tamanho=100,
            mime_type="application/pdf",
        )
        DocumentoClinico.objects.create(
            pet=outro_pet,
            usuario=self.vet,
            tipo="laudo",
            nome_original=arquivo2.name,
            nome_interno=f"fake_{outro_pet.id}_{arquivo2.name}",
            caminho_arquivo=f"documentos/fake_{outro_pet.id}_{arquivo2.name}",
            tamanho=100,
            mime_type="application/pdf",
        )

        resp = self.client.get("/api/v1/documentos-clinicos/", {"pet": str(self.pet.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["results"]), 1)
        self.assertEqual(resp.json()["results"][0]["pet"], str(self.pet.id))

    def test_nao_autenticado_negado(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/api/v1/documentos-clinicos/")
        self.assertEqual(resp.status_code, 401)

    def test_download_arquivo(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        arquivo = self._criar_arquivo_pdf()
        resp = self.client.post(
            "/api/v1/documentos-clinicos/",
            {
                "pet": str(self.pet.id),
                "tipo": "laudo",
                "arquivo": arquivo,
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        doc_id = resp.json()["id"]

        # Tenta download
        resp_download = self.client.get(f"/api/v1/documentos-clinicos/{doc_id}/download/")
        self.assertEqual(resp_download.status_code, 200)
        self.assertIn('filename="teste.pdf"', resp_download["Content-Disposition"])
        self.assertEqual(resp_download["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp_download["X-Frame-Options"], "DENY")
        self.assertEqual(resp_download.content, b"%PDF-1.4 fake")

    def test_download_arquivo_nao_encontrado(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        # Cria documento com caminho inexistente
        doc = DocumentoClinico.objects.create(
            pet=self.pet,
            usuario=self.vet,
            tipo="laudo",
            nome_original="inexistente.pdf",
            nome_interno="inexistente.pdf",
            caminho_arquivo="documentos/inexistente.pdf",
            tamanho=100,
            mime_type="application/pdf",
        )

        resp = self.client.get(f"/api/v1/documentos-clinicos/{doc.id}/download/")
        self.assertEqual(resp.status_code, 404)

    def test_upload_executavel_disfarcado_rejeitado(self):
        """Arquivo com extensão .pdf mas conteúdo executável é rejeitado."""
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        arquivo = SimpleUploadedFile(
            "exame.pdf", b"MZ\x90\x00conteudo-executavel", content_type="application/pdf"
        )
        resp = self.client.post(
            "/api/v1/documentos-clinicos/",
            {"pet": str(self.pet.id), "tipo": "laudo", "arquivo": arquivo},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DocumentoClinico.objects.count(), 0)

    def test_autoria_e_auditoria_no_upload(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        resp = self.client.post(
            "/api/v1/documentos-clinicos/",
            {
                "pet": str(self.pet.id),
                "tipo": "laudo",
                "arquivo": self._criar_arquivo_pdf(),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)

        doc = DocumentoClinico.objects.get(id=resp.json()["id"])
        self.assertEqual(doc.created_by, self.vet)
        self.assertEqual(doc.updated_by, self.vet)
        self.assertEqual(doc.usuario, self.vet)

        log = AuditLog.objects.filter(
            entidade="documentos.documentoclinico",
            entidade_id=str(doc.id),
            acao=AuditLog.Acao.CRIACAO,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.usuario, self.vet)

    def test_exclusao_logica_preserva_arquivo(self):
        autenticar(self.client, self.vet)
        grupo_vet, _ = Group.objects.get_or_create(name="veterinario")
        self.vet.groups.add(grupo_vet)

        resp = self.client.post(
            "/api/v1/documentos-clinicos/",
            {
                "pet": str(self.pet.id),
                "tipo": "laudo",
                "arquivo": self._criar_arquivo_pdf(),
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        doc = DocumentoClinico.objects.get(id=resp.json()["id"])
        caminho = doc.caminho_arquivo
        self.assertTrue(default_storage.exists(caminho))

        # DELETE padrão = exclusão lógica; arquivo permanece para retenção.
        resp_del = self.client.delete(f"/api/v1/documentos-clinicos/{doc.id}/")
        self.assertEqual(resp_del.status_code, 204)
        doc.refresh_from_db()
        self.assertTrue(doc.is_deleted)
        self.assertEqual(doc.deleted_by, self.vet)
        self.assertTrue(default_storage.exists(caminho))

        # A listagem padrão não mostra o documento excluído.
        resp_list = self.client.get("/api/v1/documentos-clinicos/")
        ids = [d["id"] for d in resp_list.json()["results"]]
        self.assertNotIn(str(doc.id), ids)

        # Remoção física explícita apaga o arquivo.
        doc.hard_delete()
        self.assertFalse(default_storage.exists(caminho))
