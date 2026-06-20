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
            "peso",
            "data_nascimento",
            "cor",
            "observacoes",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]
 