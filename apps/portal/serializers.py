"""Serializers do portal. Expõem somente campos aprovados para o tutor."""

from rest_framework import serializers

from apps.atendimentos.models import Atendimento
from apps.documentos.models import DocumentoClinico, DocumentoVeterinario
from apps.pets.models import Pet
from apps.prescricao.models import Prescricao
from apps.prontuario.models import Vacina
from apps.tutores.models import Tutor

from .models import (
    AcessoPortal,
    ConviteAcessoPortal,
    NotificacaoPortal,
    SolicitacaoAgendamento,
)


class PortalLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(
        write_only=True, trim_whitespace=False, style={"input_type": "password"}
    )


class PortalPetSerializer(serializers.ModelSerializer):
    """Dados cadastrais do animal, sem anotações internas do prontuário."""

    especie_nome = serializers.CharField(source="especie.nome", read_only=True)
    raca_nome = serializers.CharField(source="raca.nome", read_only=True)
    sexo_display = serializers.CharField(source="get_sexo_display", read_only=True)
    idade_calculada = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Pet
        fields = [
            "id",
            "nome",
            "especie",
            "especie_nome",
            "raca",
            "raca_nome",
            "sexo",
            "sexo_display",
            "cor",
            "castrado",
            "vermifugado",
            "microchip",
            "data_nascimento",
            "idade",
            "idade_calculada",
            "alergias",
            "condicoes_preexistentes",
        ]
        read_only_fields = fields


class PortalAgendamentoSerializer(serializers.ModelSerializer):
    """Agendamento real do animal, em modo somente leitura."""

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tipo_servico_display = serializers.CharField(
        source="get_tipo_servico_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    profissional_nome = serializers.SerializerMethodField()

    class Meta:
        model = Atendimento
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tipo_servico",
            "tipo_servico_display",
            "data_hora_inicio",
            "duracao_minutos",
            "status",
            "status_display",
            "profissional_nome",
        ]
        read_only_fields = fields

    def get_profissional_nome(self, obj):
        if obj.profissional_id:
            return obj.profissional.nome
        return obj.nome_profissional


class PortalVacinaSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    via_display = serializers.CharField(source="get_via_aplicacao_display", read_only=True)
    situacao = serializers.CharField(read_only=True)
    situacao_display = serializers.SerializerMethodField()
    dias_para_retorno = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Vacina
        fields = [
            "id",
            "pet",
            "pet_nome",
            "nome_vacina",
            "data_aplicacao",
            "data_retorno",
            "lote",
            "fabricante",
            "via_aplicacao",
            "via_display",
            "dose",
            "situacao",
            "situacao_display",
            "dias_para_retorno",
        ]
        read_only_fields = fields

    def get_situacao_display(self, obj):
        return obj.Situacao(obj.situacao).label


class PortalSolicitacaoAgendamentoSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tipo_servico_display = serializers.CharField(
        source="get_tipo_servico_display", read_only=True
    )
    periodo_display = serializers.CharField(
        source="get_periodo_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )

    class Meta:
        model = SolicitacaoAgendamento
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tipo_servico",
            "tipo_servico_display",
            "data_preferida",
            "periodo",
            "periodo_display",
            "observacoes",
            "status",
            "status_display",
            "resposta",
            "respondido_em",
            "atendimento",
            "created_at",
        ]
        read_only_fields = fields


class PortalSolicitacaoCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolicitacaoAgendamento
        fields = [
            "pet",
            "tipo_servico",
            "data_preferida",
            "periodo",
            "observacoes",
        ]

    def validate_pet(self, pet):
        acesso = self.context.get("portal_acesso")
        if acesso is None or pet.tutor_id != acesso.tutor_id:
            raise serializers.ValidationError("Animal não pertence ao seu cadastro.")
        return pet

    def validate_data_preferida(self, data):
        from django.utils import timezone

        if data < timezone.localdate():
            raise serializers.ValidationError("Escolha uma data a partir de hoje.")
        return data


class PortalNotificacaoSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)

    class Meta:
        model = NotificacaoPortal
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tipo",
            "tipo_display",
            "titulo",
            "mensagem",
            "lida",
            "lida_em",
            "created_at",
        ]
        read_only_fields = fields


class PortalItemPrescricaoSerializer(serializers.Serializer):
    """Somente o conteúdo necessário para o tutor seguir a receita."""

    id = serializers.UUIDField(read_only=True)
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    principio_ativo = serializers.CharField(
        source="produto.principio_ativo", read_only=True
    )
    concentracao = serializers.CharField(source="produto.concentracao", read_only=True)
    forma_farmaceutica = serializers.CharField(
        source="produto.forma_farmaceutica", read_only=True
    )
    unidade_dispensacao = serializers.CharField(
        source="produto.unidade_dispensacao", read_only=True
    )
    dose = serializers.CharField(read_only=True)
    via_display = serializers.CharField(source="get_via_display", read_only=True)
    frequencia = serializers.CharField(read_only=True)
    duracao = serializers.CharField(read_only=True)
    quantidade_prescrita = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    observacoes = serializers.CharField(read_only=True)


class PortalPrescricaoSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    veterinario_nome = serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    veterinario_crmv = serializers.CharField(source="veterinario.crmv", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    itens = PortalItemPrescricaoSerializer(many=True, read_only=True)

    class Meta:
        model = Prescricao
        fields = [
            "id",
            "pet",
            "pet_nome",
            "veterinario_nome",
            "veterinario_crmv",
            "data_prescricao",
            "observacoes",
            "status",
            "status_display",
            "itens",
        ]
        read_only_fields = fields


class PortalPerfilSerializer(serializers.ModelSerializer):
    """Atualização de contato pelo próprio tutor.

    CPF e vínculo não são editáveis pelo portal: identidade e titularidade são
    alteradas apenas pela clínica.
    """

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Tutor
        fields = [
            "id",
            "nome",
            "telefone",
            "email",
            "cpf",
            "endereco",
            "username",
        ]
        read_only_fields = ["id", "cpf", "username"]

    def validate_nome(self, value):
        value = " ".join((value or "").split())
        if not value:
            raise serializers.ValidationError("Informe o nome.")
        return value.title()

    def validate_email(self, value):
        return (value or "").strip().lower()


class AlterarSenhaPortalSerializer(serializers.Serializer):
    senha_atual = serializers.CharField(
        write_only=True, trim_whitespace=False, style={"input_type": "password"}
    )
    nova_senha = serializers.CharField(
        write_only=True, trim_whitespace=False, style={"input_type": "password"}
    )
    confirmar_nova_senha = serializers.CharField(
        write_only=True, trim_whitespace=False, style={"input_type": "password"}
    )

    def validate_senha_atual(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Senha atual incorreta.")
        return value

    def validate_nova_senha(self, value):
        from django.contrib.auth import password_validation
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            password_validation.validate_password(value, user=self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if attrs["nova_senha"] != attrs["confirmar_nova_senha"]:
            raise serializers.ValidationError(
                {"confirmar_nova_senha": "As senhas não coincidem."}
            )
        if attrs["nova_senha"] == attrs["senha_atual"]:
            raise serializers.ValidationError(
                {"nova_senha": "A nova senha deve ser diferente da atual."}
            )
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["nova_senha"])
        user.save(update_fields=["password"])
        return user


# ---------------------------------------------------------------------------
# Administração interna do portal
# ---------------------------------------------------------------------------


class ConviteAcessoPortalSerializer(serializers.ModelSerializer):
    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    status = serializers.CharField(read_only=True)
    status_display = serializers.SerializerMethodField()

    class Meta:
        model = ConviteAcessoPortal
        fields = [
            "id",
            "tutor",
            "tutor_nome",
            "email",
            "nome",
            "status",
            "status_display",
            "expira_em",
            "usado_em",
            "revogado_em",
            "created_at",
        ]
        read_only_fields = fields

    def get_status_display(self, obj):
        return ConviteAcessoPortal.Status(obj.status).label


class ConviteAcessoPortalCreateSerializer(serializers.Serializer):
    tutor = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.filter(is_deleted=False))
    email = serializers.EmailField(required=False, allow_blank=True)
    nome = serializers.CharField(required=False, allow_blank=True, max_length=150)


class AcessoPortalSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    sessoes_ativas = serializers.SerializerMethodField()

    class Meta:
        model = AcessoPortal
        fields = [
            "id",
            "username",
            "user_email",
            "tutor",
            "tutor_nome",
            "ativo",
            "revogado_em",
            "ultimo_acesso_em",
            "consentimento_privacidade_em",
            "consentimento_privacidade_versao",
            "sessoes_ativas",
            "created_at",
        ]
        read_only_fields = fields

    def get_sessoes_ativas(self, obj):
        return obj.sessoes.filter(
            revogada_em__isnull=True,
            is_deleted=False,
        ).count()


class SolicitacaoAgendamentoAdminSerializer(serializers.ModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    tipo_servico_display = serializers.CharField(
        source="get_tipo_servico_display", read_only=True
    )
    periodo_display = serializers.CharField(
        source="get_periodo_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SolicitacaoAgendamento
        fields = [
            "id",
            "tutor",
            "tutor_nome",
            "pet",
            "pet_nome",
            "tipo_servico",
            "tipo_servico_display",
            "data_preferida",
            "periodo",
            "periodo_display",
            "observacoes",
            "status",
            "status_display",
            "resposta",
            "respondido_em",
            "atendimento",
            "created_at",
        ]
        read_only_fields = fields


class NotificacaoPortalCreateSerializer(serializers.Serializer):
    tutor = serializers.PrimaryKeyRelatedField(queryset=Tutor.objects.filter(is_deleted=False))
    pet = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    tipo = serializers.ChoiceField(
        choices=NotificacaoPortal.Tipo.choices,
        default=NotificacaoPortal.Tipo.GERAL,
    )
    titulo = serializers.CharField(max_length=150)
    mensagem = serializers.CharField()

    def validate(self, attrs):
        pet = attrs.get("pet")
        if pet is not None and pet.tutor_id != attrs["tutor"].pk:
            raise serializers.ValidationError(
                {"pet": ["O animal não pertence ao tutor informado."]}
            )
        return attrs


class LiberacaoDocumentoSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(
        choices=["clinico", "veterinario", "prescricao"],
    )
    id = serializers.UUIDField()
    liberado = serializers.BooleanField(default=True)
    motivo = serializers.CharField(required=False, allow_blank=True)
