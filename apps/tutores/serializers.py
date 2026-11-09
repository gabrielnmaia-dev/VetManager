"""Serializers do app tutores com validação de CPF, telefone e normalização."""

import re

from rest_framework import serializers

from django.core.validators import RegexValidator

from apps.pets.serializers import PetCreateSerializer, PetResumoSerializer

from .models import Tutor
from .services import criar_tutor_com_pets
from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado


def validar_cpf(value):
    """Valida CPF brasileiro: formato, dígitos verificadores e não permite
    sequências com todos os dígitos iguais.

    Aceita CPF com ou máscara (ex.: "123.456.789-00" ou "12345678900").
    """
    if not value:
        return value
    cpf = re.sub(r"\D", "", value)
    if len(cpf) != 11:
        raise serializers.ValidationError("CPF deve conter 11 dígitos numéricos.")
    if cpf == cpf[0] * 11:
        raise serializers.ValidationError("CPF inválido: dígitos repetidos.")
    # Primeiro dígito verificador.
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    digito1 = (soma * 10 % 11) % 10
    if int(cpf[9]) != digito1:
        raise serializers.ValidationError("CPF inválido: primeiro dígito verificador.")
    # Segundo dígito verificador.
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    digito2 = (soma * 10 % 11) % 10
    if int(cpf[10]) != digito2:
        raise serializers.ValidationError("CPF inválido: segundo dígito verificador.")
    return value


def normalizar_telefone(value):
    """Remove máscara e valida que o telefone tem 10 ou 11 dígitos."""
    if not value:
        return value
    digitos = re.sub(r"\D", "", value)
    if len(digitos) < 10 or len(digitos) > 11:
        raise serializers.ValidationError(
            "Telefone deve conter 10 ou 11 dígitos (DDD + número)."
        )
    return value


class TutorSerializer(AuthoredModelSerializer):
    """Serializer de leitura/atualização do tutor."""

    cpf = serializers.CharField(
        required=False,
        allow_blank=True,
        validators=[validar_cpf],
    )
    telefone = serializers.CharField(
        required=False,
        allow_blank=True,
        validators=[RegexValidator(
            regex=r"^\+?[\d\s\-\(\)\.]+$",
            message="Telefone contém caracteres inválidos.",
        )],
    )

    class Meta:
        model = Tutor
        fields = [
            "id",
            "nome",
            "telefone",
            "email",
            "cpf",
            "endereco",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate_telefone(self, value):
        return normalizar_telefone(value)

    def validate_cpf(self, value):
        if value:
            value = validar_cpf(value)
            # Normaliza CPF para o formato com máscara.
            cpf = re.sub(r"\D", "", value)
            if len(cpf) == 11:
                value = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"
        return value

    def validate_email(self, value):
        if value:
            value = value.strip().lower()
        return value

    def validate_nome(self, value):
        if value:
            value = " ".join(value.split())  # colapsa espaços múltiplos
            value = value.title()  # cada palavra com inicial maiúscula
        return value

    def validate_endereco(self, value):
        if value:
            value = " ".join(value.split())
        return value


class TutorComPetsSerializer(serializers.ModelSerializer):
    """Tutor com os pets aninhados (busca rápida da recepção)."""

    pets = PetResumoSerializer(many=True, read_only=True)

    class Meta:
        model = Tutor
        fields = [
            "id",
            "nome",
            "telefone",
            "email",
            "cpf",
            "endereco",
            "pets",
            "criado_em",
            "atualizado_em",
        ]


class TutorCreateSerializer(AuthoredModelSerializer):
    """POST /api/v1/tutores/: aceita o payload legado e o novo
    com "pets" aninhado (lista opcional). A criação em cascata acontece no
    service, dentro de transaction.atomic.

    A autoria (created_by/updated_by) é injetada pelo backend a partir de
    request.user — o cliente nunca pode definir quem criou o registro.
    """

    nome = serializers.CharField(
        max_length=150,
        error_messages={
            "required": "Informe o nome do tutor.",
            "blank": "Informe o nome do tutor.",
        },
    )
    telefone = serializers.CharField(
        max_length=20,
        error_messages={
            "required": "Informe o telefone do tutor.",
            "blank": "Informe o telefone do tutor.",
        },
    )
    cpf = serializers.CharField(
        max_length=14,
        required=False,
        allow_blank=True,
        validators=[validar_cpf],
    )
    email = serializers.EmailField(required=False, allow_blank=True)
    endereco = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    pets = PetCreateSerializer(many=True, required=False)

    class Meta:
        model = Tutor
        fields = [
            "id",
            "nome",
            "telefone",
            "email",
            "cpf",
            "endereco",
            "criado_em",
            "atualizado_em",
            "pets",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate_telefone(self, value):
        return normalizar_telefone(value)

    def validate_cpf(self, value):
        if value:
            return validar_cpf(value)
        return value

    def validate_email(self, value):
        if value:
            value = value.strip().lower()
        return value

    def validate_nome(self, value):
        if value:
            value = " ".join(value.split())
            value = value.title()
        return value

    def validate_endereco(self, value):
        if value:
            value = " ".join(value.split())
        return value

    def create(self, validated_data):
        pets_data = validated_data.pop("pets", [])
        user = usuario_autenticado(self.context)
        if user is not None:
            validated_data["created_by"] = user
            validated_data["updated_by"] = user
        return criar_tutor_com_pets(validated_data, pets_data, user=user)


class TutorResumoSerializer(serializers.ModelSerializer):
    """Resumo do tutor para respostas de atendimento (fluxo rápido)."""

    class Meta:
        model = Tutor
        fields = ["id", "nome", "telefone", "cpf"]
