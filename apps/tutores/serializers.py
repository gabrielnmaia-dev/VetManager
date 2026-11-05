from rest_framework import serializers

from apps.pets.serializers import PetCreateSerializer, PetResumoSerializer

from .models import Tutor
from .services import criar_tutor_com_pets


class TutorSerializer(serializers.ModelSerializer):
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


class TutorComPetsSerializer(serializers.ModelSerializer):
    """Tutor com os pets aninhados (busca rápida da recepção)."""

    pets = PetResumoSerializer(many=True, read_only=True)

    class Meta:
        model = Tutor
        fields = ["id", "nome", "telefone", "cpf", "pets"]


class TutorCreateSerializer(serializers.ModelSerializer):
    """POST /api/v1/tutores/: aceita o payload legado (sem pets) e o novo
    com "pets" aninhado (lista opcional). A criação em cascata acontece no
    service, dentro de transaction.atomic."""

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

    def create(self, validated_data):
        pets_data = validated_data.pop("pets", [])
        return criar_tutor_com_pets(validated_data, pets_data)


class TutorResumoSerializer(serializers.ModelSerializer):
    """Resumo do tutor para respostas de atendimento (fluxo rápido)."""

    class Meta:
        model = Tutor
        fields = ["id", "nome", "telefone", "cpf"]
