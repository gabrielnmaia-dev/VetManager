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


# ---------------------------------------------------------------------------
# Geração de documentos veterinários
# ---------------------------------------------------------------------------

import re
from datetime import date, datetime
from decimal import Decimal

_MARCADOR = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def _formatar_valor(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        from django.utils import timezone

        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, Decimal):
        return str(valor).replace(".", ",")
    return str(valor)


def contexto_documento(documento) -> dict:
    """Monta o contexto de marcadores a partir do documento e seus vínculos."""
    from django.conf import settings

    pet = documento.pet
    tutor = documento.tutor
    veterinario = documento.veterinario
    prontuario = documento.prontuario
    atendimento = documento.atendimento

    especie = getattr(pet, "especie", None)
    raca = getattr(pet, "raca", None)

    contexto = {
        "clinica_nome": getattr(settings, "CLINICA_NOME", "VetManager"),
        "clinica_cnpj": getattr(settings, "CLINICA_CNPJ", ""),
        "clinica_endereco": getattr(settings, "CLINICA_ENDERECO", ""),
        "clinica_telefone": getattr(settings, "CLINICA_TELEFONE", ""),
        "clinica_email": getattr(settings, "CLINICA_EMAIL", ""),
        "clinica_cidade": getattr(settings, "CLINICA_CIDADE", ""),
        "documento_tipo": documento.get_tipo_display(),
        "documento_titulo": documento.titulo,
        "identificador": documento.identificador,
        "data_emissao": _formatar_valor(documento.data_emissao),
        "pet_nome": pet.nome,
        "pet_especie": getattr(especie, "nome", "") or "",
        "pet_raca": getattr(raca, "nome", "") or "",
        "pet_sexo": pet.get_sexo_display() if pet.sexo else "",
        "pet_cor": pet.cor or "",
        "pet_idade": _formatar_valor(pet.idade_calculada),
        "pet_microchip": pet.microchip or "",
        "tutor_nome": tutor.nome,
        "tutor_cpf": tutor.cpf or "",
        "tutor_telefone": tutor.telefone or "",
        "tutor_email": tutor.email or "",
        "tutor_endereco": tutor.endereco or "",
        "veterinario_nome": (
            veterinario.profissional.nome if veterinario else ""
        ),
        "veterinario_crmv": veterinario.crmv if veterinario else "",
        "veterinario_especialidade": (
            veterinario.especialidade if veterinario else ""
        ),
        "prontuario_data": (
            _formatar_valor(prontuario.data_consulta) if prontuario else ""
        ),
        "prontuario_diagnostico": prontuario.diagnostico if prontuario else "",
        "prontuario_prescricao": prontuario.prescricao if prontuario else "",
        "prontuario_observacoes": prontuario.observacoes if prontuario else "",
        "atendimento_data": (
            _formatar_valor(atendimento.data_hora_inicio) if atendimento else ""
        ),
        "atendimento_tipo": (
            atendimento.get_tipo_servico_display() if atendimento else ""
        ),
        "atendimento_queixa": atendimento.queixa if atendimento else "",
    }
    return contexto


def renderizar_template(corpo: str, contexto: dict) -> str:
    """Substitui marcadores ``{{campo}}`` pelos valores do contexto.

    Marcadores desconhecidos são removidos para não vazar placeholders no
    documento final. A substituição é textual e não executa código.
    """

    def _substituir(match):
        return _formatar_valor(contexto.get(match.group(1), ""))

    return _MARCADOR.sub(_substituir, corpo or "")


def _escapar(texto: str) -> str:
    from xml.sax.saxutils import escape

    return escape(texto or "")


def _paragrafo(texto: str, estilo):
    """Converte texto puro (com quebras) em parágrafo do ReportLab."""
    from reportlab.platypus import Paragraph

    linhas = _escapar(texto or "").splitlines() or [""]
    return Paragraph("<br/>".join(linhas), estilo)


