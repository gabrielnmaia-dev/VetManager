"""Serializers da prescrição estruturada e da administração de medicamentos."""

from django.db.models import Sum
from rest_framework import serializers

from apps.atendimentos.models import Atendimento
from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from apps.estoque.models import Lote, Produto
from apps.pets.models import Pet
from apps.prontuario.models import Prontuario
from apps.veterinarios.models import Profissional, Veterinario

from . import services
from .models import (
    AdministracaoMedicamento,
    ItemPrescricao,
    Prescricao,
)


class ItemPrescricaoSerializer(AuthoredModelSerializer):
    """Item clínico da prescrição, com dados do catálogo para exibição."""

    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_codigo = serializers.CharField(
        source="produto.codigo_interno", read_only=True
    )
    principio_ativo = serializers.CharField(
        source="produto.principio_ativo", read_only=True
    )
    concentracao = serializers.CharField(
        source="produto.concentracao", read_only=True
    )
    forma_farmaceutica = serializers.CharField(
        source="produto.forma_farmaceutica", read_only=True
    )
    unidade_dispensacao = serializers.CharField(
        source="produto.unidade_dispensacao", read_only=True
    )
    via_display = serializers.CharField(source="get_via_display", read_only=True)
    quantidade_administrada = serializers.SerializerMethodField()

    class Meta:
        model = ItemPrescricao
        fields = [
            "id",
            "produto",
            "produto_nome",
            "produto_codigo",
            "principio_ativo",
            "concentracao",
            "forma_farmaceutica",
            "unidade_dispensacao",
            "dose",
            "via",
            "via_display",
            "frequencia",
            "duracao",
            "quantidade_prescrita",
            "quantidade_administrada",
            "observacoes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "produto_nome",
            "produto_codigo",
            "principio_ativo",
            "concentracao",
            "forma_farmaceutica",
            "unidade_dispensacao",
            "via_display",
            "quantidade_administrada",
            "created_at",
            "updated_at",
        ]

    def get_quantidade_administrada(self, obj):
        total = obj.administracoes.filter(
            status=AdministracaoMedicamento.Status.ATIVA
        ).aggregate(total=Sum("quantidade"))["total"]
        return total or 0


