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
