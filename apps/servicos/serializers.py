"""Serializers do catálogo de serviços, orçamentos e serviços realizados."""

from decimal import Decimal

from rest_framework import serializers

from apps.atendimentos.models import Atendimento
from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from apps.veterinarios.models import Profissional

from . import services
from .models import (
    CategoriaServico,
    HistoricoOrcamento,
    ItemOrcamento,
    Orcamento,
    Servico,
    ServicoRealizado,
)


class CategoriaServicoSerializer(AuthoredModelSerializer):
    servicos_count = serializers.SerializerMethodField()

    class Meta:
        model = CategoriaServico
        fields = [
            "id",
            "nome",
            "descricao",
            "ativo",
            "servicos_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "servicos_count",
            "created_at",
            "updated_at",
        ]

    def get_servicos_count(self, obj):
        return obj.servicos.count()

    def validate_nome(self, valor):
        valor = (valor or "").strip()
        if not valor:
            raise serializers.ValidationError("Informe o nome da categoria.")
        qs = CategoriaServico.objects.filter(nome__iexact=valor)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Já existe uma categoria de serviço com este nome."
            )
        return valor


class ServicoSerializer(AuthoredModelSerializer):
    categoria = serializers.PrimaryKeyRelatedField(
        queryset=CategoriaServico.objects.filter(is_deleted=False)
    )
    categoria_nome = serializers.CharField(
        source="categoria.nome", read_only=True
    )
    situacao_display = serializers.CharField(
        source="get_situacao_display", read_only=True
    )
    orcamentos_count = serializers.SerializerMethodField()
    realizados_count = serializers.SerializerMethodField()

    class Meta:
        model = Servico
        fields = [
            "id",
            "nome",
            "categoria",
            "categoria_nome",
            "descricao",
            "preco_base",
            "duracao_estimada_minutos",
            "situacao",
            "situacao_display",
            "regras",
            "permite_desconto",
            "desconto_maximo_percentual",
            "orcamentos_count",
            "realizados_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "categoria_nome",
            "situacao_display",
            "orcamentos_count",
            "realizados_count",
            "created_at",
            "updated_at",
        ]

    def get_orcamentos_count(self, obj):
        return obj.itens_orcamento.count()

    def get_realizados_count(self, obj):
        return obj.servicos_realizados.count()

    def validate_nome(self, valor):
        valor = (valor or "").strip()
        if not valor:
            raise serializers.ValidationError("Informe o nome do serviço.")
        qs = Servico.objects.filter(nome__iexact=valor)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Já existe um serviço com este nome."
            )
        return valor

    def validate_preco_base(self, valor):
        if valor is None:
            return Decimal("0.00")
        if valor < 0:
            raise serializers.ValidationError(
                "O preço base não pode ser negativo."
            )
        return valor

    def validate_desconto_maximo_percentual(self, valor):
        if valor is None:
            return Decimal("0.00")
        if valor < 0 or valor > 100:
            raise serializers.ValidationError(
                "O desconto máximo deve estar entre 0 e 100."
            )
        return valor


class ItemOrcamentoSerializer(AuthoredModelSerializer):
    servico = serializers.PrimaryKeyRelatedField(
        queryset=Servico.objects.filter(is_deleted=False)
    )
    servico_nome = serializers.CharField(source="servico.nome", read_only=True)
    servico_categoria = serializers.CharField(
        source="servico.categoria.nome", read_only=True
    )
    desconto_autorizado_por_nome = serializers.SerializerMethodField()

    class Meta:
        model = ItemOrcamento
        fields = [
            "id",
            "servico",
            "servico_nome",
            "servico_categoria",
            "quantidade",
            "valor_unitario",
            "desconto",
            "valor_total",
            "desconto_motivo",
            "desconto_autorizado_por_nome",
            "observacoes",
        ]
        read_only_fields = [
            "id",
            "servico_nome",
            "servico_categoria",
            "valor_total",
            "desconto_autorizado_por_nome",
        ]

    def get_desconto_autorizado_por_nome(self, obj):
        if obj.desconto_autorizado_por_id is None:
            return None
        return obj.desconto_autorizado_por.get_username()


