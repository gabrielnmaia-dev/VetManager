"""Modelos de documentos e anexos clínicos.

Armazena anexos privados (exames, laudos, radiografias, fotografias, etc.)
com controle de acesso rigoroso e nomes internos aleatórios para evitar
acesso direto por URL previsível.

O armazenamento é feito no sistema de arquivos local por padrão, com
suporte preparado para S3 (basta configurar AWS settings e o STORAGE_BACKEND).
"""

import hashlib
import os
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import models
from django.utils import timezone

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

    # Liberação explícita para o portal do tutor. O padrão é NÃO expor:
    # o portal só mostra o que a clínica liberar individualmente.
    liberado_portal = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="liberado no portal do tutor",
    )
    liberado_portal_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="liberado no portal em",
    )
    liberado_portal_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="liberado no portal por",
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


# ---------------------------------------------------------------------------
# Documentos veterinários gerados (receituário, atestado, laudo, etc.)
# ---------------------------------------------------------------------------


class TipoDocumentoVeterinario(models.TextChoices):
    RECEITUARIO = "receituario", "Receituário"
    ATESTADO = "atestado", "Atestado"
    LAUDO = "laudo", "Laudo"
    ENCAMINHAMENTO = "encaminhamento", "Encaminhamento"
    RELATORIO_CLINICO = "relatorio_clinico", "Relatório Clínico"
    DECLARACAO_COMPARECIMENTO = (
        "declaracao_comparecimento",
        "Declaração de Comparecimento",
    )
    DOCUMENTO_ALTA = "documento_alta", "Documento de Alta"


class SituacaoDocumento(models.TextChoices):
    RASCUNHO = "rascunho", "Rascunho"
    EMITIDO = "emitido", "Emitido"
    CANCELADO = "cancelado", "Cancelado"


class StatusAssinatura(models.TextChoices):
    NAO_ASSINADO = "nao_assinado", "Não assinado"
    PREPARADO = "preparado", "Preparado para assinatura"
    ASSINADO_EXTERNO = "assinado_externo", "Assinado externamente"


def gerar_identificador() -> str:
    """Gera o identificador público de autenticidade do documento.

    O identificador não carrega dados clínicos e não é sequencial, evitando
    enumeração de documentos.
    """
    return f"VM-{uuid.uuid4().hex[:12].upper()}"


class ModeloDocumento(BaseModel):
    """Template editável usado para gerar documentos veterinários.

    O corpo aceita marcadores no formato ``{{ nome_do_campo }}``. Os campos
    disponíveis são documentados em ``apps.documentos.services``.
    """

    tipo = models.CharField(
        max_length=40,
        choices=TipoDocumentoVeterinario.choices,
        verbose_name="tipo de documento",
    )
    nome = models.CharField(max_length=150, verbose_name="nome do modelo")
    corpo = models.TextField(
        verbose_name="corpo do modelo",
        help_text="Use marcadores como {{pet_nome}} e {{tutor_nome}}.",
    )
    ativo = models.BooleanField(default=True, verbose_name="ativo")
    versao = models.PositiveIntegerField(default=1, verbose_name="versão")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["tipo", "nome", "-versao"]
        verbose_name = "modelo de documento"
        verbose_name_plural = "modelos de documento"
        constraints = [
            models.UniqueConstraint(
                fields=["tipo", "nome", "versao"],
                name="documento_modelo_unico_por_versao",
            )
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()} v{self.versao})"


