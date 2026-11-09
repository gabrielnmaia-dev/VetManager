"""Serializers e utilitários compartilhados.

``AuthoredModelSerializer`` elimina a possibilidade de o cliente informar
autoria: os campos são somente leitura e preenchidos aqui a partir de
``request.user``.
"""

from rest_framework import serializers


def usuario_autenticado(context) -> object | None:
    """Extrai o usuário autenticado do contexto do serializer."""
    request = (context or {}).get("request")
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


class AuthoredModelSerializer(serializers.ModelSerializer):
    """ModelSerializer que injeta ``created_by``/``updated_by`` no backend."""

    def create(self, validated_data):
        user = usuario_autenticado(self.context)
        if user is not None:
            validated_data["created_by"] = user
            validated_data["updated_by"] = user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        user = usuario_autenticado(self.context)
        if user is not None:
            validated_data["updated_by"] = user
        return super().update(instance, validated_data)


class JustificativaField(serializers.CharField):
    """Campo write-only usado em operações clínicas sensíveis."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("write_only", True)
        kwargs.setdefault(
            "help_text",
            "Justificativa da alteração/exclusão. Obrigatória em mudanças "
            "clínicas e exclusões de prontuário.",
        )
        super().__init__(**kwargs)
