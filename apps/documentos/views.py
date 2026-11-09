"""Views de documentos clínicos."""

import os
from urllib.parse import quote

from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action

from apps.base.views import AuditModelViewSetMixin

from .models import DocumentoClinico
from .serializers import DocumentoClinicoSerializer, DocumentoClinicoCreateSerializer


class DocumentoClinicoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Gerenciamento de documentos clínicos (anexos de exames, laudos, etc.).

    O arquivo físico não é exposto diretamente. O download é feito por este
    ViewSet através do endpoint `download`, que valida autenticação e
    permissão antes de servir o conteúdo.
    """

    queryset = DocumentoClinico.objects.select_related(
        "pet", "pet__tutor", "prontuario", "atendimento", "usuario"
    ).all()
    serializer_class = DocumentoClinicoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["pet", "prontuario", "atendimento", "tipo"]
    search_fields = ["nome_original", "descricao", "pet__nome"]
    ordering_fields = ["criado_em", "data_exame", "nome_original"]
    ordering = ["-criado_em"]
    audit_entidade = "documento_clinico"
    role_policy = ("admin", "veterinario", "recepcao")

    def get_serializer_class(self):
        if self.action == "create":
            return DocumentoClinicoCreateSerializer
        return super().get_serializer_class()

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Faz download do arquivo do documento clínico.

        Exige autenticação. O arquivo é servido com cabeçalhos de segurança
        para evitar execução no navegador (XSS) e forçar download.
        """
        documento = self.get_object()

        if not default_storage.exists(documento.caminho_arquivo):
            raise Http404("Arquivo não encontrado no armazenamento.")

        with default_storage.open(documento.caminho_arquivo, "rb") as f:
            conteudo = f.read()

        response = HttpResponse(
            conteudo,
            content_type=documento.mime_type or "application/octet-stream",
        )
        # Sanitiza o nome para evitar injeção de cabeçalhos. Usa fallback ASCII
        # e o parâmetro RFC 5987 para nomes com acentos.
        nome_seguro = os.path.basename(documento.nome_original or "arquivo")
        nome_ascii = nome_seguro.encode("ascii", "ignore").decode() or "arquivo"
        nome_ascii = nome_ascii.replace('"', "").replace("\r", "").replace("\n", "")

        response["Content-Disposition"] = (
            f"attachment; filename=\"{nome_ascii}\"; "
            f"filename*=UTF-8''{quote(nome_seguro)}"
        )
        response["Content-Length"] = documento.tamanho or len(conteudo)
        # Headers de segurança para evitar execução no navegador
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Content-Security-Policy"] = "default-src 'none'"
        response["Cache-Control"] = "no-store"

        return response


# ---------------------------------------------------------------------------
# Documentos veterinários gerados
# ---------------------------------------------------------------------------

import hashlib
from datetime import datetime

from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.auditoria.models import AuditLog
from apps.auditoria.services import (
    registrar,
    snapshot,
    usuario_da_request,
)
from apps.base.views import AuditModelViewSetMixin, JustificativaObrigatoriaMixin

from .models import (
    DocumentoVeterinario,
    ModeloDocumento,
    SituacaoDocumento,
    StatusAssinatura,
)
from .serializers import (
    CancelarDocumentoSerializer,
    DocumentoVeterinarioSerializer,
    DocumentoVeterinarioWriteSerializer,
    ModeloDocumentoSerializer,
    RegistrarAssinaturaSerializer,
)
from .services import gerar_pdf_documento


class ModeloDocumentoViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    """Modelos (templates) de documentos veterinários."""

    queryset = ModeloDocumento.objects.all()
    serializer_class = ModeloDocumentoSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["tipo", "ativo"]
    search_fields = ["nome", "corpo"]
    ordering_fields = ["tipo", "nome", "versao", "criado_em"]
    ordering = ["tipo", "nome", "-versao"]
    role_policy = {
        "list": ("admin", "veterinario"),
        "retrieve": ("admin", "veterinario"),
        "*": ("admin",),
    }