class DocumentoVeterinario(BaseModel):
    """Documento clínico gerado pelo sistema (PDF + metadados de integridade).

    O conteúdo é armazenado como snapshot textual no momento da emissão e o
    PDF é gravado em armazenamento privado. O identificador e o hash permitem
    conferir a autenticidade do documento sem expor o conteúdo clínico.

    Sobre assinatura: os campos ``assinatura_*`` apenas registram metadados de
    um processo externo. Uma imagem de assinatura NÃO é tratada como assinatura
    digital válida, e o sistema não declara validade jurídica.
    """

    tipo = models.CharField(
        max_length=40,
        choices=TipoDocumentoVeterinario.choices,
        verbose_name="tipo de documento",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="documentos_veterinarios",
        verbose_name="animal",
    )
    tutor = models.ForeignKey(
        "tutores.Tutor",
        on_delete=models.PROTECT,
        related_name="documentos_veterinarios",
        verbose_name="tutor",
    )
    prontuario = models.ForeignKey(
        "prontuario.Prontuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_veterinarios",
        verbose_name="prontuário",
    )
    atendimento = models.ForeignKey(
        "atendimentos.Atendimento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_veterinarios",
        verbose_name="atendimento",
    )
    veterinario = models.ForeignKey(
        "veterinarios.Veterinario",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="documentos_veterinarios",
        verbose_name="profissional responsável",
    )
    modelo = models.ForeignKey(
        ModeloDocumento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos",
        verbose_name="modelo utilizado",
    )

    titulo = models.CharField(max_length=200, verbose_name="título")
    conteudo = models.TextField(verbose_name="conteúdo")
    identificador = models.CharField(
        max_length=32,
        unique=True,
        default=gerar_identificador,
        editable=False,
        verbose_name="identificador de autenticidade",
    )
    hash_conteudo = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        verbose_name="hash SHA-256 do conteúdo",
    )
    situacao = models.CharField(
        max_length=20,
        choices=SituacaoDocumento.choices,
        default=SituacaoDocumento.RASCUNHO,
        verbose_name="situação",
    )
    data_emissao = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="data de emissão",
    )
    emitido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="documentos_emitidos",
        verbose_name="emitido por",
    )

    # Arquivo PDF privado (gerado na emissão).
    pdf_nome_interno = models.CharField(
        max_length=255,
        blank=True,
        editable=False,
        verbose_name="nome interno do PDF",
    )
    pdf_caminho = models.CharField(
        max_length=500,
        blank=True,
        editable=False,
        verbose_name="caminho do PDF",
    )
    pdf_tamanho = models.PositiveIntegerField(
        default=0,
        editable=False,
        verbose_name="tamanho do PDF (bytes)",
    )
    pdf_sha256 = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        verbose_name="hash SHA-256 do PDF",
    )

    # Histórico de versões.
    versao = models.PositiveIntegerField(default=1, verbose_name="versão")
    documento_anterior = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versoes_posteriores",
        verbose_name="documento anterior",
    )

    # Assinatura: apenas metadados de um processo externo. Não implica
    # validade jurídica nem assinatura digital qualificada.
    assinatura_status = models.CharField(
        max_length=20,
        choices=StatusAssinatura.choices,
        default=StatusAssinatura.NAO_ASSINADO,
        verbose_name="situação da assinatura",
    )
    assinatura_provedor = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="provedor de assinatura",
    )
    assinatura_referencia = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="referência externa da assinatura",
    )
    assinatura_hash = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="hash do artefato de assinatura",
    )
    assinado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="assinado em",
    )

    # Cancelamento (documento emitido não é apagado).
    cancelado_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="cancelado em",
    )
    motivo_cancelamento = models.TextField(
        blank=True,
        verbose_name="motivo do cancelamento",
    )

    # Liberação explícita para o portal do tutor (padrão: não expor).
    liberado_portal = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="liberado no portal do tutor",
    )
    liberado_portal_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="liberado no portal em",
    )
    liberado_portal_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="liberado no portal por",
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["-criado_em"]
        verbose_name = "documento veterinário"
        verbose_name_plural = "documentos veterinários"
        indexes = [
            models.Index(fields=["pet", "-criado_em"]),
            models.Index(fields=["tutor", "-criado_em"]),
            models.Index(fields=["prontuario"]),
            models.Index(fields=["atendimento"]),
            models.Index(fields=["tipo", "situacao"]),
            models.Index(fields=["identificador"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.identificador} — {self.pet.nome}"

    @staticmethod
    def calcular_hash(conteudo: str) -> str:
        return hashlib.sha256((conteudo or "").encode("utf-8")).hexdigest()

    def atualizar_hash(self):
        self.hash_conteudo = self.calcular_hash(self.conteudo)

    @property
    def editavel(self) -> bool:
        return self.situacao == SituacaoDocumento.RASCUNHO

    def salvar_pdf(self, conteudo_pdf: bytes):
        """Grava o PDF em armazenamento privado com nome aleatório."""
        self.pdf_nome_interno = f"{uuid.uuid4().hex}.pdf"
        self.pdf_caminho = f"documentos_veterinarios/{self.pdf_nome_interno}"
        self.pdf_tamanho = len(conteudo_pdf)
        self.pdf_sha256 = hashlib.sha256(conteudo_pdf).hexdigest()

        try:
            os.makedirs(
                os.path.dirname(default_storage.path(self.pdf_caminho)),
                exist_ok=True,
            )
        except Exception:
            # Storages remotos (ex.: S3) não implementam ``path``.
            pass

        self.pdf_caminho = default_storage.save(
            self.pdf_caminho,
            ContentFile(conteudo_pdf),
        )

    def excluir_pdf(self):
        if self.pdf_caminho:
            try:
                default_storage.delete(self.pdf_caminho)
            except Exception:
                pass

    def get_absolute_url(self):
        return f"/api/v1/documentos-veterinarios/{self.id}/download/"

    def hard_delete(self, using=None, keep_parents=False):
        self.excluir_pdf()
        return super().hard_delete(using=using, keep_parents=keep_parents)
