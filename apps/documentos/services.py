"""Serviços de documentos clínicos.

Validação de upload (extensão, tamanho e tipo real por assinatura de bytes)
e exclusão segura de arquivos do armazenamento privado.
"""

import os

from django.conf import settings
from django.core.files.storage import default_storage

# Extensões aceitas para anexos clínicos.
EXTENSOES_PERMITIDAS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".dcm",  # DICOM
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".zip",
}

# MIME types considerados seguros para armazenamento/serviço.
MIMES_PERMITIDOS = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/webp",
    "application/dicom",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "application/zip",
}

# MIME types que jamais podem ser aceitos.
MIMES_PROIBIDOS = {
    "application/x-executable",
    "application/x-msdownload",
    "application/x-sh",
    "application/x-shellscript",
    "text/x-shellscript",
    "application/x-python",
    "application/x-java",
    "application/x-applet",
    "application/x-dosexec",
    "application/octet-stream",
}

# Mapeia a assinatura detectada para um MIME type canônico.
_ASSINATURAS = [
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"PK\x03\x04", "application/zip"),
    (b"DICM", "application/dicom"),
    # Assinaturas de executáveis/scripts — sempre bloqueadas.
    (b"MZ", "application/x-msdownload"),
    (b"\x7fELF", "application/x-executable"),
    (b"#!", "text/x-shellscript"),
]


def _detectar_por_assinatura(cabecalho):
    """Detecta o MIME type a partir dos primeiros bytes (magic bytes).

    Implementação em Python puro para não depender de ``libmagic`` no
    ambiente. Retorna ``None`` quando a assinatura não é reconhecida.
    """
    if not cabecalho:
        return None

    for assinatura, mime in _ASSINATURAS:
        if cabecalho.startswith(assinatura):
            # RIFF container: WEBP
            if assinatura == b"RIFF":
                return mime
            return mime

    # WEBP: "RIFF" + 4 bytes tamanho + "WEBP"
    if cabecalho[:4] == b"RIFF" and cabecalho[8:12] == b"WEBP":
        return "image/webp"

    return None


def detectar_mime_type(arquivo_upload):
    """Detecta o MIME type real do arquivo.

    Prioriza ``python-magic`` (se disponível) e cai para a detecção por
    assinatura de bytes. Por último, usa o ``content_type`` informado.
    """
    arquivo_upload.seek(0)
    cabecalho = arquivo_upload.read(2048)
    arquivo_upload.seek(0)

    try:
        import magic

        mime = magic.from_buffer(cabecalho, mime=True)
        if mime:
            return mime
    except Exception:
        pass

    mime = _detectar_por_assinatura(cabecalho)
    if mime:
        return mime

    return getattr(arquivo_upload, "content_type", None) or "application/octet-stream"


def validar_arquivo(arquivo_upload):
    """Valida um arquivo enviado.

    Verifica extensão, tamanho e tipo real (assinatura de bytes).
    Retorna ``(valido, mensagem_erro)``.
    """
    tamanho_maximo = getattr(
        settings, "DOCUMENTO_TAMANHO_MAXIMO", 10 * 1024 * 1024
    )

    # Extensão
    ext = os.path.splitext(arquivo_upload.name or "")[1].lower()
    if ext not in EXTENSOES_PERMITIDAS:
        return False, f"Extensão '{ext or '(sem extensão)'}' não permitida."

    # Tamanho
    if arquivo_upload.size > tamanho_maximo:
        tamanho_mb = tamanho_maximo / (1024 * 1024)
        return False, f"Arquivo excede o limite de {tamanho_mb:.0f} MB."

    # Tipo real
    mime_real = detectar_mime_type(arquivo_upload)

    if mime_real in MIMES_PROIBIDOS:
        return False, "Tipo de arquivo não permitido."

    if mime_real not in MIMES_PERMITIDOS:
        return False, f"Tipo de arquivo '{mime_real}' não permitido."

    return True, ""


def excluir_arquivo_seguro(caminho_arquivo):
    """Exclui um arquivo do armazenamento de forma segura (silenciosa)."""
    if caminho_arquivo:
        try:
            default_storage.delete(caminho_arquivo)
        except Exception:
            pass
