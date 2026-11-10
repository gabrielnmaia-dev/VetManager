"""Serializers do catálogo e da execução de procedimentos."""

from rest_framework import serializers

from apps.atendimentos.models import Atendimento
from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from apps.estoque.models import Lote, Produto
from apps.pets.models import Pet
from apps.veterinarios.models import Profissional

from . import services
from .models import (
    CategoriaProcedimento,
    ExecucaoProcedimento,
    MaterialPrevistoProcedimento,
    MaterialUtilizadoProcedimento,
    Procedimento,
)


class CategoriaProcedimentoSerializer(AuthoredModelSerializer):
    procedimentos_count = serializers.SerializerMethodField()

    class Meta:
        model = CategoriaProcedimento
        fields = [
            "id",
            "nome",
            "descricao",
            "ativo",
            "procedimentos_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "procedimentos_count",
            "created_at",
            "updated_at",
        ]

    def get_procedimentos_count(self, obj):
        return obj.procedimentos.count()

    def validate_nome(self, valor):
        valor = (valor or "").strip()
        if not valor:
            raise serializers.ValidationError("Informe o nome da categoria.")
        qs = CategoriaProcedimento.objects.filter(nome__iexact=valor)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Já existe uma categoria com este nome.")
        return valor


class MaterialPrevistoProcedimentoSerializer(AuthoredModelSerializer):
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_codigo = serializers.CharField(
        source="produto.codigo_interno", read_only=True
    )
    unidade_dispensacao = serializers.CharField(
        source="produto.unidade_dispensacao", read_only=True
    )

    class Meta:
        model = MaterialPrevistoProcedimento
        fields = [
            "id",
            "produto",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
            "quantidade_prevista",
            "observacoes",
        ]
        read_only_fields = [
            "id",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
        ]


class ProcedimentoSerializer(AuthoredModelSerializer):
    categoria = serializers.PrimaryKeyRelatedField(
        queryset=CategoriaProcedimento.objects.filter(is_deleted=False)
    )
    categoria_nome = serializers.CharField(
        source="categoria.nome", read_only=True
    )
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    materiais_previstos = MaterialPrevistoProcedimentoSerializer(
        many=True, required=False
    )
    materiais_previstos_count = serializers.SerializerMethodField()
    execucoes_count = serializers.SerializerMethodField()

    class Meta:
        model = Procedimento
        fields = [
            "id",
            "nome",
            "categoria",
            "categoria_nome",
            "tipo",
            "tipo_display",
            "descricao",
            "duracao_estimada_minutos",
            "ativo",
            "materiais_previstos",
            "materiais_previstos_count",
            "execucoes_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "categoria_nome",
            "tipo_display",
            "materiais_previstos_count",
            "execucoes_count",
            "created_at",
            "updated_at",
        ]

    def get_materiais_previstos_count(self, obj):
        return obj.materiais_previstos.count()

    def get_execucoes_count(self, obj):
        return obj.execucoes.count()

    def validate_nome(self, valor):
        valor = (valor or "").strip()
        if not valor:
            raise serializers.ValidationError("Informe o nome do procedimento.")
        qs = Procedimento.objects.filter(nome__iexact=valor)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Já existe um procedimento com este nome."
            )
        return valor

    def create(self, validated_data):
        materiais = validated_data.pop("materiais_previstos", [])
        return services.salvar_procedimento(
            dados=validated_data,
            materiais=materiais,
            usuario=usuario_autenticado(self.context),
        )

    def update(self, instance, validated_data):
        materiais = validated_data.pop("materiais_previstos", None)
        return services.salvar_procedimento(
            dados=validated_data,
            materiais=materiais,
            procedimento=instance,
            usuario=usuario_autenticado(self.context),
        )


class MaterialUtilizadoProcedimentoSerializer(AuthoredModelSerializer):
    produto = serializers.PrimaryKeyRelatedField(
        queryset=Produto.objects.filter(is_deleted=False)
    )
    lote = serializers.PrimaryKeyRelatedField(
        queryset=Lote.objects.filter(is_deleted=False)
    )
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
    movimentacao_dados = serializers.SerializerMethodField()
    estorno_dados = serializers.SerializerMethodField()

    class Meta:
        model = MaterialUtilizadoProcedimento
        fields = [
            "id",
            "produto",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
            "lote",
            "lote_numero",
            "lote_validade",
            "quantidade",
            "observacoes",
            "movimentacao",
            "movimentacao_dados",
            "estorno_movimentacao",
            "estorno_dados",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
            "lote_numero",
            "lote_validade",
            "movimentacao",
            "movimentacao_dados",
            "estorno_movimentacao",
            "estorno_dados",
            "created_at",
        ]

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


class ExecucaoProcedimentoSerializer(AuthoredModelSerializer):
    atendimento = serializers.PrimaryKeyRelatedField(
        queryset=Atendimento.objects.filter(is_deleted=False)
    )
    pet = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    procedimento = serializers.PrimaryKeyRelatedField(
        queryset=Procedimento.objects.filter(is_deleted=False)
    )
    profissional = serializers.PrimaryKeyRelatedField(
        queryset=Profissional.objects.filter(is_deleted=False)
    )
    equipe = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Profissional.objects.filter(is_deleted=False),
        required=False,
    )
    materiais = MaterialUtilizadoProcedimentoSerializer(many=True, required=False)
    chave_idempotencia = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        write_only=True,
    )

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    procedimento_nome = serializers.CharField(
        source="procedimento.nome", read_only=True
    )
    procedimento_tipo = serializers.CharField(
        source="procedimento.tipo", read_only=True
    )
    procedimento_tipo_display = serializers.CharField(
        source="procedimento.get_tipo_display", read_only=True
    )
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    atendimento_data = serializers.DateTimeField(
        source="atendimento.data_hora_inicio", read_only=True
    )
    atendimento_tipo = serializers.CharField(
        source="atendimento.get_tipo_servico_display", read_only=True
    )
    equipe_detalhes = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    cancelada_por_username = serializers.SerializerMethodField()
    materiais_count = serializers.SerializerMethodField()

    class Meta:
        model = ExecucaoProcedimento
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor_nome",
            "atendimento",
            "atendimento_data",
            "atendimento_tipo",
            "procedimento",
            "procedimento_nome",
            "procedimento_tipo",
            "procedimento_tipo_display",
            "profissional",
            "profissional_nome",
            "equipe",
            "equipe_detalhes",
            "data_hora",
            "observacoes",
            "resultado",
            "intercorrencias",
            "materiais",
            "materiais_count",
            "status",
            "status_display",
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
            "pet_nome",
            "tutor_nome",
            "atendimento_data",
            "atendimento_tipo",
            "procedimento_nome",
            "procedimento_tipo",
            "procedimento_tipo_display",
            "profissional_nome",
            "equipe_detalhes",
            "materiais_count",
            "status",
            "status_display",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "cancelada_por_username",
            "created_at",
            "updated_at",
        ]

    def get_equipe_detalhes(self, obj):
        return [
            {"id": str(profissional.id), "nome": profissional.nome}
            for profissional in obj.equipe.all()
        ]

    def get_cancelada_por_username(self, obj):
        return obj.cancelada_por.username if obj.cancelada_por else ""

    def get_materiais_count(self, obj):
        return obj.materiais.count()

    def create(self, validated_data):
        materiais = validated_data.pop("materiais", [])
        execucao, criada = services.registrar_execucao(
            materiais=materiais,
            usuario=usuario_autenticado(self.context),
            **validated_data,
        )
        execucao.criada_agora = criada
        return execucao
