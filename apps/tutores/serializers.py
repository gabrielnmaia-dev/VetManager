from rest_framework import serializers
from .models import Tutor
 
 
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
 
 