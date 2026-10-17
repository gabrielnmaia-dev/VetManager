from rest_framework import serializers

from apps.pets.models import Pet
from apps.pets.serializers import PetCreateSerializer, PetResumoSerializer
from apps.tutores.models import Tutor
from apps.tutores.serializers import TutorCreateSerializer, TutorResumoSerializer
from apps.veterinarios.models import Profissional
from apps.veterinarios.serializers import ProfissionalResumoSerializer

from .models import Atendimento
from .services import atualizar_atendimento, criar_atendimento, criar_atendimento_rapido


def _validar_profissional_obrigatorio(attrs, instance=None):
    """Exige pelo menos um identificador do profissional.

    - ``profissional_id`` (novo, preferencial): no serializer legado ele chega
      em attrs como ``profissional`` (source renomeia para a FK);
    - ``nome_profissional`` (legado): texto livre.

    Quando os dois vêm, a FK vence e o service espelha ``profissional.nome``
    em ``nome_profissional``. Na edição, o valor já salvo no registro conta
    como presente (PUT/PATCH parcial não precisa repeti-lo).
    """
    tem_fk = (
        attrs.get("profissional_id") is not None
        or attrs.get("profissional") is not None
        or (instance is not None and instance.profissional_id is not None)
    )
    nome = attrs.get("nome_profissional")
    if nome is None and instance is not None:
        nome = instance.nome_profissional
    if not tem_fk and not nome:
        raise serializers.ValidationError(
            {"profissional": ["Informe profissional_id ou nome_profissional."]}
        )
    return attrs


class AtendimentoSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor = serializers.PrimaryKeyRelatedField(source="pet.tutor", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    tipo_servico_display = serializers.CharField(
        source="get_tipo_servico_display",
        read_only=True,
    )
    # Escrita nova: profissional_id (source renomeia para a FK "profissional").
    profissional_id = serializers.PrimaryKeyRelatedField(
        source="profissional",
        queryset=Profissional.objects.all(),
        required=False,
        allow_null=True,
        help_text="ID do profissional cadastrado (preferencial).",
    )
    # Leitura: resumo do profissional já vinculado.
    profissional = ProfissionalResumoSerializer(read_only=True)
    # Legado: continua aceito na escrita, mas agora é opcional
    # (o service o espelha a partir da FK quando ela existe).
    nome_profissional = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )

    class Meta:
        model = Atendimento
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "profissional_id",
            "profissional",
            "nome_profissional",
            "tipo_servico",
            "tipo_servico_display",
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

    def validate(self, attrs):
        return _validar_profissional_obrigatorio(attrs, instance=self.instance)

    def create(self, validated_data):
        return criar_atendimento(validated_data)

    def update(self, instance, validated_data):
        return atualizar_atendimento(instance, validated_data)


class AtendimentoRapidoSerializer(serializers.Serializer):
    """POST /api/v1/atendimentos/rapido/: use tutor_id/pet_id para registros
    já existentes ou tutor/pet (dicts) para cadastrá-los em cascata — nunca
    os dois ao mesmo tempo. Para o profissional, envie profissional_id
    (preferencial) ou nome_profissional (legado) — pelo menos um dos dois.
    Depois, os dados do próprio atendimento."""

    tutor_id = serializers.PrimaryKeyRelatedField(
        queryset=Tutor.objects.all(),
        required=False,
    )
    tutor = TutorCreateSerializer(required=False)
    pet_id = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.select_related("tutor"),
        required=False,
    )
    pet = PetCreateSerializer(required=False)

    profissional_id = serializers.PrimaryKeyRelatedField(
        queryset=Profissional.objects.all(),
        required=False,
        help_text="ID do profissional cadastrado (preferencial).",
    )
    nome_profissional = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        help_text="Legado: aceito quando não vier profissional_id.",
    )

    tipo_servico = serializers.ChoiceField(
        choices=Atendimento.TipoServico.choices,
        error_messages={
            "required": "Informe o tipo de serviço.",
            "invalid_choice": "Tipo de serviço inválido.",
        },
    )
    queixa = serializers.CharField(required=False, allow_blank=True)
    data_hora_inicio = serializers.DateTimeField(
        error_messages={"required": "Informe a data e hora de início."},
    )
    duracao_minutos = serializers.IntegerField(
        required=False,
        min_value=1,
        error_messages={
            "min_value": "A duração deve ser de pelo menos 1 minuto.",
        },
    )
    status = serializers.ChoiceField(
        choices=Atendimento.Status.choices,
        required=False,
        error_messages={"invalid_choice": "Status inválido."},
    )
    observacoes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        # tutor_id OU tutor: nem os dois, nem nenhum.
        tem_tutor_id = attrs.get("tutor_id") is not None
        tem_tutor = attrs.get("tutor") is not None
        if tem_tutor_id and tem_tutor:
            raise serializers.ValidationError(
                {"tutor_id": ["Não informe tutor_id e tutor ao mesmo tempo."]}
            )
        if not tem_tutor_id and not tem_tutor:
            raise serializers.ValidationError(
                {"tutor": ["Informe tutor_id ou tutor."]}
            )

        # pet_id OU pet: nem os dois, nem nenhum.
        tem_pet_id = attrs.get("pet_id") is not None
        tem_pet = attrs.get("pet") is not None
        if tem_pet_id and tem_pet:
            raise serializers.ValidationError(
                {"pet_id": ["Não informe pet_id e pet ao mesmo tempo."]}
            )
        if not tem_pet_id and not tem_pet:
            raise serializers.ValidationError(
                {"pet": ["Informe pet_id ou pet."]}
            )

        # profissional_id OU nome_profissional: pelo menos um dos dois.
        _validar_profissional_obrigatorio(attrs)

        return attrs

    def create(self, validated_data):
        return criar_atendimento_rapido(validated_data)


class AtendimentoRapidoResponseSerializer(AtendimentoSerializer):
    """Resposta do atendimento rápido: tutor e pet aninhados em resumo."""

    pet = PetResumoSerializer(read_only=True)
    tutor = TutorResumoSerializer(source="pet.tutor", read_only=True)

    class Meta(AtendimentoSerializer.Meta):
        pass
