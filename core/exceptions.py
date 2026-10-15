import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("django.request")


def custom_exception_handler(exc, context):
    """
    Usa o handler padrão do DRF e, para erros não tratados, devolve um JSON
    genérico (sem stack trace) em produção. Em DEBUG deixa o Django exibir
    a página de erro normalmente.
    """
    response = exception_handler(exc, context)
    if response is not None:
        return response

    if settings.DEBUG:
        return None

    view = context.get("view")
    logger.exception(
        "Erro não tratado em %s", view.__class__.__name__ if view else "?", exc_info=exc
    )
    return Response(
        {"detail": "Erro interno do servidor."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
