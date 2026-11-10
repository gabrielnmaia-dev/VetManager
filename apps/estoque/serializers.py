"""Serializers do catálogo de produtos e categorias.

As validações de duplicidade são feitas aqui (mensagens amigáveis) e também no
banco (``UniqueConstraint``), evitando corrida entre duas requisições
simultâneas. Registros excluídos logicamente não bloqueiam o reaproveitamento
do mesmo código/nome.
"""

from rest_framework import serializers

from apps.base.serializers import AuthoredModelSerializer

from .models import CategoriaProduto, Produto


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
