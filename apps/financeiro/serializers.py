"""Serializers do módulo financeiro."""

from rest_framework import serializers

from apps.atendimentos.models import Atendimento
from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from apps.tutores.models import Tutor

from . import services
from .models import (
    AplicacaoPagamento,
    Caixa,
    ContaReceber,
    FormaPagamento,
    HistoricoContaReceber,
    MovimentacaoCaixa,
    Pagamento,
    ParcelaContaReceber,
)


class FormaPagamentoSerializer(AuthoredModelSerializer):
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    pagamentos_count = serializers.SerializerMethodField()

    class Meta:
        model = FormaPagamento
        fields = [
            "id",
            "nome",
            "tipo",
            "tipo_display",
            "ativo",
            "permite_parcelamento",
            "observacoes",
            "pagamentos_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tipo_display",
            "pagamentos_count",
            "created_at",
            "updated_at",
        ]

    def get_pagamentos_count(self, obj):
        return obj.pagamentos.count()

    def validate_nome(self, valor):
        valor = (valor or "").strip()
        if not valor:
            raise serializers.ValidationError("Informe o nome da forma de pagamento.")
        qs = FormaPagamento.objects.filter(nome__iexact=valor)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Já existe uma forma de pagamento com este nome."
            )
        return valor


class ParcelaContaReceberSerializer(AuthoredModelSerializer):
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    vencida = serializers.BooleanField(read_only=True)

    class Meta:
        model = ParcelaContaReceber
        fields = [
            "id",
            "conta",
            "numero",
            "vencimento",
            "valor",
            "valor_pago",
            "saldo",
            "status",
            "status_display",
            "vencida",
            "created_at",
        ]
        read_only_fields = fields


class HistoricoContaReceberSerializer(serializers.ModelSerializer):
    status_anterior_display = serializers.CharField(
        source="get_status_anterior_display", read_only=True
    )
    status_novo_display = serializers.CharField(
        source="get_status_novo_display", read_only=True
    )
    usuario_nome = serializers.SerializerMethodField()

    class Meta:
        model = HistoricoContaReceber
        fields = [
            "id",
            "status_anterior",
            "status_anterior_display",
            "status_novo",
            "status_novo_display",
            "valor_pago",
            "saldo",
            "usuario_nome",
            "observacao",
            "created_at",
        ]
        read_only_fields = fields

    def get_usuario_nome(self, obj):
        if obj.usuario_id is None:
            return None
        return obj.usuario.get_username()


