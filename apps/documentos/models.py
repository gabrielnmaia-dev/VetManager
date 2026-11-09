"""Modelos de documentos e anexos clínicos.

Armazena anexos privados (exames, laudos, radiografias, fotografias, etc.)
com controle de acesso rigoroso e nomes internos aleatórios para evitar
acesso direto por URL previsível.

O armazenamento é feito no sistema de arquivos local por padrão, com
suporte preparado para S3 (basta configurar AWS settings e o STORAGE_BACKEND).
"""

import os
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models

from apps.base.models import BaseModel
from apps.pets.models import Pet

from .services import detectar_mime_type


class TipoDocumento(models.TextChoices):
    EXAME_LABORATORIAL = "exame_laboratorial", "Exame Laboratorial"
    RADIOGRAFIA = "radiografia", "Radiografia"
    ULTRASSONOGRAFIA = "ultrassonografia", "Ultrassonografia"
    FOTOGRAFIA_CLINICA = "fotografia_clinica", "Fotografia Clínica"
    LAUDO = "laudo", "Laudo"
    PDF = "pdf", "PDF"
    DOCUMENTO_EXTERNO = "documento_externo", "Documento Externo"
    OUTRO = "outro", "Outro"


class DocumentoClinico(BaseModel):
    """Registro de anexo clínico com arquivo armazenado de forma privada.

    O arquivo físico é gravado em diretório não acessível diretamente pela
    web. O download é feito por endpoint autenticado que serve o conteúdo
    com cabeçalhos de segurança adequados.
    """

    pet = models.ForeignKey(
        Pet,
        on_delete=models.CASCADE,
        related_name="documentos_clinicos",
        verbose_name="pet",
    )
    prontuario = models.ForeignKey(
        "prontuario.Prontuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos",
        verbose_name="prontuário",
    )
    atendimento = models.ForeignKey(
        "atendimentos.Atendimento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos",
        verbose_name="atendimento",
    )

    tipo = models.CharField(
        max_length=30,
        choices=TipoDocumento.choices,
        default=TipoDocumento.OUTRO,
        verbose_name="tipo de documento",
    )
    nome_original = models.CharField(
        max_length=255,
        verbose_name="nome original",
    )
    nome_interno = models.CharField(
        max_length=255,
        unique=True,
        editable=False,
        verbose_name="nome interno",
        help_text="Nome aleatório do arquivo no armazenamento.",
    )
    caminho_arquivo = models.CharField(
        max_length=500,
        editable=False,
        verbose_name="caminho do arquivo",
    )
    tamanho = models.PositiveIntegerField(
        editable=False,
        verbose_name="tamanho (bytes)",
    )
    mime_type = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="MIME type",
    )
    data_exame = models.DateField(
        null=True,
        blank=True,
        verbose_name="data do exame",
    )
    data_envio = models.DateTimeField(
        auto_now_add=True,
        verbose_name="data de envio",
    )
    descricao = models.TextField(
        blank=True,
        verbose_name="descrição",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_enviados",
        verbose_name="usuário responsável",
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["-criado_em"]
        verbose_name = "documento clínico"
        verbose_name_plural = "documentos clínicos"
        indexes = [
            models.Index(fields=["pet", "-criado_em"]),
            models.Index(fields=["prontuario"]),
            models.Index(fields=["atendimento"]),
            models.Index(fields=["tipo"]),
            models.Index(fields=["usuario", "-criado_em"]),
        ]

    def __str__(self):
        return f"{self.nome_original} ({self.get_tipo_display()})"

    @property
    def extensao(self):
        """Retorna a extensão do arquivo original."""
        return os.path.splitext(self.nome_original)[1].lower()

    def salvar_arquivo(self, arquivo_upload):
        """Salva o arquivo enviado no armazenamento privado.

        Gera um nome interno aleatório (UUID + extensão) e grava em
        ``MEDIA_ROOT/documentos/``, diretório que nunca é exposto
        publicamente. O MIME type é detectado a partir do conteúdo.
        """
        ext = os.path.splitext(arquivo_upload.name or "")[1].lower()
        self.nome_interno = f"{uuid.uuid4().hex}{ext}"
        self.caminho_arquivo = f"documentos/{self.nome_interno}"

        self.mime_type = self.mime_type or detectar_mime_type(arquivo_upload)

        conteudo = arquivo_upload.read()
        self.tamanho = len(conteudo)

        # Garante a existência do diretório para storages locais.
        try:
            os.makedirs(
                os.path.dirname(default_storage.path(self.caminho_arquivo)),
                exist_ok=True,
            )
        except Exception:
            # Storages remotos (ex.: S3) não implementam ``path``.
            pass

        self.caminho_arquivo = default_storage.save(
            self.caminho_arquivo,
            ContentFile(conteudo),
        )

    def excluir_arquivo(self):
        """Remove o arquivo físico do armazenamento (silenciosamente)."""
        if self.caminho_arquivo:
            try:
                default_storage.delete(self.caminho_arquivo)
            except Exception:
                pass

    def get_absolute_url(self):
        """URL para download através do endpoint autenticado."""
        return f"/api/v1/documentos-clinicos/{self.id}/download/"

    def save(self, *args, **kwargs):
        # Não grava o arquivo físico aqui; o serializer/view cuida disso.
        return super().save(*args, **kwargs)

    def hard_delete(self, using=None, keep_parents=False):
        """Remoção física: apaga também o arquivo do armazenamento.

        A exclusão padrão (``delete``) é lógica e preserva o arquivo e o
        registro para fins de retenção clínica e auditoria.
        """
        self.excluir_arquivo()
        return super().hard_delete(using=using, keep_parents=keep_parents)
