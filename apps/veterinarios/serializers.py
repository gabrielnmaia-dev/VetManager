"""Serializers dos modelos de veterinários e agenda."""

from rest_framework import serializers

from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado

from .models import (
    AgendamentoRecorrente,
    BloqueioAgenda,
    HistoricoStatusAtendimento,
    HorarioTrabalho,
    ListaEspera,
    Profissional,
    SalaConsultorio,
    TipoServico,
    Veterinario,
)


class VeterinarioSerializer(serializers.ModelSerializer):
    """Veterinário com identificação do profissional vinculado.

    ``id`` e ``profissional_nome`` são necessários para selecionar o
    responsável em telas que referenciam o veterinário (ex.: documentos
    veterinários). São somente leitura.
    """

    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )

    class Meta:
        model = Veterinario
        fields = [
            "id",
            "profissional",
            "profissional_nome",
            "crmv",
            "especialidade",
        ]
        read_only_fields = ["id", "profissional", "profissional_nome"]


class ProfissionalSerializer(AuthoredModelSerializer):
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


class ProfissionalResumoSerializer(serializers.ModelSerializer):
    """Resumo do profissional para respostas de atendimento."""

    class Meta:
        model = Profissional
        fields = ["id", "nome", "cargo"]


class ProfissionalCreateSerializer(serializers.ModelSerializer):
    """Cadastro de profissional com opção de criar vínculo de veterinário."""

    criar_veterinario = serializers.BooleanField(
        default=False, write_only=True,
        help_text="Se true e cargo for 'Veterinário', cria o registro de Veterinário.",
    )
    crmv = serializers.CharField(
        max_length=20, required=False, allow_blank=True, write_only=True
    )
    especialidade = serializers.CharField(
        max_length=100, required=False, allow_blank=True, write_only=True
    )

    class Meta:
        model = Profissional
        fields = [
            "id",
            "nome",
            "cargo",
            "telefone",
            "ativo",
            "criar_veterinario",
            "crmv",
            "especialidade",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def create(self, validated_data):
        criar_vet = validated_data.pop("criar_veterinario", False)
        crmv = validated_data.pop("crmv", None)
        especialidade = validated_data.pop("especialidade", "")
        profissional = Profissional.objects.create(**validated_data)
        if criar_vet and profissional.cargo == "Veterinário":
            if not crmv:
                raise serializers.ValidationError(
                    {"crmv": ["CRMV é obrigatório para criar veterinário."]}
                )
            Veterinario.objects.create(
                profissional=profissional, crmv=crmv, especialidade=especialidade
            )
        return profissional


class TipoServicoSerializer(AuthoredModelSerializer):
    class Meta:
        model = TipoServico
        fields = [
            "id",
            "nome",
            "duracao_padrao_minutos",
            "intervalo_minutos",
            "ativo",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]


class SalaConsultorioSerializer(AuthoredModelSerializer):
    class Meta:
        model = SalaConsultorio
        fields = [
            "id",
            "nome",
            "ativo",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]


class HorarioTrabalhoSerializer(AuthoredModelSerializer):
    dia_semana_display = serializers.CharField(
        source="get_dia_semana_display", read_only=True
    )
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )

    class Meta:
        model = HorarioTrabalho
        fields = [
            "id",
            "profissional",
            "profissional_nome",
            "dia_semana",
            "dia_semana_display",
            "hora_inicio",
            "hora_fim",
            "ativo",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate(self, attrs):
        hora_inicio = attrs.get("hora_inicio") or getattr(
            self.instance, "hora_inicio", None
        )
        hora_fim = attrs.get("hora_fim") or getattr(self.instance, "hora_fim", None)
        if hora_inicio and hora_fim and hora_inicio >= hora_fim:
            raise serializers.ValidationError(
                {"hora_fim": ["A hora de fim deve ser posterior à hora de início."]}
            )
        return attrs


class BloqueioAgendaSerializer(AuthoredModelSerializer):
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    sala_nome = serializers.CharField(
        source="sala.nome", read_only=True
    )
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = BloqueioAgenda
        fields = [
            "id",
            "profissional",
            "profissional_nome",
            "sala",
            "sala_nome",
            "tipo",
            "tipo_display",
            "motivo",
            "data_inicio",
            "data_fim",
            "ativo",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate(self, attrs):
        data_inicio = attrs.get("data_inicio") or getattr(
            self.instance, "data_inicio", None
        )
        data_fim = attrs.get("data_fim") or getattr(self.instance, "data_fim", None)
        if data_inicio and data_fim and data_inicio >= data_fim:
            raise serializers.ValidationError(
                {"data_fim": ["A data de fim deve ser posterior à data de início."]}
            )
        return attrs


class ListaEsperaSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    tipo_servico_nome = serializers.CharField(
        source="tipo_servico.nome", read_only=True
    )

    class Meta:
        model = ListaEspera
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "profissional",
            "profissional_nome",
            "tipo_servico",
            "tipo_servico_nome",
            "data_desejada",
            "horario_inicio_desejado",
            "horario_fim_desejado",
            "observacoes",
            "ativo",
            "atendimento_gerado",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "atendimento_gerado",
            "criado_em",
            "atualizado_em",
        ]


class AgendamentoRecorrenteSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    tipo_servico_nome = serializers.CharField(
        source="tipo_servico.nome", read_only=True
    )
    sala_nome = serializers.CharField(
        source="sala.nome", read_only=True
    )
    dia_semana_display = serializers.CharField(
        source="get_dia_semana_display", read_only=True
    )

    class Meta:
        model = AgendamentoRecorrente
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor",
            "profissional",
            "profissional_nome",
            "tipo_servico",
            "tipo_servico_nome",
            "sala",
            "sala_nome",
            "duracao_minutos",
            "dia_semana",
            "dia_semana_display",
            "hora_inicio",
            "data_inicio",
            "data_fim",
            "ativo",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate(self, attrs):
        dia_semana = attrs.get("dia_semana") or getattr(
            self.instance, "dia_semana", None
        )
        hora_inicio = attrs.get("hora_inicio") or getattr(
            self.instance, "hora_inicio", None
        )
        data_inicio = attrs.get("data_inicio") or getattr(
            self.instance, "data_inicio", None
        )
        if (
            dia_semana is not None
            and hora_inicio is not None
            and data_inicio is not None
            and data_inicio.weekday() != dia_semana
        ):
            raise serializers.ValidationError(
                {
                    "data_inicio": [
                        "A data de início deve cair no dia da semana informado."
                    ]
                }
            )
        return attrs


class HistoricoStatusAtendimentoSerializer(serializers.ModelSerializer):
    usuario_username = serializers.CharField(
        source="usuario.username", read_only=True
    )

    class Meta:
        model = HistoricoStatusAtendimento
        fields = [
            "id",
            "atendimento",
            "status_anterior",
            "status_novo",
            "motivo",
            "data_operacao",
            "usuario",
            "usuario_username",
        ]
        read_only_fields = [
            "id",
            "data_operacao",
            "usuario",
            "usuario_username",
        ]
