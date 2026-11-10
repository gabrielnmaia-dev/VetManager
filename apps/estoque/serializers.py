"""Serializers do catálogo de produtos e categorias.

As validações de duplicidade são feitas aqui (mensagens amigáveis) e também no
banco (``UniqueConstraint``), evitando corrida entre duas requisições
simultâneas. Registros excluídos logicamente não bloqueiam o reaproveitamento
do mesmo código/nome.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.atendimentos.models import Atendimento
from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado

from . import services
from .models import (
    CategoriaProduto,
    Fornecedor,
    Inventario,
    ItemInventario,
    Lote,
    MovimentacaoEstoque,
    Produto,
)


class CategoriaProdutoSerializer(AuthoredModelSerializer):
    """Categoria do catálogo com contagem de produtos ativos."""

    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    produtos_count = serializers.SerializerMethodField()

    class Meta:
        model = CategoriaProduto
        fields = [
            "id",
            "nome",
            "tipo",
            "tipo_display",
            "descricao",
            "ativo",
            "produtos_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "produtos_count"]

    def get_produtos_count(self, obj) -> int:
        return obj.produtos.filter(is_deleted=False).count()

    def validate_nome(self, value):
        nome = (value or "").strip()
        if not nome:
            raise serializers.ValidationError("Informe o nome da categoria.")
        qs = CategoriaProduto.objects.filter(nome__iexact=nome)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Já existe uma categoria com este nome."
            )
        return nome


class ProdutoSerializer(AuthoredModelSerializer):
    """Cadastro completo de produtos, incluindo campos de medicamento."""

    categoria_nome = serializers.CharField(source="categoria.nome", read_only=True)
    categoria_tipo = serializers.CharField(source="categoria.tipo", read_only=True)
    tipo_estoque_display = serializers.CharField(
        source="get_tipo_estoque_display", read_only=True
    )
    unidade_medida_display = serializers.CharField(
        source="get_unidade_medida_display", read_only=True
    )
    forma_farmaceutica_display = serializers.CharField(
        source="get_forma_farmaceutica_display", read_only=True
    )
    unidade_dispensacao_display = serializers.CharField(
        source="get_unidade_dispensacao_display", read_only=True
    )
    is_medicamento = serializers.BooleanField(read_only=True)

    codigo_interno = serializers.CharField(
        max_length=60,
        error_messages={
            "required": "Informe o código interno do produto.",
            "blank": "Informe o código interno do produto.",
        },
    )
    codigo_barras = serializers.CharField(
        max_length=80, required=False, allow_blank=True
    )
    nome = serializers.CharField(
        max_length=150,
        error_messages={
            "required": "Informe o nome do produto.",
            "blank": "Informe o nome do produto.",
        },
    )
    categoria = serializers.PrimaryKeyRelatedField(
        queryset=CategoriaProduto.objects.all(),
        error_messages={
            "required": "Informe a categoria do produto.",
            "null": "Informe a categoria do produto.",
            "does_not_exist": "Categoria não encontrada.",
            "incorrect_type": "Categoria inválida.",
        },
    )

    class Meta:
        model = Produto
        fields = [
            "id",
            "nome",
            "descricao",
            "categoria",
            "categoria_nome",
            "categoria_tipo",
            "fabricante",
            "apresentacao",
            "unidade_medida",
            "unidade_medida_display",
            "codigo_interno",
            "codigo_barras",
            "ativo",
            "tipo_estoque",
            "tipo_estoque_display",
            "estoque_minimo",
            "controla_estoque",
            "requer_receita",
            "principio_ativo",
            "concentracao",
            "forma_farmaceutica",
            "forma_farmaceutica_display",
            "unidade_dispensacao",
            "unidade_dispensacao_display",
            "is_medicamento",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "categoria_nome",
            "categoria_tipo",
            "tipo_estoque_display",
            "unidade_medida_display",
            "forma_farmaceutica_display",
            "unidade_dispensacao_display",
            "is_medicamento",
        ]

    def _valor_atual(self, attrs, campo):
        if campo in attrs:
            return attrs.get(campo)
        if self.instance is not None:
            return getattr(self.instance, campo)
        return ""

    def validate(self, attrs):
        # Normaliza textos para que a comparação/armazenamento seja estável.
        for campo in (
            "nome",
            "codigo_interno",
            "codigo_barras",
            "fabricante",
            "apresentacao",
            "principio_ativo",
            "concentracao",
        ):
            if campo in attrs and attrs[campo] is not None:
                attrs[campo] = attrs[campo].strip()

        categoria = attrs.get("categoria") or getattr(
            self.instance, "categoria", None
        )
        if categoria is None:
            raise serializers.ValidationError(
                {"categoria": ["Informe a categoria do produto."]}
            )

        # A categoria precisa estar ativa no momento do cadastro. Na edição,
        # aceita-se manter a categoria atual mesmo que tenha sido inativada
        # depois, mas não trocar para outra categoria inativa.
        categoria_atual = getattr(self.instance, "categoria_id", None)
        if not categoria.ativo and categoria.pk != categoria_atual:
            raise serializers.ValidationError(
                {"categoria": ["Não é possível cadastrar produto em categoria inativa."]}
            )

        codigo_interno = attrs.get("codigo_interno")
        if codigo_interno:
            qs = Produto.objects.filter(codigo_interno__iexact=codigo_interno)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"codigo_interno": ["Já existe um produto com este código interno."]}
                )

        codigo_barras = self._valor_atual(attrs, "codigo_barras") or ""
        if codigo_barras:
            qs = Produto.objects.filter(codigo_barras__iexact=codigo_barras)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"codigo_barras": ["Já existe um produto com este código de barras."]}
                )

        estoque_minimo = attrs.get("estoque_minimo")
        if estoque_minimo is not None and estoque_minimo < 0:
            raise serializers.ValidationError(
                {"estoque_minimo": ["O estoque mínimo não pode ser negativo."]}
            )

        if categoria.tipo == CategoriaProduto.Tipo.MEDICAMENTO:
            obrigatorios = {
                "principio_ativo": "Informe o princípio ativo do medicamento.",
                "concentracao": "Informe a concentração do medicamento.",
                "forma_farmaceutica": "Informe a forma farmacêutica do medicamento.",
                "unidade_dispensacao": "Informe a unidade de dispensação do medicamento.",
            }
            erros = {}
            for campo, mensagem in obrigatorios.items():
                valor = self._valor_atual(attrs, campo)
                if not str(valor or "").strip():
                    erros[campo] = [mensagem]
            if erros:
                raise serializers.ValidationError(erros)

        return attrs


class FornecedorSerializer(AuthoredModelSerializer):
    """Cadastro de fornecedores usados nas entradas de estoque."""

    class Meta:
        model = Fornecedor
        fields = [
            "id",
            "nome",
            "razao_social",
            "cnpj",
            "telefone",
            "email",
            "endereco",
            "observacoes",
            "ativo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_cnpj(self, value):
        cnpj = (value or "").strip()
        if not cnpj:
            return ""
        qs = Fornecedor.objects.filter(cnpj__iexact=cnpj)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Já existe um fornecedor com este CNPJ."
            )
        return cnpj


class LoteSerializer(AuthoredModelSerializer):
    """Lote com saldo controlado por movimentações."""

    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_codigo = serializers.CharField(
        source="produto.codigo_interno", read_only=True
    )
    produto_tipo_estoque = serializers.CharField(
        source="produto.tipo_estoque", read_only=True
    )
    fornecedor_nome = serializers.CharField(
        source="fornecedor.nome", read_only=True, allow_null=True
    )
    status_validade = serializers.CharField(read_only=True)
    dias_para_vencer = serializers.IntegerField(read_only=True, allow_null=True)
    esta_vencido = serializers.BooleanField(read_only=True)
    valor_em_estoque = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True
    )

    class Meta:
        model = Lote
        fields = [
            "id",
            "produto",
            "produto_nome",
            "produto_codigo",
            "produto_tipo_estoque",
            "numero_lote",
            "fabricante",
            "data_fabricacao",
            "data_validade",
            "quantidade_inicial",
            "quantidade_atual",
            "custo_aquisicao",
            "fornecedor",
            "fornecedor_nome",
            "observacoes",
            "status_validade",
            "dias_para_vencer",
            "esta_vencido",
            "valor_em_estoque",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "quantidade_atual",
            "status_validade",
            "dias_para_vencer",
            "esta_vencido",
            "valor_em_estoque",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        numero = attrs.get("numero_lote")
        if numero is not None:
            numero = numero.strip()
            attrs["numero_lote"] = numero
            if not numero:
                raise serializers.ValidationError(
                    {"numero_lote": ["Informe o número do lote."]}
                )

        produto = attrs.get("produto") or getattr(self.instance, "produto", None)
        numero_atual = numero or getattr(self.instance, "numero_lote", "")

        if self.instance is not None:
            if "produto" in attrs and attrs["produto"].pk != self.instance.produto_id:
                raise serializers.ValidationError(
                    {"produto": ["O produto do lote não pode ser alterado."]}
                )
            if (
                "numero_lote" in attrs
                and numero.lower() != self.instance.numero_lote.lower()
            ):
                raise serializers.ValidationError(
                    {"numero_lote": ["O número do lote não pode ser alterado."]}
                )
            if (
                "quantidade_inicial" in attrs
                and attrs["quantidade_inicial"] != self.instance.quantidade_inicial
            ):
                raise serializers.ValidationError(
                    {
                        "quantidade_inicial": [
                            "A quantidade inicial não pode ser alterada. "
                            "Use uma entrada ou ajuste de estoque."
                        ]
                    }
                )

        data_fabricacao = attrs.get(
            "data_fabricacao", getattr(self.instance, "data_fabricacao", None)
        )
        data_validade = attrs.get(
            "data_validade", getattr(self.instance, "data_validade", None)
        )
        if data_fabricacao and data_validade and data_fabricacao > data_validade:
            raise serializers.ValidationError(
                {
                    "data_fabricacao": [
                        "A data de fabricação não pode ser posterior à validade."
                    ]
                }
            )

        if produto and numero_atual:
            qs = Lote.objects.filter(
                produto=produto, numero_lote__iexact=numero_atual
            )
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"numero_lote": ["Já existe um lote com este número para o produto."]}
                )
        return attrs

    def create(self, validated_data):
        return services.criar_lote(
            usuario=usuario_autenticado(self.context), **validated_data
        )


class MovimentacaoEstoqueSerializer(serializers.ModelSerializer):
    """Leitura do livro-razão de estoque (nunca editável pela API)."""

    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_codigo = serializers.CharField(
        source="produto.codigo_interno", read_only=True
    )
    tipo_estoque = serializers.CharField(
        source="produto.tipo_estoque", read_only=True
    )
    lote_numero = serializers.CharField(
        source="lote.numero_lote", read_only=True
    )
    fornecedor_nome = serializers.CharField(
        source="fornecedor.nome", read_only=True, allow_null=True
    )
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    direcao_display = serializers.CharField(
        source="get_direcao_display", read_only=True
    )
    usuario_username = serializers.SerializerMethodField()
    atendimento_pet = serializers.SerializerMethodField()

    class Meta:
        model = MovimentacaoEstoque
        fields = [
            "id",
            "produto",
            "produto_nome",
            "produto_codigo",
            "tipo_estoque",
            "lote",
            "lote_numero",
            "tipo",
            "tipo_display",
            "direcao",
            "direcao_display",
            "quantidade",
            "saldo_anterior",
            "saldo_posterior",
            "motivo",
            "atendimento",
            "atendimento_pet",
            "fornecedor",
            "fornecedor_nome",
            "custo_unitario",
            "documento_referencia",
            "usuario_username",
            "data_hora",
            "created_at",
        ]
        read_only_fields = [field for field in fields]

    def get_usuario_username(self, obj):
        return obj.created_by.username if obj.created_by else ""

    def get_atendimento_pet(self, obj):
        if not obj.atendimento_id:
            return None
        return obj.atendimento.pet.nome


class EntradaEstoqueSerializer(serializers.Serializer):
    produto = serializers.PrimaryKeyRelatedField(
        queryset=Produto.objects.filter(is_deleted=False, controla_estoque=True)
    )
    lote = serializers.PrimaryKeyRelatedField(
        queryset=Lote.objects.filter(is_deleted=False)
    )
    quantidade = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001")
    )
    motivo = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="Entrada de estoque"
    )
    fornecedor = serializers.PrimaryKeyRelatedField(
        queryset=Fornecedor.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    custo_unitario = serializers.DecimalField(
        max_digits=12, decimal_places=4, required=False, allow_null=True
    )
    documento_referencia = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )

    def validate(self, attrs):
        if attrs["lote"].produto_id != attrs["produto"].pk:
            raise serializers.ValidationError(
                {"lote": ["O lote informado não pertence ao produto selecionado."]}
            )
        return attrs


class SaidaEstoqueSerializer(serializers.Serializer):
    TIPOS = (
        MovimentacaoEstoque.Tipo.SAIDA,
        MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
        MovimentacaoEstoque.Tipo.PERDA,
        MovimentacaoEstoque.Tipo.VENCIMENTO,
    )

    produto = serializers.PrimaryKeyRelatedField(
        queryset=Produto.objects.filter(is_deleted=False, controla_estoque=True)
    )
    lote = serializers.PrimaryKeyRelatedField(
        queryset=Lote.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    tipo = serializers.ChoiceField(choices=TIPOS, default=MovimentacaoEstoque.Tipo.SAIDA)
    quantidade = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001")
    )
    motivo = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default="Saída de estoque"
    )
    atendimento = serializers.PrimaryKeyRelatedField(
        queryset=Atendimento.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    documento_referencia = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )

    def validate(self, attrs):
        lote = attrs.get("lote")
        if lote is not None and lote.produto_id != attrs["produto"].pk:
            raise serializers.ValidationError(
                {"lote": ["O lote informado não pertence ao produto selecionado."]}
            )
        return attrs


class AjusteEstoqueSerializer(serializers.Serializer):
    produto = serializers.PrimaryKeyRelatedField(
        queryset=Produto.objects.filter(is_deleted=False, controla_estoque=True)
    )
    lote = serializers.PrimaryKeyRelatedField(
        queryset=Lote.objects.filter(is_deleted=False)
    )
    quantidade = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0.001")
    )
    direcao = serializers.ChoiceField(choices=MovimentacaoEstoque.Direcao.choices)
    motivo = serializers.CharField(max_length=255)

    def validate(self, attrs):
        if attrs["lote"].produto_id != attrs["produto"].pk:
            raise serializers.ValidationError(
                {"lote": ["O lote informado não pertence ao produto selecionado."]}
            )
        return attrs


class ItemInventarioSerializer(AuthoredModelSerializer):
    lote_numero = serializers.CharField(source="lote.numero_lote", read_only=True)
    produto = serializers.SerializerMethodField()
    produto_nome = serializers.CharField(
        source="lote.produto.nome", read_only=True
    )
    produto_codigo = serializers.CharField(
        source="lote.produto.codigo_interno", read_only=True
    )
    data_validade = serializers.DateField(
        source="lote.data_validade", read_only=True
    )

    class Meta:
        model = ItemInventario
        fields = [
            "id",
            "inventario",
            "lote",
            "lote_numero",
            "produto",
            "produto_nome",
            "produto_codigo",
            "data_validade",
            "quantidade_sistema",
            "quantidade_contada",
            "diferenca",
            "movimentacao",
            "observacoes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "produto",
            "produto_nome",
            "produto_codigo",
            "data_validade",
            "lote_numero",
            "quantidade_sistema",
            "diferenca",
            "movimentacao",
            "created_at",
            "updated_at",
        ]

    def get_produto(self, obj):
        return str(obj.lote.produto_id)

    def validate(self, attrs):
        inventario = attrs.get("inventario") or getattr(
            self.instance, "inventario", None
        )
        lote = attrs.get("lote") or getattr(self.instance, "lote", None)
        if inventario is None:
            raise serializers.ValidationError(
                {"inventario": ["Informe o inventário."]}
            )
        if inventario.status != Inventario.Status.ABERTO:
            raise serializers.ValidationError(
                {"inventario": ["Este inventário não está aberto."]}
            )
        if lote is None:
            raise serializers.ValidationError({"lote": ["Informe o lote."]})

        if self.instance is not None:
            if "inventario" in attrs and attrs["inventario"].pk != self.instance.inventario_id:
                raise serializers.ValidationError(
                    {"inventario": ["O inventário do item não pode ser alterado."]}
                )
            if "lote" in attrs and attrs["lote"].pk != self.instance.lote_id:
                raise serializers.ValidationError(
                    {"lote": ["O lote do item não pode ser alterado."]}
                )
        else:
            if lote.produto.tipo_estoque != inventario.tipo_estoque:
                raise serializers.ValidationError(
                    {
                        "lote": [
                            "O lote pertence a um produto de outro tipo de estoque."
                        ]
                    }
                )
            if not lote.produto.controla_estoque:
                raise serializers.ValidationError(
                    {"lote": ["Este produto não controla estoque."]}
                )
            if ItemInventario.objects.filter(
                inventario=inventario, lote=lote
            ).exists():
                raise serializers.ValidationError(
                    {"lote": ["Este lote já faz parte do inventário."]}
                )
        return attrs

    def create(self, validated_data):
        lote = validated_data["lote"]
        validated_data["quantidade_sistema"] = lote.quantidade_atual or 0
        validated_data.setdefault(
            "quantidade_contada", lote.quantidade_atual or 0
        )
        return super().create(validated_data)


class InventarioSerializer(AuthoredModelSerializer):
    tipo_estoque_display = serializers.CharField(
        source="get_tipo_estoque_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    finalizado_por_username = serializers.SerializerMethodField()
    itens_count = serializers.SerializerMethodField()
    diferencas_count = serializers.SerializerMethodField()

    class Meta:
        model = Inventario
        fields = [
            "id",
            "tipo_estoque",
            "tipo_estoque_display",
            "status",
            "status_display",
            "observacoes",
            "iniciado_em",
            "finalizado_em",
            "finalizado_por",
            "finalizado_por_username",
            "itens_count",
            "diferencas_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "iniciado_em",
            "finalizado_em",
            "finalizado_por",
            "finalizado_por_username",
            "itens_count",
            "diferencas_count",
            "created_at",
            "updated_at",
        ]

    def get_finalizado_por_username(self, obj):
        return obj.finalizado_por.username if obj.finalizado_por else ""

    def get_itens_count(self, obj) -> int:
        return obj.itens.filter(is_deleted=False).count()

    def get_diferencas_count(self, obj) -> int:
        return (
            obj.itens.filter(is_deleted=False)
            .exclude(diferenca=0)
            .count()
        )

    def validate(self, attrs):
        if self.instance is not None and self.instance.status != Inventario.Status.ABERTO:
            raise serializers.ValidationError(
                {"detail": "Somente inventários abertos podem ser alterados."}
            )
        return attrs

    def create(self, validated_data):
        return services.abrir_inventario(
            usuario=usuario_autenticado(self.context), **validated_data
        )
