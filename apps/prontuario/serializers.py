from rest_framework import serializers

from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from .models import Prontuario, Vacina


class VacinaSerializer(AuthoredModelSerializer):
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


class ProntuarioSerializer(AuthoredModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    veterinario_nome = serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    vacinas = VacinaSerializer(many=True, read_only=True)

    def validate_veterinario(self, valor):
        """O veterinário do prontuário deve ser um Profissional com cargo
        'Veterinário', não qualquer profissional (tosador, banhista, etc.)."""
        if valor is not None and valor.profissional.cargo != "Veterinário":
            raise serializers.ValidationError(
                "Somente profissionais com cargo 'Veterinário' podem assinar prontuários."
            )
        return valor

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
            "data_nascimento",
            "idade",
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