class ContaReceberSerializer(AuthoredModelSerializer):
    tutor = serializers.PrimaryKeyRelatedField(
        queryset=Tutor.objects.filter(is_deleted=False), required=False
    )
    atendimento = serializers.PrimaryKeyRelatedField(
        queryset=Atendimento.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    tutor_nome = serializers.CharField(source="tutor.nome", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    status_efetivo = serializers.CharField(read_only=True)
    vencida = serializers.BooleanField(read_only=True)
    dias_atraso = serializers.IntegerField(read_only=True)
    parcelas = ParcelaContaReceberSerializer(many=True, read_only=True)
    historico = HistoricoContaReceberSerializer(many=True, read_only=True)
    numero_parcelas = serializers.IntegerField(
        write_only=True, required=False, default=1, min_value=1, max_value=60
    )
    parcelas_entrada = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False
    )
    vencimento = serializers.DateField(required=False)
    data_emissao = serializers.DateField(required=False)
    chave_idempotencia = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True
    )

    class Meta:
        model = ContaReceber
        fields = [
            "id",
            "tutor",
            "tutor_nome",
            "atendimento",
            "descricao",
            "valor",
            "data_emissao",
            "vencimento",
            "status",
            "status_display",
            "status_efetivo",
            "valor_pago",
            "saldo",
            "vencida",
            "dias_atraso",
            "observacoes",
            "motivo_cancelamento",
            "cancelado_em",
            "parcelas",
            "historico",
            "numero_parcelas",
            "parcelas_entrada",
            "chave_idempotencia",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tutor_nome",
            "status",
            "status_display",
            "status_efetivo",
            "valor_pago",
            "saldo",
            "vencida",
            "dias_atraso",
            "motivo_cancelamento",
            "cancelado_em",
            "parcelas",
            "historico",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        numero_parcelas = validated_data.pop("numero_parcelas", 1)
        parcelas_entrada = validated_data.pop("parcelas_entrada", None)
        return services.criar_conta_receber(
            dados=validated_data,
            numero_parcelas=numero_parcelas,
            parcelas_entrada=parcelas_entrada,
            usuario=usuario_autenticado(self.context),
        )


class AplicacaoPagamentoSerializer(serializers.ModelSerializer):
    parcela_numero = serializers.IntegerField(source="parcela.numero", read_only=True)

    class Meta:
        model = AplicacaoPagamento
        fields = ["id", "parcela", "parcela_numero", "valor"]
        read_only_fields = fields


class PagamentoSerializer(AuthoredModelSerializer):
    conta = serializers.PrimaryKeyRelatedField(
        queryset=ContaReceber.objects.filter(is_deleted=False)
    )
    parcela = serializers.PrimaryKeyRelatedField(
        queryset=ParcelaContaReceber.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    forma_pagamento = serializers.PrimaryKeyRelatedField(
        queryset=FormaPagamento.objects.filter(is_deleted=False, ativo=True)
    )
    caixa = serializers.PrimaryKeyRelatedField(
        queryset=Caixa.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    conta_descricao = serializers.CharField(
        source="conta.descricao", read_only=True
    )
    tutor_nome = serializers.CharField(source="conta.tutor.nome", read_only=True)
    forma_pagamento_nome = serializers.CharField(
        source="forma_pagamento.nome", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    aplicacoes = AplicacaoPagamentoSerializer(many=True, read_only=True)
    estornado_por_nome = serializers.SerializerMethodField()
    chave_idempotencia = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True
    )

    class Meta:
        model = Pagamento
        fields = [
            "id",
            "conta",
            "conta_descricao",
            "tutor_nome",
            "parcela",
            "forma_pagamento",
            "forma_pagamento_nome",
            "valor",
            "data_hora",
            "status",
            "status_display",
            "observacoes",
            "caixa",
            "estornado_em",
            "estornado_por_nome",
            "motivo_estorno",
            "aplicacoes",
            "chave_idempotencia",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "conta_descricao",
            "tutor_nome",
            "forma_pagamento_nome",
            "status",
            "status_display",
            "estornado_em",
            "estornado_por_nome",
            "motivo_estorno",
            "aplicacoes",
            "created_at",
        ]

    def get_estornado_por_nome(self, obj):
        if obj.estornado_por_id is None:
            return None
        return obj.estornado_por.get_username()

    def create(self, validated_data):
        conta = validated_data.pop("conta")
        caixa = validated_data.pop("caixa", None)
        return services.registrar_pagamento(
            conta_id=conta.pk,
            caixa=caixa,
            usuario=usuario_autenticado(self.context),
            **validated_data,
        )


class EstornoPagamentoSerializer(serializers.Serializer):
    motivo = serializers.CharField(max_length=255)


class FechamentoCaixaSerializer(serializers.Serializer):
    valor_fechamento_informado = serializers.DecimalField(
        max_digits=12, decimal_places=2
    )
    observacoes = serializers.CharField(required=False, allow_blank=True)


class CaixaSerializer(AuthoredModelSerializer):
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    usuario_abertura_nome = serializers.SerializerMethodField()
    usuario_fechamento_nome = serializers.SerializerMethodField()
    resumo = serializers.SerializerMethodField()
    chave_idempotencia = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True
    )

    class Meta:
        model = Caixa
        fields = [
            "id",
            "descricao",
            "status",
            "status_display",
            "data_abertura",
            "data_fechamento",
            "valor_abertura",
            "valor_fechamento_informado",
            "valor_fechamento_sistema",
            "diferenca",
            "usuario_abertura_nome",
            "usuario_fechamento_nome",
            "observacoes",
            "observacoes_fechamento",
            "resumo",
            "chave_idempotencia",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "data_abertura",
            "data_fechamento",
            "valor_fechamento_informado",
            "valor_fechamento_sistema",
            "diferenca",
            "usuario_abertura_nome",
            "usuario_fechamento_nome",
            "observacoes_fechamento",
            "resumo",
            "created_at",
            "updated_at",
        ]

    def get_usuario_abertura_nome(self, obj):
        if obj.usuario_abertura_id is None:
            return None
        return obj.usuario_abertura.get_username()

    def get_usuario_fechamento_nome(self, obj):
        if obj.usuario_fechamento_id is None:
            return None
        return obj.usuario_fechamento.get_username()

    def get_resumo(self, obj):
        return services.resumo_caixa(obj)

    def create(self, validated_data):
        return services.abrir_caixa(
            usuario=usuario_autenticado(self.context), **validated_data
        )


class MovimentacaoCaixaSerializer(AuthoredModelSerializer):
    caixa = serializers.PrimaryKeyRelatedField(
        queryset=Caixa.objects.filter(is_deleted=False)
    )
    forma_pagamento = serializers.PrimaryKeyRelatedField(
        queryset=FormaPagamento.objects.filter(is_deleted=False, ativo=True),
        required=False,
        allow_null=True,
    )
    caixa_descricao = serializers.CharField(
        source="caixa.descricao", read_only=True
    )
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    forma_pagamento_nome = serializers.CharField(
        source="forma_pagamento.nome", read_only=True
    )
    usuario_nome = serializers.SerializerMethodField()
    valor_assinado = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    chave_idempotencia = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True
    )

    class Meta:
        model = MovimentacaoCaixa
        fields = [
            "id",
            "caixa",
            "caixa_descricao",
            "tipo",
            "tipo_display",
            "valor",
            "valor_assinado",
            "descricao",
            "forma_pagamento",
            "forma_pagamento_nome",
            "pagamento",
            "data_hora",
            "usuario_nome",
            "chave_idempotencia",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "caixa_descricao",
            "tipo_display",
            "valor_assinado",
            "forma_pagamento_nome",
            "pagamento",
            "usuario_nome",
            "created_at",
        ]

    def get_usuario_nome(self, obj):
        if obj.created_by_id is None:
            return None
        return obj.created_by.get_username()

    def create(self, validated_data):
        caixa = validated_data.pop("caixa")
        return services.registrar_movimentacao_caixa(
            caixa_id=caixa.pk,
            usuario=usuario_autenticado(self.context),
            **validated_data,
        )
