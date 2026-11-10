"""Serializers do app pets com catálogos controlados e validações."""

from rest_framework import serializers

from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from .models import Especie, Raca, Pet, HistoricoResponsabilidadePet, MedicaoVital


class EspecieSerializer(AuthoredModelSerializer):
    """Catálogo de espécies (somente leitura para clientes)."""

    class Meta:
        model = Especie
        fields = ["id", "nome", "ativo", "criado_em", "atualizado_em"]
        read_only_fields = ["id", "criado_em", "atualizado_em"]


class RacaSerializer(AuthoredModelSerializer):
    """Catálogo de raças vinculado a uma espécie."""

    especie_nome = serializers.CharField(source="especie.nome", read_only=True)

    class Meta:
        model = Raca
        fields = [
            "id",
            "especie",
            "especie_nome",
            "nome",
            "ativo",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate(self, attrs):
        especie = attrs.get("especie") or getattr(self.instance, "especie", None)
        nome = attrs.get("nome") or getattr(self.instance, "nome", None)
        if especie and nome:
            qs = Raca.objects.filter(especie=especie, nome__iexact=nome)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"nome": ["Esta raça já está cadastrada para esta espécie."]}
                )
        return attrs


class PetSerializer(AuthoredModelSerializer):
    """Serializer completo do Pet com catálogos controlados."""

    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    especie_nome = serializers.CharField(source="especie.nome", read_only=True)
    raca_nome = serializers.CharField(source="raca.nome", read_only=True)
    idade_calculada = serializers.SerializerMethodField(read_only=True)
    sexo_display = serializers.CharField(source="get_sexo_display", read_only=True)
    historico_responsaveis = serializers.SerializerMethodField(read_only=True)

    data_nascimento = serializers.DateField(
        required=False, allow_null=True, format="%Y-%m-%d", input_formats=["%Y-%m-%d"]
    )

    class Meta:
        model = Pet
        fields = [
            "id",
            "tutor",
            "tutor_nome",
            "especie",
            "especie_nome",
            "raca",
            "raca_nome",
            "nome",
            "cor",
            "sexo",
            "sexo_display",
            "castrado",
            "vermifugado",
            "microchip",
            "identificacao_adicional",
            "data_nascimento",
            "idade",
            "idade_calculada",
            "observacoes",
            "alergias",
            "condicoes_preexistentes",
            "historico_relevante",
            "historico_responsaveis",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "criado_em",
            "atualizado_em",
            "especie_nome",
            "raca_nome",
            "sexo_display",
            "idade_calculada",
            "historico_responsaveis",
        ]

    def get_idade_calculada(self, obj):
        return obj.idade_calculada

    def get_historico_responsaveis(self, obj):
        historico = obj.historico_responsaveis.all().order_by("-data_inicio")
        return [
            {
                "tutor": h.tutor.nome,
                "tutor_id": str(h.tutor.id),
                "data_inicio": h.data_inicio,
                "data_fim": h.data_fim,
                "motivo": h.motivo,
                "is_atual": h.is_atual,
            }
            for h in historico
        ]

    def validate(self, attrs):
        # Validação cruzada: raça deve ser compatível com a espécie.
        especie = attrs.get("especie") or getattr(self.instance, "especie", None)
        raca = attrs.get("raca") or getattr(self.instance, "raca", None)
        if especie and raca and raca.especie_id != especie.pk:
            raise serializers.ValidationError(
                {"raca": ["A raça selecionada não pertence à espécie informada."]}
            )
        return attrs


class PetResumoSerializer(serializers.ModelSerializer):
    """Resumo usado para aninhar pets no tutor (busca rápida)."""

    especie_nome = serializers.CharField(source="especie.nome", read_only=True)
    raca_nome = serializers.CharField(source="raca.nome", read_only=True)

    class Meta:
        model = Pet
        fields = ["id", "nome", "especie", "especie_nome", "raca", "raca_nome"]