class PrescricaoSerializer(AuthoredModelSerializer):
    """Prescrição com itens aninhados; a criação delega ao serviço."""

    pet = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    veterinario = serializers.PrimaryKeyRelatedField(
        queryset=Veterinario.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    prontuario = serializers.PrimaryKeyRelatedField(
        queryset=Prontuario.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    atendimento = serializers.PrimaryKeyRelatedField(
        queryset=Atendimento.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    veterinario_nome = serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    veterinario_crmv = serializers.CharField(
        source="veterinario.crmv", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    cancelada_por_username = serializers.SerializerMethodField()
    itens = ItemPrescricaoSerializer(many=True)
    itens_count = serializers.SerializerMethodField()
    administracoes_count = serializers.SerializerMethodField()
    administracoes_ativas = serializers.SerializerMethodField()

    class Meta:
        model = Prescricao
        fields = [
            "id",
            "prontuario",
            "atendimento",
            "pet",
            "pet_nome",
            "tutor_nome",
            "veterinario",
            "veterinario_nome",
            "veterinario_crmv",
            "data_prescricao",
            "observacoes",
            "status",
            "status_display",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "cancelada_por_username",
            "itens",
            "itens_count",
            "administracoes_count",
            "administracoes_ativas",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "pet_nome",
            "tutor_nome",
            "veterinario_nome",
            "veterinario_crmv",
            "status",
            "status_display",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "cancelada_por_username",
            "itens_count",
            "administracoes_count",
            "administracoes_ativas",
            "created_at",
            "updated_at",
        ]

    def get_cancelada_por_username(self, obj):
        return obj.cancelada_por.username if obj.cancelada_por else ""

    def get_itens_count(self, obj):
        return len(obj.itens.all())

    def get_administracoes_count(self, obj):
        return len(obj.administracoes.all())

    def get_administracoes_ativas(self, obj):
        return sum(
            1
            for administracao in obj.administracoes.all()
            if administracao.status == AdministracaoMedicamento.Status.ATIVA
        )

    def validate(self, attrs):
        if self.instance is None:
            if not attrs.get("itens"):
                raise serializers.ValidationError(
                    {"itens": ["Inclua ao menos um medicamento na prescrição."]}
                )
            if (
                not attrs.get("pet")
                and not attrs.get("prontuario")
                and not attrs.get("atendimento")
            ):
                raise serializers.ValidationError(
                    {"pet": ["Informe o animal ou vincule um prontuário/atendimento."]}
                )
            if (
                not attrs.get("veterinario")
                and not attrs.get("prontuario")
            ):
                raise serializers.ValidationError(
                    {"veterinario": ["Informe o veterinário responsável."]}
                )
        return attrs

    def create(self, validated_data):
        itens = validated_data.pop("itens", [])
        return services.criar_prescricao(
            itens=itens,
            usuario=usuario_autenticado(self.context),
            **validated_data,
        )


class AdministracaoMedicamentoSerializer(AuthoredModelSerializer):
    """Administração clínica com baixa automática e idempotente no estoque."""

    item_prescricao = serializers.PrimaryKeyRelatedField(
        queryset=ItemPrescricao.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    pet = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    produto = serializers.PrimaryKeyRelatedField(
        queryset=Produto.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    lote = serializers.PrimaryKeyRelatedField(
        queryset=Lote.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
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
    chave_idempotencia = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        write_only=True,
    )

    prescricao = serializers.PrimaryKeyRelatedField(read_only=True)
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_codigo = serializers.CharField(
        source="produto.codigo_interno", read_only=True
    )
    unidade_dispensacao = serializers.CharField(
        source="produto.unidade_dispensacao", read_only=True
    )
    lote_numero = serializers.CharField(source="lote.numero_lote", read_only=True)
    lote_validade = serializers.DateField(
        source="lote.data_validade", read_only=True
    )
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    atendimento_pet = serializers.SerializerMethodField()
    via_display = serializers.CharField(source="get_via_display", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    cancelada_por_username = serializers.SerializerMethodField()
    movimentacao_dados = serializers.SerializerMethodField()
    estorno_dados = serializers.SerializerMethodField()

    class Meta:
        model = AdministracaoMedicamento
        fields = [
            "id",
            "item_prescricao",
            "prescricao",
            "pet",
            "pet_nome",
            "produto",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
            "lote",
            "lote_numero",
            "lote_validade",
            "atendimento",
            "atendimento_pet",
            "profissional",
            "profissional_nome",
            "quantidade",
            "dose",
            "via",
            "via_display",
            "data_hora",
            "observacoes",
            "status",
            "status_display",
            "movimentacao",
            "movimentacao_dados",
            "estorno_movimentacao",
            "estorno_dados",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "cancelada_por_username",
            "chave_idempotencia",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "prescricao",
            "pet_nome",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
            "lote_numero",
            "lote_validade",
            "atendimento_pet",
            "profissional_nome",
            "via_display",
            "status",
            "status_display",
            "movimentacao",
            "movimentacao_dados",
            "estorno_movimentacao",
            "estorno_dados",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "cancelada_por_username",
            "created_at",
            "updated_at",
        ]

    def get_atendimento_pet(self, obj):
        return obj.atendimento.pet.nome if obj.atendimento_id else None

    def get_cancelada_por_username(self, obj):
        return obj.cancelada_por.username if obj.cancelada_por else ""

    def _dados_movimentacao(self, movimentacao):
        if movimentacao is None:
            return None
        return {
            "id": str(movimentacao.id),
            "tipo": movimentacao.tipo,
            "tipo_display": movimentacao.get_tipo_display(),
            "quantidade": str(movimentacao.quantidade),
            "saldo_anterior": str(movimentacao.saldo_anterior),
            "saldo_posterior": str(movimentacao.saldo_posterior),
            "motivo": movimentacao.motivo,
            "data_hora": movimentacao.data_hora,
        }

    def get_movimentacao_dados(self, obj):
        return self._dados_movimentacao(obj.movimentacao)

    def get_estorno_dados(self, obj):
        return self._dados_movimentacao(obj.estorno_movimentacao)

    def validate_quantidade(self, valor):
        if valor is None or valor <= 0:
            raise serializers.ValidationError(
                "Informe uma quantidade maior que zero."
            )
        return valor

    def create(self, validated_data):
        administracao, criada = services.registrar_administracao(
            usuario=usuario_autenticado(self.context),
            **validated_data,
        )
        administracao.criada_agora = criada
        return administracao
