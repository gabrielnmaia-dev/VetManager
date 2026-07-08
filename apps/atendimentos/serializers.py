from rest_framework import serializers
from .models import Atendimento


class AtendimentoSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor = serializers.PrimaryKeyRelatedField(source="pet.tutor", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    tipo_servico_display = serializers.CharField(
        source="get_tipo_servico_display",
        read_only=True,
    )

    class Meta:
        model = Atendimento
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "nome_profissional",
            "tipo_servico",
            "tipo_servico_display",  # ← adicionar aqui
            "queixa",
            "data_hora_inicio",
            "duracao_minutos",
            "status",
            "observacoes",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "tipo_servico_display",
            "criado_em",
            "atualizado_em",
        ]