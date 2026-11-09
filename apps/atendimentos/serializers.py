"""Serializers do app atendimentos com suporte a agenda, salas e status."""

from rest_framework import serializers

from apps.pets.models import Pet
from apps.pets.serializers import PetCreateSerializer, PetResumoSerializer
from apps.tutores.models import Tutor
from apps.tutores.serializers import TutorCreateSerializer, TutorResumoSerializer
from apps.veterinarios.models import Profissional, SalaConsultorio
from apps.veterinarios.serializers import ProfissionalResumoSerializer

from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado

from .models import Atendimento
from .services import (
    atualizar_atendimento,
    cancelar_atendimento,
    criar_atendimento,
    criar_atendimento_rapido,
    confirmar_atendimento,
    reagendar_atendimento,
    marcar_faltou,
)


def _validar_profissional_obrigatorio(attrs, instance=None):
    """Exige pelo menos um identificador do profissional."""
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


class AtendimentoSerializer(AuthoredModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor = serializers.PrimaryKeyRelatedField(
        source="pet.tutor", read_only=True
    )
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    tipo_servico_display = serializers.CharField(
        source="get_tipo_servico_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    profissional_id = serializers.PrimaryKeyRelatedField(
        source="profissional",
        queryset=Profissional.objects.all(),
        required=False,
        allow_null=True,
        help_text="ID do profissional cadastrado (preferencial).",
    )
    profissional = ProfissionalResumoSerializer(read_only=True)
    nome_profissional = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    sala = serializers.PrimaryKeyRelatedField(
        queryset=SalaConsultorio.objects.filter(ativo=True),
        required=False,
        allow_null=True,
        help_text="Sala/consultório para o atendimento.",
    )
    sala_nome = serializers.CharField(
        source="sala.nome", read_only=True
    )
    tutor_telefone = serializers.CharField(
        source="pet.tutor.telefone", read_only=True
    )
    tutor_endereco = serializers.CharField(
        source="pet.tutor.endereco", read_only=True
    )

    class Meta:
        model = Atendimento
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "tutor_telefone",
            "tutor_endereco",
            "profissional_id",
            "profissional",
            "nome_profissional",
            "sala",
            "sala_nome",
            "tipo_servico",
            "tipo_servico_display",
            "queixa",
            "data_hora_inicio",
            "duracao_minutos",
            "status",
            "status_display",
            "observacoes",
            "taxidog",
            "motivo_cancelamento",
            "data_confirmacao",
            "data_cancelamento",
            "reagendado_de",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "tutor_telefone",
            "tutor_endereco",
            "tipo_servico_display",
            "status_display",
            "criado_em",
            "atualizado_em",
            "data_confirmacao",
            "data_cancelamento",
            "reagendado_de",
        ]

    def validate(self, attrs):
        return _validar_profissional_obrigatorio(attrs, instance=self.instance)

    def create(self, validated_data):
        user = usuario_autenticado(self.context)
        if user is not None:
            validated_data["created_by"] = user
            validated_data["updated_by"] = user
        return criar_atendimento(validated_data, user=user)

    def update(self, instance, validated_data):
        user = usuario_autenticado(self.context)
        if user is not None:
            validated_data["updated_by"] = user
        return atualizar_atendimento(instance, validated_data, user=user)


class AtendimentoRapidoSerializer(serializers.Serializer):
    """POST /api/v1/atendimentos/rapido/"""

    tutor_id = serializers.PrimaryKeyRelatedField(
        queryset=Tutor.objects.all(), required=False
    )
    tutor = TutorCreateSerializer(required=False)
    pet_id = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.select_related("tutor"), required=False
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
    sala = serializers.PrimaryKeyRelatedField(
        queryset=SalaConsultorio.objects.filter(ativo=True),
        required=False,
        allow_null=True,
        help_text="Sala/consultório para o atendimento.",
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
        error_messages={"min_value": "A duração deve ser de pelo menos 1 minuto."},
    )
    status = serializers.ChoiceField(
        choices=Atendimento.Status.choices,
        required=False,
        error_messages={"invalid_choice": "Status inválido."},
    )
    observacoes = serializers.CharField(required=False, allow_blank=True)
    taxidog = serializers.BooleanField(required=False)

    def validate(self, attrs):
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

        _validar_profissional_obrigatorio(attrs)

        return attrs

    def create(self, validated_data):
        user = usuario_autenticado(self.context)
        return criar_atendimento_rapido(validated_data, user=user)


class AtendimentoRapidoResponseSerializer(AtendimentoSerializer):
    pet = PetResumoSerializer(read_only=True)
    tutor = TutorResumoSerializer(source="pet.tutor", read_only=True)

    class Meta(AtendimentoSerializer.Meta):
        pass


class AtendimentoConfirmarSerializer(serializers.Serializer):
    """POST /api/v1/atendimentos/:id/confirmar/"""

    justificativa = serializers.CharField(required=False, allow_blank=True)


class AtendimentoCancelarSerializer(serializers.Serializer):
    """POST /api/v1/atendimentos/:id/cancelar/"""

    motivo = serializers.CharField(
        required=True, help_text="Motivo do cancelamento."
    )


class AtendimentoReagendarSerializer(serializers.Serializer):
    """POST /api/v1/atendimentos/:id/reagendar/"""

    data_hora_inicio = serializers.DateTimeField(
        required=True, help_text="Nova data e hora do atendimento."
    )
    duracao_minutos = serializers.IntegerField(
        required=False, min_value=1
    )
    sala = serializers.PrimaryKeyRelatedField(
        queryset=SalaConsultorio.objects.filter(ativo=True),
        required=False,
        allow_null=True,
    )
    justificativa = serializers.CharField(required=False, allow_blank=True)


class AtendimentoFaltouSerializer(serializers.Serializer):
    """POST /api/v1/atendimentos/:id/faltou/"""

    justificativa = serializers.CharField(required=False, allow_blank=True)
