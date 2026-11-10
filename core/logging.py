"""Logs estruturados do VetManager.

O objetivo é produzir uma linha JSON por evento, com os campos pedidos pela
operação (data/hora, nível, serviço, usuário, request id, operação e erro)
sem despejar payloads, cabeçalhos ou dados clínicos.

Regras de segurança aplicadas aqui:

* Apenas um conjunto **fechado** de campos ``extra`` é serializado. Qualquer
  outro campo é descartado — inclusive se alguém passar dados de prontuário.
* Textos conhecidos por carregar segredos (``Bearer ...``, ``password=...``,
  cookies de access/refresh) são redigidos.
* O stack trace só é incluído quando ``LOG_INCLUDE_TRACEBACK=1``.

Nunca registre ``request.body``, ``request.headers`` inteiros, senhas ou
tokens. Use ``extra={"operacao": ..., "status_code": ...}`` para enriquecer.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

from core.logging_context import obter_request_id, obter_usuario_id

SERVICE_NAME = os.environ.get("SERVICE_NAME", "vetmanager-api")

# Campos extras permitidos no JSON. Mantenha esta lista pequena: é a barreira
# contra vazamento acidental de dados clínicos para o agregador de logs.
CAMPOS_EXTRAS_PERMITIDOS = (
    "operacao",
    "metodo",
    "rota",
    "status_code",
    "duracao_ms",
    "lentidao",
    "erro_tipo",
    "erro_mensagem",
    "servico_externo",
    "tarefa",
    "resultado",
    "tentativa",
)

# Padrões de segredo que podem aparecer em mensagens de terceiros.
_PADROES_SEGREDO = (
    re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:password|senha|token|secret|api[_-]?key)\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)((?:access|refresh|portal_access|portal_refresh)=)[^;\s]+"),
)


def _redigir(texto: str) -> str:
    for padrao in _PADROES_SEGREDO:
        texto = padrao.sub(r"\1 [REDACTED]", texto)
    return texto


def _serializavel(valor):
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return str(valor)


class JsonFormatter(logging.Formatter):
    """Formatter que devolve uma linha JSON por evento de log."""

    def format(self, record: logging.LogRecord) -> str:
        dados: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nivel": record.levelname,
            "servico": SERVICE_NAME,
            "logger": record.name,
            "mensagem": _redigir(record.getMessage()),
        }

        request_id = obter_request_id()
        if request_id:
            dados["request_id"] = request_id

        usuario_id = obter_usuario_id()
        if usuario_id:
            dados["usuario_id"] = usuario_id

        for campo in CAMPOS_EXTRAS_PERMITIDOS:
            valor = getattr(record, campo, None)
            if valor is not None:
                dados[campo] = _serializavel(valor)

        if record.exc_info and record.exc_info[0] is not None:
            exc_tipo, exc_valor = record.exc_info[0], record.exc_info[1]
            dados["erro"] = {
                "tipo": exc_tipo.__name__,
                "mensagem": _redigir(str(exc_valor)) if exc_valor else None,
            }
            if os.environ.get("LOG_INCLUDE_TRACEBACK", "0").strip() == "1":
                dados["traceback"] = self.formatException(record.exc_info)
        elif record.levelno >= logging.ERROR:
            # Erros registrados sem exc_info ainda precisam do campo "erro".
            dados.setdefault(
                "erro",
                {
                    "tipo": getattr(record, "erro_tipo", None),
                    "mensagem": getattr(record, "erro_mensagem", None),
                },
            )

        return json.dumps(dados, ensure_ascii=False, default=str)
