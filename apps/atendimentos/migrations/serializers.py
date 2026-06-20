from rest_framework import serializers
from .models import Atendimento
 
 
class AtendimentoSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
 
    class Meta:
        model = Atendimento
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor_nome",
            "nome_profissional",
            "tipo_servico",
            "queixa",
            "data_hora_inicio",
            "duracao_minutos",
            "status",
            "observacoes",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]
 