def gerar_pdf_documento(documento) -> bytes:
    """Gera o PDF do documento veterinário.

    Usa ReportLab. O layout é pensado para impressão em A4 e inclui cabeçalho
    da clínica, identificação do tutor/animal/profissional, conteúdo, bloco de
    assinatura e identificação de autenticidade.

    Importante: o PDF não afirma validade jurídica de assinatura. Os campos de
    assinatura são apenas metadados de um processo externo.
    """
    import io

    from django.conf import settings
    from django.utils import timezone
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=f"{documento.get_tipo_display()} {documento.identificador}",
        author=getattr(settings, "CLINICA_NOME", "VetManager"),
        subject=documento.titulo,
    )

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle(
        "TituloDocumento",
        parent=estilos["Title"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    subtitulo = ParagraphStyle(
        "SubtituloDocumento",
        parent=estilos["Normal"],
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
    )
    corpo = ParagraphStyle(
        "CorpoDocumento",
        parent=estilos["Normal"],
        fontSize=10.5,
        leading=15,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    )
    rotulo = ParagraphStyle(
        "RotuloDocumento",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#333333"),
    )
    valor = ParagraphStyle(
        "ValorDocumento",
        parent=estilos["Normal"],
        fontSize=9,
        leading=12,
    )
    pequeno = ParagraphStyle(
        "PequenoDocumento",
        parent=estilos["Normal"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#666666"),
    )

    historia = []

    # Cabeçalho da clínica
    clinica_nome = getattr(settings, "CLINICA_NOME", "VetManager")
    clinica_linhas = [
        getattr(settings, "CLINICA_ENDERECO", ""),
        " • ".join(
            v
            for v in [
                getattr(settings, "CLINICA_TELEFONE", ""),
                getattr(settings, "CLINICA_EMAIL", ""),
            ]
            if v
        ),
        (
            f"CNPJ: {getattr(settings, 'CLINICA_CNPJ', '')}"
            if getattr(settings, "CLINICA_CNPJ", "")
            else ""
        ),
    ]
    historia.append(
        Paragraph(
            _escapar(clinica_nome),
            ParagraphStyle(
                "Clinica",
                parent=estilos["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=13,
                leading=16,
                alignment=TA_CENTER,
                spaceAfter=1,
            ),
        )
    )
    for linha in clinica_linhas:
        if linha:
            historia.append(Paragraph(_escapar(linha), subtitulo))
    historia.append(Spacer(1, 6))
    historia.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#2E8E96")))
    historia.append(Spacer(1, 10))

    historia.append(Paragraph(_escapar(documento.get_tipo_display()), titulo))
    historia.append(
        Paragraph(
            f"Documento nº {_escapar(documento.identificador)}",
            subtitulo,
        )
    )
    historia.append(Spacer(1, 10))

    # Identificação
    pet = documento.pet
    tutor = documento.tutor
    veterinario = documento.veterinario
    especie = getattr(getattr(pet, "especie", None), "nome", "") or ""
    raca = getattr(getattr(pet, "raca", None), "nome", "") or ""
    idade = _formatar_valor(pet.idade_calculada)

    def _linha(rotulo_texto, valor_texto):
        return [
            Paragraph(_escapar(rotulo_texto), rotulo),
            Paragraph(_escapar(valor_texto or "—"), valor),
        ]

    dados = [
        _linha("Tutor", tutor.nome),
        _linha("CPF", tutor.cpf),
        _linha("Telefone", tutor.telefone),
        _linha("Animal", pet.nome),
        _linha("Espécie / Raça", f"{especie} / {raca}" if raca else especie),
        _linha("Sexo / Idade", f"{pet.get_sexo_display() if pet.sexo else '—'} / {idade or '—'}"),
        _linha("Microchip", pet.microchip),
    ]
    if documento.prontuario_id:
        dados.append(
            _linha(
                "Prontuário",
                _formatar_valor(documento.prontuario.data_consulta),
            )
        )
    if documento.atendimento_id:
        dados.append(
            _linha(
                "Atendimento",
                f"{documento.atendimento.get_tipo_servico_display()} — "
                f"{_formatar_valor(documento.atendimento.data_hora_inicio)}",
            )
        )
    if veterinario:
        dados.append(
            _linha(
                "Profissional",
                f"{veterinario.profissional.nome} — CRMV {veterinario.crmv}",
            )
        )

    tabela = Table(dados, colWidths=[32 * mm, 138 * mm])
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ]
        )
    )
    historia.append(tabela)
    historia.append(Spacer(1, 14))

    # Corpo
    historia.append(_paragrafo(documento.conteudo, corpo))

    # Assinatura / data
    historia.append(Spacer(1, 26))
    cidade = getattr(settings, "CLINICA_CIDADE", "")
    data_txt = _formatar_valor(documento.data_emissao or timezone.now())
    local_data = f"{cidade}, {data_txt}" if cidade else data_txt
    historia.append(Paragraph(_escapar(local_data), corpo))
    historia.append(Spacer(1, 24))

    if veterinario:
        historia.append(
            Paragraph("_" * 60, ParagraphStyle("Linha", parent=valor, alignment=TA_CENTER))
        )
        historia.append(
            Paragraph(
                _escapar(veterinario.profissional.nome),
                ParagraphStyle("AssNome", parent=valor, alignment=TA_CENTER, fontName="Helvetica-Bold"),
            )
        )
        historia.append(
            Paragraph(
                _escapar(
                    f"Médico(a) Veterinário(a) — CRMV {veterinario.crmv}"
                ),
                ParagraphStyle("AssCrmv", parent=pequeno, alignment=TA_CENTER),
            )
        )

    # Situação da assinatura (metadados, sem alegação de validade jurídica)
    historia.append(Spacer(1, 12))
    if documento.assinatura_status == "assinado_externo":
        texto_assinatura = (
            f"Assinatura eletrônica registrada externamente via "
            f"{documento.assinatura_provedor or 'provedor não informado'}"
            f"{(' em ' + _formatar_valor(documento.assinado_em)) if documento.assinado_em else ''}. "
            f"Referência: {documento.assinatura_referencia or '—'}."
        )
    elif documento.assinatura_status == "preparado":
        texto_assinatura = (
            "Documento preparado para assinatura eletrônica externa. "
            "Nenhuma assinatura foi aplicada até o momento."
        )
    else:
        texto_assinatura = "Documento sem assinatura eletrônica registrada."
    historia.append(Paragraph(_escapar(texto_assinatura), pequeno))
    historia.append(
        Paragraph(
            _escapar(
                "A autenticidade deste documento pode ser conferida pelo "
                "identificador informado. A conferência não substitui a "
                "assinatura digital qualificada quando exigida por lei."
            ),
            pequeno,
        )
    )

    historia.append(Spacer(1, 6))
    historia.append(
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC"))
    )
    historia.append(Spacer(1, 4))
    verificacao = getattr(settings, "DOCUMENTO_VERIFICACAO_URL", "")
    if not verificacao:
        frontend = getattr(settings, "FRONTEND_URL", "") or ""
        verificacao = (
            f"{frontend.rstrip('/')}/validar" if frontend else "sistema VetManager"
        )
    historia.append(
        Paragraph(
            _escapar(
                f"Autenticidade: {documento.identificador}  •  "
                f"SHA-256 do conteúdo: {documento.hash_conteudo[:32]}…  •  "
                f"Verifique em {verificacao}"
            ),
            pequeno,
        )
    )

    def _rodape(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(
            20 * mm,
            10 * mm,
            f"{clinica_nome} — documento gerado eletronicamente",
        )
        canvas.drawRightString(
            A4[0] - 20 * mm,
            10 * mm,
            f"Página {doc_obj.page}",
        )
        canvas.restoreState()

    doc.build(historia, onFirstPage=_rodape, onLaterPages=_rodape)
    return buffer.getvalue()
