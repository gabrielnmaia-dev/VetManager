"""Catálogo de produtos, medicamentos e categorias do estoque.

O catálogo é a base compartilhada pelos módulos de prescrição, administração
clínica, estoque, procedimentos e financeiro. Nenhum dado clínico é inventado:
princípio ativo, concentração, forma farmacêutica e unidade de dispensação são
informados pela clínica no cadastro de cada produto.

O catálogo distingue estoque **clínico** de estoque **comercial** desde o
produto. Assim, o consumo de um medicamento nunca se confunde com a venda de
um produto de prateleira, mesmo que os dois usem o mesmo cadastro básico.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

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
    estoque_minimo = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name="estoque mínimo",
        help_text="Saldo total a partir do qual o produto entra em alerta.",
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
                raise ValidationError(erros)


class Fornecedor(BaseModel):
    """Fornecedor de produtos e lotes."""

    nome = models.CharField(max_length=150, verbose_name="nome")
    razao_social = models.CharField(
        max_length=200, blank=True, verbose_name="razão social"
    )
    cnpj = models.CharField(max_length=18, blank=True, verbose_name="CNPJ")
    telefone = models.CharField(max_length=30, blank=True, verbose_name="telefone")
    email = models.EmailField(blank=True, verbose_name="e-mail")
    endereco = models.TextField(blank=True, verbose_name="endereço")
    observacoes = models.TextField(blank=True, verbose_name="observações")
    ativo = models.BooleanField(default=True, verbose_name="ativo")

    class Meta:
        ordering = ["nome"]
        verbose_name = "fornecedor"
        verbose_name_plural = "fornecedores"
        constraints = [
            models.UniqueConstraint(
                Lower("cnpj"),
                condition=Q(is_deleted=False) & ~Q(cnpj=""),
                name="uniq_fornecedor_cnpj_ativo",
            )
        ]

    def __str__(self) -> str:
        return self.nome


class Lote(BaseModel):
    """Lote físico de um produto, com saldo e rastreabilidade.

    ``quantidade_atual`` é mantida exclusivamente pelas movimentações
    (entradas, saídas, ajustes e inventários). Ela nunca é aceita em payloads
    da API para evitar divergência entre o saldo e o histórico.
    """

    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="lotes",
        verbose_name="produto",
    )
    numero_lote = models.CharField(max_length=80, verbose_name="número do lote")
    fabricante = models.CharField(
        max_length=120, blank=True, verbose_name="fabricante"
    )
    data_fabricacao = models.DateField(
        null=True, blank=True, verbose_name="data de fabricação"
    )
    data_validade = models.DateField(
        null=True, blank=True, verbose_name="validade"
    )
    quantidade_inicial = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name="quantidade inicial",
    )
    quantidade_atual = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        editable=False,
        verbose_name="quantidade atual",
    )
    custo_aquisicao = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="custo de aquisição",
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lotes",
        verbose_name="fornecedor",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["data_validade", "numero_lote"]
        verbose_name = "lote"
        verbose_name_plural = "lotes"
        indexes = [
            models.Index(
                fields=["produto", "data_validade"],
                name="idx_lote_produto_validade",
            ),
            models.Index(fields=["data_validade"], name="idx_lote_validade"),
        ]
        constraints = [
            models.UniqueConstraint(
                "produto",
                Lower("numero_lote"),
                condition=Q(is_deleted=False),
                name="uniq_lote_produto_numero_ativo",
            )
        ]

    def __str__(self) -> str:
        return f"{self.produto.nome} — lote {self.numero_lote}"

    @property
    def esta_vencido(self) -> bool:
        return bool(
            self.data_validade and self.data_validade < timezone.localdate()
        )

    @property
    def dias_para_vencer(self) -> int | None:
        if not self.data_validade:
            return None
        return (self.data_validade - timezone.localdate()).days

    @property
    def status_validade(self) -> str:
        """Classificação usada nos alertas e na interface."""
        if not self.data_validade:
            return "sem_validade"
        dias = self.dias_para_vencer
        if dias is not None and dias < 0:
            return "vencido"
        if dias is not None and dias <= 30:
            return "vencendo"
        return "ok"

    @property
    def valor_em_estoque(self):
        custo = self.custo_aquisicao or 0
        return (self.quantidade_atual or 0) * custo


class MovimentacaoEstoque(BaseModel):
    """Livro-razão imutável de toda alteração de saldo.

    Não há update nem delete: correções são feitas por uma nova movimentação
    de ajuste, preservando a trilha completa. O saldo anterior/posterior é
    gravado em cada linha para auditoria mesmo que o lote seja alterado depois.
    """

    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SAIDA = "saida", "Saída"
        CONSUMO_CLINICO = "consumo_clinico", "Consumo clínico"
        PERDA = "perda", "Perda"
        VENCIMENTO = "vencimento", "Vencimento"
        AJUSTE = "ajuste", "Ajuste"
        DEVOLUCAO = "devolucao", "Devolução"

    class Direcao(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SAIDA = "saida", "Saída"

    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="movimentacoes",
        verbose_name="produto",
    )
    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name="movimentacoes",
        verbose_name="lote",
    )
    tipo = models.CharField(
        max_length=30, choices=Tipo.choices, db_index=True, verbose_name="tipo"
    )
    direcao = models.CharField(
        max_length=10,
        choices=Direcao.choices,
        db_index=True,
        verbose_name="direção",
    )
    quantidade = models.DecimalField(
        max_digits=12, decimal_places=3, verbose_name="quantidade"
    )
    saldo_anterior = models.DecimalField(
        max_digits=12, decimal_places=3, verbose_name="saldo anterior"
    )
    saldo_posterior = models.DecimalField(
        max_digits=12, decimal_places=3, verbose_name="saldo posterior"
    )
    motivo = models.CharField(max_length=255, blank=True, verbose_name="motivo")
    atendimento = models.ForeignKey(
        "atendimentos.Atendimento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes_estoque",
        verbose_name="atendimento",
    )
    fornecedor = models.ForeignKey(
        Fornecedor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimentacoes",
        verbose_name="fornecedor",
    )
    custo_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="custo unitário",
    )
    documento_referencia = models.CharField(
        max_length=100, blank=True, verbose_name="documento de referência"
    )
    data_hora = models.DateTimeField(
        default=timezone.now, editable=False, db_index=True, verbose_name="data e hora"
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "movimentação de estoque"
        verbose_name_plural = "movimentações de estoque"
        indexes = [
            models.Index(
                fields=["produto", "-data_hora"], name="idx_mov_produto_data"
            ),
            models.Index(fields=["lote", "-data_hora"], name="idx_mov_lote_data"),
            models.Index(fields=["tipo", "-data_hora"], name="idx_mov_tipo_data"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.get_tipo_display()} — {self.produto.nome} "
            f"({self.quantidade})"
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "Movimentações de estoque são imutáveis. "
                "Registre um novo ajuste em vez de alterar o histórico."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Movimentações de estoque não podem ser excluídas. "
            "Registre um estorno por ajuste."
        )

    def soft_delete(self, user=None):
        raise ValidationError(
            "Movimentações de estoque não podem ser excluídas. "
            "Registre um estorno por ajuste."
        )

    def hard_delete(self, *args, **kwargs):
        raise ValidationError(
            "Movimentações de estoque não podem ser excluídas fisicamente."
        )

    def clean(self):
        super().clean()
        if self.direcao not in self.Direcao.values:
            raise ValidationError({"direcao": "Direção inválida."})
        if self.quantidade is None or self.quantidade <= 0:
            raise ValidationError({"quantidade": "A quantidade deve ser maior que zero."})


class Inventario(BaseModel):
    """Inventário de contagem física de um tipo de estoque."""

    class Status(models.TextChoices):
        ABERTO = "aberto", "Aberto"
        FINALIZADO = "finalizado", "Finalizado"
        CANCELADO = "cancelado", "Cancelado"

    tipo_estoque = models.CharField(
        max_length=20,
        choices=Produto.TipoEstoque.choices,
        default=Produto.TipoEstoque.CLINICO,
        db_index=True,
        verbose_name="tipo de estoque",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ABERTO,
        db_index=True,
        verbose_name="situação",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    iniciado_em = models.DateTimeField(
        default=timezone.now, editable=False, verbose_name="iniciado em"
    )
    finalizado_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="finalizado em"
    )
    finalizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="finalizado por",
    )

    class Meta:
        ordering = ["-iniciado_em"]
        verbose_name = "inventário"
        verbose_name_plural = "inventários"

    def __str__(self) -> str:
        return f"Inventário {self.get_tipo_estoque_display()} — {self.get_status_display()}"


class ItemInventario(BaseModel):
    """Contagem de um lote dentro de um inventário."""

    inventario = models.ForeignKey(
        Inventario,
        on_delete=models.CASCADE,
        related_name="itens",
        verbose_name="inventário",
    )
    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name="itens_inventario",
        verbose_name="lote",
    )
    quantidade_sistema = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name="quantidade no sistema",
    )
    quantidade_contada = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name="quantidade contada",
    )
    diferenca = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        editable=False,
        verbose_name="diferença",
    )
    movimentacao = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="item_inventario",
        verbose_name="movimentação de ajuste",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["lote__produto__nome", "lote__data_validade"]
        verbose_name = "item de inventário"
        verbose_name_plural = "itens de inventário"
        constraints = [
            models.UniqueConstraint(
                "inventario",
                "lote",
                condition=Q(is_deleted=False),
                name="uniq_item_inventario_lote_ativo",
            )
        ]

    def __str__(self) -> str:
        return f"{self.lote} — contado {self.quantidade_contada}"

    @property
    def produto(self):
        return self.lote.produto

    def save(self, *args, **kwargs):
        self.diferenca = (self.quantidade_contada or 0) - (
            self.quantidade_sistema or 0
        )
        return super().save(*args, **kwargs)
