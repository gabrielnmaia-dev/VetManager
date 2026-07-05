from rest_framework import serializers
from .models import Atendimento
 
 
class AtendimentoSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
 
    class Meta:
        model = Atendimento
        fields = [
            "id",
            "tutor",
            "tutor_nome",
            "nome",
            "especie",
            "raca",
            "sexo",
            "castrado",
            "vermifugado",
            "peso",
            "data_nascimento",
            "cor",
            "observacoes",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]
 