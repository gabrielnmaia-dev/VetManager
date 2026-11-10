"""Catálogo de produtos, medicamentos e categorias do estoque.

O catálogo é a base compartilhada pelos módulos de prescrição, administração
clínica, estoque, procedimentos e financeiro. Nenhum dado clínico é inventado:
princípio ativo, concentração, forma farmacêutica e unidade de dispensação são
informados pela clínica no cadastro de cada produto.

O catálogo distingue estoque **clínico** de estoque **comercial** desde o
produto. Assim, o consumo de um medicamento nunca se confunde com a venda de
um produto de prateleira, mesmo que os dois usem o mesmo cadastro básico.
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.base.models import BaseModel


class CategoriaProduto(BaseModel):
    """Categoria do catálogo (medicamentos, materiais, vacinas etc.).

    O ``tipo`` é o que permite ao restante do sistema saber se um produto é
    medicamento (e, portanto, exige os campos farmacêuticos) sem depender do
    nome livre escolhido pela clínica.
    """

    class Tipo(models.TextChoices):
        MEDICAMENTO = "medicamento", "Medicamento"
        MATERIAL_CLINICO = "material_clinico", "Material clínico"
        VACINA = "vacina", "Vacina"
        CONSUMO = "consumo", "Produto de consumo"
        COMERCIAL = "comercial", "Produto comercial"

    nome = models.CharField(max_length=100, verbose_name="nome")
    tipo = models.CharField(
        max_length=30,
        choices=Tipo.choices,
        default=Tipo.MEDICAMENTO,
        verbose_name="tipo",
    )
    descricao = models.TextField(blank=True, verbose_name="descrição")
    ativo = models.BooleanField(default=True, verbose_name="ativa")

    class Meta:
        ordering = ["nome"]
        verbose_name = "categoria de produto"
        verbose_name_plural = "categorias de produto"
        constraints = [
            models.UniqueConstraint(
                Lower("nome"),
                condition=Q(is_deleted=False),
                name="uniq_categoria_produto_nome_ativo",
            )
        ]

    def __str__(self) -> str:
        return self.nome


class Produto(BaseModel):
    """Produto do catálogo, com campos farmacêuticos condicionais.

    Os campos de medicamento só são exigidos quando a categoria é do tipo
    ``medicamento``. Para materiais, vacinas e produtos comerciais eles ficam
    opcionais — a clínica pode preenchê-los quando fizer sentido.
    """

    class TipoEstoque(models.TextChoices):
        CLINICO = "clinico", "Clínico"
        COMERCIAL = "comercial", "Comercial"

    class UnidadeMedida(models.TextChoices):
        UNIDADE = "unidade", "Unidade"
        CAIXA = "caixa", "Caixa"
        PACOTE = "pacote", "Pacote"
        FRASCO = "frasco", "Frasco"
        AMPOLA = "ampola", "Ampola"
        COMPRIMIDO = "comprimido", "Comprimido"
        CAPSULA = "capsula", "Cápsula"
        TUBO = "tubo", "Tubo"
        BISNAGA = "bisnaga", "Bisnaga"
        ML = "ml", "Mililitro (ml)"
        L = "l", "Litro (l)"
        MG = "mg", "Miligrama (mg)"
        G = "g", "Grama (g)"
        KG = "kg", "Quilograma (kg)"
        OUTRA = "outra", "Outra"

    class FormaFarmaceutica(models.TextChoices):
        COMPRIMIDO = "comprimido", "Comprimido"
        CAPSULA = "capsula", "Cápsula"
        SOLUCAO = "solucao", "Solução"
        SUSPENSAO = "suspensao", "Suspensão"
        EMULSAO = "emulsao", "Emulsão"
        POMADA = "pomada", "Pomada"
        CREME = "creme", "Creme"
        GEL = "gel", "Gel"
        GOTAS = "gotas", "Gotas"
        SPRAY = "spray", "Spray"
        INJETAVEL = "injetavel", "Injetável"
        PO = "po", "Pó"
        OUTRA = "outra", "Outra"

    class UnidadeDispensacao(models.TextChoices):
        UNIDADE = "unidade", "Unidade"
        COMPRIMIDO = "comprimido", "Comprimido"
        CAPSULA = "capsula", "Cápsula"
        ML = "ml", "Mililitro (ml)"
        MG = "mg", "Miligrama (mg)"
        G = "g", "Grama (g)"
        FRASCO = "frasco", "Frasco"
        AMPOLA = "ampola", "Ampola"
        DOSE = "dose", "Dose"
        APLICACAO = "aplicacao", "Aplicação"
        OUTRA = "outra", "Outra"

    nome = models.CharField(max_length=150, verbose_name="nome")
    descricao = models.TextField(blank=True, verbose_name="descrição")
    categoria = models.ForeignKey(
        CategoriaProduto,
        on_delete=models.PROTECT,
        related_name="produtos",
        verbose_name="categoria",
    )
    fabricante = models.CharField(
        max_length=120, blank=True, verbose_name="fabricante"
    )
    apresentacao = models.CharField(
        max_length=150,
        blank=True,
        verbose_name="apresentação",
        help_text="Ex.: caixa com 10 comprimidos, frasco de 100 ml.",
    )
    unidade_medida = models.CharField(
        max_length=20,
        choices=UnidadeMedida.choices,
        default=UnidadeMedida.UNIDADE,
        verbose_name="unidade de medida",
    )
    codigo_interno = models.CharField(
        max_length=60, verbose_name="código interno"
    )
    codigo_barras = models.CharField(
        max_length=80, blank=True, verbose_name="código de barras"
    )
    ativo = models.BooleanField(default=True, verbose_name="ativo")
    tipo_estoque = models.CharField(
        max_length=20,
        choices=TipoEstoque.choices,
        default=TipoEstoque.CLINICO,
        db_index=True,
        verbose_name="tipo de estoque",
    )
    controla_estoque = models.BooleanField(
        default=True,
        verbose_name="controla estoque",
        help_text="Desmarque para itens que não passam por saldo/lote.",
    )
    requer_receita = models.BooleanField(
        default=False,
        verbose_name="requer receita",
        help_text="Usado pelas telas de prescrição para sinalizar o item.",
    )

    # --- Campos de medicamento (preenchidos pela clínica) ---
    principio_ativo = models.CharField(
        max_length=150, blank=True, verbose_name="princípio ativo"
    )
    concentracao = models.CharField(
        max_length=60, blank=True, verbose_name="concentração"
    )
    forma_farmaceutica = models.CharField(
        max_length=30,
        choices=FormaFarmaceutica.choices,
        blank=True,
        verbose_name="forma farmacêutica",
    )
    unidade_dispensacao = models.CharField(
        max_length=20,
        choices=UnidadeDispensacao.choices,
        blank=True,
        verbose_name="unidade de dispensação",
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "produto"
        verbose_name_plural = "produtos"
        indexes = [
            models.Index(fields=["nome"], name="idx_produto_nome"),
            models.Index(
                fields=["categoria", "ativo"], name="idx_produto_categoria_ativo"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("codigo_interno"),
                condition=Q(is_deleted=False),
                name="uniq_produto_codigo_interno_ativo",
            ),
            models.UniqueConstraint(
                Lower("codigo_barras"),
                condition=Q(is_deleted=False) & ~Q(codigo_barras=""),
                name="uniq_produto_codigo_barras_ativo",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.nome} ({self.codigo_interno})"

    @property
    def is_medicamento(self) -> bool:
        return self.categoria_id is not None and (
            self.categoria.tipo == CategoriaProduto.Tipo.MEDICAMENTO
        )

    @property
    def eh_comercial(self) -> bool:
        return self.tipo_estoque == self.TipoEstoque.COMERCIAL

    def clean(self):
        """Garante os campos farmacêuticos quando a categoria é medicamento.

        A mesma regra existe no serializer (com mensagens amigáveis) e aqui
        para proteger gravações feitas fora da API (admin, scripts, testes).
        """
        super().clean()
        if self.is_medicamento:
            obrigatorios = {
                "principio_ativo": "Informe o princípio ativo do medicamento.",
                "concentracao": "Informe a concentração do medicamento.",
                "forma_farmaceutica": "Informe a forma farmacêutica.",
                "unidade_dispensacao": "Informe a unidade de dispensação.",
            }
            erros = {}
            for campo, mensagem in obrigatorios.items():
                valor = getattr(self, campo, "")
                if not str(valor or "").strip():
                    erros[campo] = mensagem
            if erros:
                from django.core.exceptions import ValidationError

                raise ValidationError(erros)
