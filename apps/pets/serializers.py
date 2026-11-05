from rest_framework import serializers
from .models import Pet


class PetSerializer(serializers.ModelSerializer):
    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)

    class Meta:
        model = Pet
        fields = [
            "id",
            "tutor",
            "tutor_nome",
            "nome",
            "especie",
            "raca",
            "sexo",
            "cor",
            "vermifugado",
            "castrado",
            "data_nascimento",
            "observacoes",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]


class PetResumoSerializer(serializers.ModelSerializer):
    """Resumo usado para aninhar pets no tutor (busca rápida)."""

    class Meta:
        model = Pet
        fields = ["id", "nome", "especie", "raca"]


class PetCreateSerializer(serializers.ModelSerializer):
    """Pet sem tutor no payload: a FK é preenchida pelo service na cascata
    (tutor+pet num POST) e no atendimento rápido."""

    nome = serializers.CharField(
        max_length=100,
        error_messages={
            "required": "Informe o nome do pet.",
            "blank": "Informe o nome do pet.",
        },
    )
    especie = serializers.CharField(
        max_length=50,
        error_messages={
            "required": "Informe a espécie do pet.",
            "blank": "Informe a espécie do pet.",
        },
    )

    class Meta:
        model = Pet
        fields = [
            "id",
            "nome",
            "especie",
            "raca",
            "sexo",
            "cor",
            "vermifugado",
            "castrado",
            "data_nascimento",
            "observacoes",
        ]
        read_only_fields = ["id"]