class HistoricoOrcamentoSerializer(serializers.ModelSerializer):
    status_anterior_display = serializers.CharField(
        source="get_status_anterior_display", read_only=True
    )
    status_novo_display = serializers.CharField(
        source="get_status_novo_display", read_only=True
    )
    usuario_nome = serializers.SerializerMethodField()

    class Meta:
        model = HistoricoOrcamento
        fields = [
            "id",
            "status_anterior",
            "status_anterior_display",
            "status_novo",
            "status_novo_display",
            "usuario_nome",
            "observacao",
            "created_at",
        ]
        read_only_fields = fields

    def get_usuario_nome(self, obj):
        if obj.usuario_id is None:
            return None
        return obj.usuario.get_username()


class OrcamentoSerializer(AuthoredModelSerializer):
    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    vencido = serializers.BooleanField(read_only=True)
    editavel = serializers.BooleanField(read_only=True)
    itens = ItemOrcamentoSerializer(many=True, required=False)
    itens_count = serializers.SerializerMethodField()
    historico = HistoricoOrcamentoSerializer(many=True, read_only=True)
    chave_idempotencia = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    class Meta:
        model = Orcamento
        fields = [
            "id",
            "tutor",
            "tutor_nome",
            "pet",
            "pet_nome",
            "atendimento",
            "profissional",
            "data_hora",
            "validade",
            "status",
            "status_display",
            "observacoes",
            "subtotal",
            "valor_desconto",
            "valor_total",
            "motivo_recusa",
            "decidido_por",
            "aprovado_em",
            "recusado_em",
            "convertido_em",
            "cancelado_em",
            "vencido",
            "editavel",
            "itens",
            "itens_count",
            "historico",
            "chave_idempotencia",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tutor_nome",
            "pet_nome",
            "status",
            "status_display",
            "subtotal",
            "valor_desconto",
            "valor_total",
            "motivo_recusa",
            "decidido_por",
            "aprovado_em",
            "recusado_em",
            "convertido_em",
            "cancelado_em",
            "vencido",
            "editavel",
            "itens_count",
            "historico",
            "created_at",
            "updated_at",
        ]

    def get_itens_count(self, obj):
        return obj.itens.count()

    def create(self, validated_data):
        itens = validated_data.pop("itens", [])
        orcamento = services.salvar_orcamento(
            dados=validated_data,
            itens=itens,
            usuario=usuario_autenticado(self.context),
        )
        return orcamento

    def update(self, instance, validated_data):
        itens = validated_data.pop("itens", None)
        return services.salvar_orcamento(
            dados=validated_data,
            itens=itens,
            orcamento=instance,
            usuario=usuario_autenticado(self.context),
        )


class ConversaoOrcamentoSerializer(serializers.Serializer):
    """Dados opcionais para converter o orçamento em serviços realizados."""

    atendimento = serializers.PrimaryKeyRelatedField(
        queryset=Atendimento.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    profissional = serializers.PrimaryKeyRelatedField(
        queryset=Profissional.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    data_hora = serializers.DateTimeField(required=False, allow_null=True)


class ServicoRealizadoSerializer(AuthoredModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(
        source="pet.tutor.nome", read_only=True
    )
    servico_nome = serializers.CharField(source="servico.nome", read_only=True)
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    desconto_autorizado_por_nome = serializers.SerializerMethodField()
    chave_idempotencia = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    class Meta:
        model = ServicoRealizado
        fields = [
            "id",
            "atendimento",
            "pet",
            "pet_nome",
            "tutor_nome",
            "servico",
            "servico_nome",
            "profissional",
            "profissional_nome",
            "quantidade",
            "valor_unitario",
            "desconto",
            "valor_total",
            "desconto_motivo",
            "desconto_autorizado_por_nome",
            "data_hora",
            "observacoes",
            "orcamento_item",
            "chave_idempotencia",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "pet_nome",
            "tutor_nome",
            "servico_nome",
            "profissional_nome",
            "valor_total",
            "desconto_autorizado_por_nome",
            "orcamento_item",
            "created_at",
        ]

    def get_desconto_autorizado_por_nome(self, obj):
        if obj.desconto_autorizado_por_id is None:
            return None
        return obj.desconto_autorizado_por.get_username()

    def create(self, validated_data):
        registro = services.registrar_servico_realizado(
            dados=validated_data,
            usuario=usuario_autenticado(self.context),
        )
        return registro
