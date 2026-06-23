from rest_framework import serializers
from .models import Profissional, Veterinario


class VeterinarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Veterinario
        fields = ["crmv", "especialidade"]
        

class ProfissionalSerializer(serializers.ModelSerializer):
    veterinario = VeterinarioSerializer(read_only=True)
    
    class Meta:
        model = Profissional
        fields = [
            "id",
            "nome",
            "cargo",
            "telefone",
            "ativo",
            "veterinario",
            "criado_em",
            "atualizado_em",
        ]
        
        read_only_fields = ["id", "criado_em", "atualizado_em"]