class DocumentoVeterinarioViewSet(
    JustificativaObrigatoriaMixin,
    AuditModelViewSetMixin,
    viewsets.ModelViewSet,
):
    """Receituários, atestados, laudos e demais documentos veterinários.

    O conteúdo clínico não é exposto na verificação pública de autenticidade:
    o endpoint ``verificar`` devolve apenas metadados e hashes.
    """

    queryset = DocumentoVeterinario.objects.select_related(
        "pet",
        "pet__tutor",
        "pet__especie",
        "pet__raca",
        "tutor",
        "prontuario",
        "atendimento",
        "veterinario",
        "veterinario__profissional",
        "modelo",
        "emitido_por",
        "documento_anterior",
    ).all()
    serializer_class = DocumentoVeterinarioSerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "pet",
        "tutor",
        "prontuario",
        "atendimento",
        "veterinario",
        "tipo",
        "situacao",
        "assinatura_status",
    ]
    search_fields = [
        "titulo",
        "identificador",
        "pet__nome",
        "tutor__nome",
        "conteudo",
    ]
    ordering_fields = [
        "criado_em",
        "data_emissao",
        "tipo",
        "situacao",
        "versao",
    ]
    ordering = ["-criado_em"]
    audit_exclude = ("conteudo",)  # o hash registra a integridade sem expor o texto
    role_policy = {
        "list": ("admin", "veterinario", "recepcao"),
        "retrieve": ("admin", "veterinario", "recepcao"),
        "download": ("admin", "veterinario", "recepcao"),
        "create": ("admin", "veterinario"),
        "update": ("admin", "veterinario"),
        "partial_update": ("admin", "veterinario"),
        "emitir": ("admin", "veterinario"),
        "cancelar": ("admin", "veterinario"),
        "nova_versao": ("admin", "veterinario"),
        "preparar_assinatura": ("admin", "veterinario"),
        "registrar_assinatura": ("admin", "veterinario"),
        "*": ("admin",),
    }

    def get_permissions(self):
        # A verificação de autenticidade é pública por desenho: o tutor ou
        # qualquer terceiro pode conferir um código sem ver o conteúdo clínico.
        if self.action == "verificar":
            return [AllowAny()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return DocumentoVeterinarioWriteSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        resposta = super().create(request, *args, **kwargs)
        instance = DocumentoVeterinario.objects.get(pk=resposta.data["id"])
        return self._resposta(instance, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return self._resposta(self.get_object())

    def perform_destroy(self, instance):
        if instance.situacao != SituacaoDocumento.RASCUNHO:
            raise ValidationError(
                "Documentos emitidos não podem ser excluídos. Cancele o "
                "documento para preservar o histórico."
            )
        return super().perform_destroy(instance)

    def _resposta(self, instance, status_code=status.HTTP_200_OK):
        return Response(
            DocumentoVeterinarioSerializer(
                instance, context=self.get_serializer_context()
            ).data,
            status=status_code,
        )

    @action(detail=True, methods=["post"], url_path="emitir")
    def emitir(self, request, pk=None):
        """Gera o PDF e congela o conteúdo do documento."""
        documento = self.get_object()
        if documento.situacao != SituacaoDocumento.RASCUNHO:
            raise ValidationError("Apenas rascunhos podem ser emitidos.")
        if not documento.veterinario_id:
            raise ValidationError(
                {"veterinario": ["Informe o profissional responsável."]}
            )
        if not (documento.conteudo or "").strip():
            raise ValidationError({"conteudo": ["O documento está vazio."]})

        anteriores = snapshot(documento, exclude=self.audit_exclude)
        documento.situacao = SituacaoDocumento.EMITIDO
        documento.data_emissao = timezone.now()
        documento.emitido_por = request.user
        documento.atualizar_hash()

        pdf = gerar_pdf_documento(documento)
        documento.salvar_pdf(pdf)
        documento.save(user=request.user)

        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=documento,
            dados_anteriores=anteriores,
            justificativa="Emissão do documento veterinário",
            request=request,
        )
        return self._resposta(documento)

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        documento = self.get_object()
        if documento.situacao != SituacaoDocumento.EMITIDO:
            raise ValidationError(
                "Apenas documentos emitidos podem ser cancelados."
            )
        serializer = CancelarDocumentoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        justificativa = serializer.validated_data["justificativa"].strip()

        anteriores = snapshot(documento, exclude=self.audit_exclude)
        documento.situacao = SituacaoDocumento.CANCELADO
        documento.cancelado_em = timezone.now()
        documento.motivo_cancelamento = justificativa
        documento.save(user=request.user)

        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=documento,
            dados_anteriores=anteriores,
            justificativa=justificativa,
            request=request,
        )
        return self._resposta(documento)

    @action(detail=True, methods=["post"], url_path="nova-versao")
    def nova_versao(self, request, pk=None):
        """Cria um rascunho de nova versão, preservando o documento anterior."""
        anterior = self.get_object()
        if anterior.situacao == SituacaoDocumento.RASCUNHO:
            raise ValidationError(
                "Edite o rascunho atual em vez de criar uma nova versão."
            )

        nova = DocumentoVeterinario(
            tipo=anterior.tipo,
            pet=anterior.pet,
            tutor=anterior.tutor,
            prontuario=anterior.prontuario,
            atendimento=anterior.atendimento,
            veterinario=anterior.veterinario,
            modelo=anterior.modelo,
            titulo=anterior.titulo,
            conteudo=anterior.conteudo,
            situacao=SituacaoDocumento.RASCUNHO,
            versao=anterior.versao + 1,
            documento_anterior=anterior,
        )
        nova.atualizar_hash()
        nova.save(user=request.user)

        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.CRIACAO,
            instancia=nova,
            justificativa=f"Nova versão de {anterior.identificador}",
            request=request,
        )
        return self._resposta(nova, status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="preparar-assinatura")
    def preparar_assinatura(self, request, pk=None):
        documento = self.get_object()
        if documento.situacao != SituacaoDocumento.EMITIDO:
            raise ValidationError(
                "Emita o documento antes de prepará-lo para assinatura."
            )
        anteriores = snapshot(documento, exclude=self.audit_exclude)
        documento.assinatura_status = StatusAssinatura.PREPARADO
        documento.save(user=request.user)
        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=documento,
            dados_anteriores=anteriores,
            justificativa="Documento preparado para assinatura externa",
            request=request,
        )
        return self._resposta(documento)

    @action(detail=True, methods=["post"], url_path="registrar-assinatura")
    def registrar_assinatura(self, request, pk=None):
        """Registra metadados de assinatura externa (sem validade jurídica)."""
        documento = self.get_object()
        if documento.situacao != SituacaoDocumento.EMITIDO:
            raise ValidationError(
                "Emita o documento antes de registrar uma assinatura."
            )
        serializer = RegistrarAssinaturaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        anteriores = snapshot(documento, exclude=self.audit_exclude)
        documento.assinatura_status = StatusAssinatura.ASSINADO_EXTERNO
        documento.assinatura_provedor = dados["provedor"]
        documento.assinatura_referencia = dados["referencia"]
        documento.assinatura_hash = dados.get("hash_assinatura", "")
        documento.assinado_em = dados.get("assinado_em") or timezone.now()
        documento.save(user=request.user)

        registrar(
            usuario=usuario_da_request(request),
            acao=AuditLog.Acao.ATUALIZACAO,
            instancia=documento,
            dados_anteriores=anteriores,
            justificativa=(
                f"Metadados de assinatura externa registrados "
                f"({dados['provedor']}: {dados['referencia']})"
            ),
            request=request,
        )
        return self._resposta(documento)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Download autenticado do PDF do documento veterinário."""
        documento = self.get_object()
        if not documento.pdf_caminho or not default_storage.exists(
            documento.pdf_caminho
        ):
            raise NotFound("PDF ainda não foi gerado para este documento.")

        with default_storage.open(documento.pdf_caminho, "rb") as f:
            conteudo = f.read()

        nome = f"{documento.tipo}-{documento.identificador}.pdf"
        response = HttpResponse(conteudo, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{nome}"'
        response["Content-Length"] = len(conteudo)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Content-Security-Policy"] = "default-src 'none'"
        response["Cache-Control"] = "no-store"
        return response

    @action(detail=False, methods=["get"], url_path=r"verificar/(?P<identificador>[^/.]+)")
    def verificar(self, request, identificador=None):
        """Verificação pública de autenticidade (sem expor conteúdo clínico)."""
        documento = (
            DocumentoVeterinario.objects.select_related(
                "pet", "tutor", "veterinario__profissional"
            )
            .filter(identificador__iexact=identificador)
            .first()
        )
        if documento is None:
            raise NotFound("Documento não encontrado.")

        hash_confere = documento.calcular_hash(documento.conteudo) == (
            documento.hash_conteudo
        )
        pdf_disponivel = bool(
            documento.pdf_caminho
            and default_storage.exists(documento.pdf_caminho)
        )
        pdf_hash_confere = None
        if pdf_disponivel and documento.pdf_sha256:
            try:
                with default_storage.open(documento.pdf_caminho, "rb") as f:
                    pdf_hash_confere = (
                        hashlib.sha256(f.read()).hexdigest()
                        == documento.pdf_sha256
                    )
            except Exception:
                pdf_hash_confere = False

        return Response(
            {
                "identificador": documento.identificador,
                "tipo": documento.tipo,
                "tipo_display": documento.get_tipo_display(),
                "situacao": documento.situacao,
                "situacao_display": documento.get_situacao_display(),
                "data_emissao": documento.data_emissao,
                "pet_nome": documento.pet.nome,
                "tutor_nome": documento.tutor.nome,
                "veterinario_nome": (
                    documento.veterinario.profissional.nome
                    if documento.veterinario
                    else None
                ),
                "veterinario_crmv": (
                    documento.veterinario.crmv
                    if documento.veterinario
                    else None
                ),
                "hash_conteudo": documento.hash_conteudo,
                "hash_confere": hash_confere,
                "pdf_disponivel": pdf_disponivel,
                "pdf_hash_confere": pdf_hash_confere,
                "aviso": (
                    "Verificação de autenticidade baseada no identificador e "
                    "nos hashes armazenados. O conteúdo clínico não é exposto."
                ),
            }
        )
