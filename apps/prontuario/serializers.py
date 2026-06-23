from rest_framework import serializers
from .models import Prontuario, Vacina


class VacinaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vacina
        fields = [
            "id",
            "pet",
            "prontuario",
            "nome_vacina",
            "data_aplicacao",
            "data_retorno",
            "observacoes",
            "criado_em",
        ]
        read_only_fields = ["id", "criado_em"]


class ProntuarioSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    veterinario_nome = serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    vacinas = VacinaSerializer(many=True, read_only=True)

    class Meta:
        model = Prontuario
        fields = [
            "id",
            "atendimento",
            "pet",
            "pet_nome",
            "veterinario",
            "veterinario_nome",
            "data_consulta",
            "peso",
            "temperatura",
            "diagnostico",
            "observacoes",
            "prescricao",
            "retorno_recomendado",
            "vacinas",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]