class PetCreateSerializer(serializers.ModelSerializer):
    """Pet sem tutor no payload: a FK é preenchida pelo service na cascata."""

    nome = serializers.CharField(
        max_length=100,
        error_messages={
            "required": "Informe o nome do pet.",
            "blank": "Informe o nome do pet.",
        },
    )
    especie = serializers.PrimaryKeyRelatedField(
        queryset=Especie.objects.filter(ativo=True),
        required=True,
        error_messages={
            "required": "Informe a espécie do pet.",
            "null": "Informe a espécie do pet.",
        },
    )
    raca = serializers.PrimaryKeyRelatedField(
        queryset=Raca.objects.filter(ativo=True),
        required=False,
        allow_null=True,
    )
    especie_nome = serializers.CharField(source="especie.nome", read_only=True)
    raca_nome = serializers.CharField(source="raca.nome", read_only=True)

    class Meta:
        model = Pet
        fields = [
            "id",
            "especie",
            "especie_nome",
            "raca",
            "raca_nome",
            "nome",
            "cor",
            "sexo",
            "castrado",
            "vermifugado",
            "microchip",
            "identificacao_adicional",
            "data_nascimento",
            "idade",
            "observacoes",
            "alergias",
            "condicoes_preexistentes",
            "historico_relevante",
        ]
        read_only_fields = ["id"]

    def validate_raca(self, value):
        """A raça deve pertencer à espécie informada."""
        if value is None:
            return value
        # Quando usado como serializer aninhado, initial_data pode não estar
        # disponível. A validação cruzada completa ocorre em validate().
        return value

    def validate(self, attrs):
        especie = attrs.get("especie")
        raca = attrs.get("raca")
        if especie and raca and raca.especie_id != especie.pk:
            raise serializers.ValidationError(
                {"raca": ["A raça selecionada não pertence à espécie informada."]}
            )
        return attrs


class HistoricoResponsabilidadePetSerializer(serializers.ModelSerializer):
    """Serializer do histórico de troca de responsável."""

    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)

    class Meta:
        model = HistoricoResponsabilidadePet
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "data_inicio",
            "data_fim",
            "motivo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MedicaoVitalSerializer(serializers.ModelSerializer):
    """Serializer de medições de sinais vitais de um pet.

    Permite registrar peso, temperatura, frequência cardíaca, respiratória,
    pressão arterial, saturação, glicemia, escore corporal e observações.
    Nenhum campo de medição é obrigatório.
    """

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    atendimento_id = serializers.CharField(
        source="atendimento.id", read_only=True
    )
    prontuario_id = serializers.CharField(
        source="prontuario.id", read_only=True
    )

    class Meta:
        model = MedicaoVital
        fields = [
            "id",
            "pet",
            "pet_nome",
            "atendimento",
            "atendimento_id",
            "prontuario",
            "prontuario_id",
            "profissional",
            "profissional_nome",
            "data_hora",
            "peso",
            "temperatura",
            "frequencia_cardíaca",
            "frequencia_respiratoria",
            "pressao_arterial",
            "saturacao",
            "glicemia",
            "escore_corporal",
            "observacoes",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate_saturacao(self, value):
        if value is not None and (value < 0 or value > 100):
            raise serializers.ValidationError(
                "A saturação de O2 deve estar entre 0 e 100."
            )
        return value

    def validate(self, attrs):
        # Pelo menos um campo de medição deve ser preenchido.
        campos_medicao = [
            "peso",
            "temperatura",
            "frequencia_cardíaca",
            "frequencia_respiratoria",
            "pressao_arterial",
            "saturacao",
            "glicemia",
            "escore_corporal",
        ]
        if not any(attrs.get(campo) is not None for campo in campos_medicao):
            raise serializers.ValidationError(
                {
                    "peso": [
                        "Informe pelo menos um parâmetro de medição "
                        "(peso, temperatura, frequência cardíaca, etc.)."
                    ]
                }
            )
        return attrs
