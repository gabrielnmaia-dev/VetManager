"""Catálogo e execução de procedimentos veterinários.

O módulo separa claramente **planejamento** de **execução**:

* ``Procedimento`` é o catálogo reutilizável (nome, categoria, tipo, duração,
  materiais previstos e situação).
* ``ExecucaoProcedimento`` é o registro clínico de uma execução real, com
  animal, atendimento, responsável, equipe, resultado e intercorrências.
* ``MaterialUtilizadoProcedimento`` liga a execução ao estoque. Cada linha
  gera uma movimentação de consumo clínico; o cancelamento da execução gera
  devoluções e preserva o livro-razão imutável.

Procedimentos cirúrgicos são apenas uma classificação do catálogo. Não há
campos cirúrgicos avançados (técnica, anestesia etc.) neste módulo.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.atendimentos.models import Atendimento
from apps.base.models import BaseModel
from apps.estoque.models import Lote, MovimentacaoEstoque, Produto
from apps.pets.models import Pet
from apps.veterinarios.models import Profissional


class CategoriaProcedimento(BaseModel):
    """Agrupamento do catálogo (ex.: exames, curativos, cirurgias)."""

    nome = models.CharField(max_length=100, verbose_name="nome")
    descricao = models.TextField(blank=True, verbose_name="descrição")
    ativo = models.BooleanField(default=True, verbose_name="ativa")

    class Meta:
        ordering = ["nome"]
        verbose_name = "categoria de procedimento"
        verbose_name_plural = "categorias de procedimento"
        constraints = [
            models.UniqueConstraint(
                Lower("nome"),
                condition=Q(is_deleted=False),
                name="uniq_categoria_procedimento_nome_ativo",
            )
        ]

    def __str__(self) -> str:
        return self.nome


class Procedimento(BaseModel):
    """Item do catálogo de procedimentos veterinários."""

    class Tipo(models.TextChoices):
        AMBULATORIAL = "ambulatorial", "Ambulatorial"
        CLINICO = "clinico", "Clínico"
        CIRURGICO = "cirurgico", "Cirúrgico"

    nome = models.CharField(max_length=150, verbose_name="nome")
    categoria = models.ForeignKey(
        CategoriaProcedimento,
        on_delete=models.PROTECT,
        related_name="procedimentos",
        verbose_name="categoria",
    )
    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.AMBULATORIAL,
        db_index=True,
        verbose_name="tipo",
    )
    descricao = models.TextField(blank=True, verbose_name="descrição")
    duracao_estimada_minutos = models.PositiveIntegerField(
        default=0, verbose_name="duração estimada (minutos)"
    )
    ativo = models.BooleanField(default=True, db_index=True, verbose_name="ativo")

    class Meta:
        ordering = ["nome"]
        verbose_name = "procedimento"
        verbose_name_plural = "procedimentos"
        indexes = [
            models.Index(
                fields=["categoria", "ativo"], name="idx_proc_categoria_ativo"
            ),
            models.Index(fields=["tipo", "ativo"], name="idx_proc_tipo_ativo"),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("nome"),
                condition=Q(is_deleted=False),
                name="uniq_procedimento_nome_ativo",
            )
        ]

    def __str__(self) -> str:
        return self.nome


class MaterialPrevistoProcedimento(BaseModel):
    """Material ou medicamento previsto no catálogo do procedimento.

    É apenas um planejamento: não reserva nem baixa estoque. A baixa ocorre
    somente na execução, em ``MaterialUtilizadoProcedimento``.
    """

    procedimento = models.ForeignKey(
        Procedimento,
        on_delete=models.CASCADE,
        related_name="materiais_previstos",
        verbose_name="procedimento",
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="materiais_previstos_procedimento",
        verbose_name="produto",
    )
    quantidade_prevista = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=1,
        verbose_name="quantidade prevista",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["produto__nome"]
        verbose_name = "material previsto"
        verbose_name_plural = "materiais previstos"
        constraints = [
            models.UniqueConstraint(
                "procedimento",
                "produto",
                condition=Q(is_deleted=False),
                name="uniq_material_previsto_procedimento",
            )
        ]

    def __str__(self) -> str:
        return f"{self.produto.nome} — {self.procedimento.nome}"


class ExecucaoProcedimento(BaseModel):
    """Registro clínico de um procedimento efetivamente executado."""

    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        CANCELADA = "cancelada", "Cancelada"

    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="execucoes_procedimento",
        verbose_name="animal",
    )
    atendimento = models.ForeignKey(
        Atendimento,
        on_delete=models.PROTECT,
        related_name="execucoes_procedimento",
        verbose_name="atendimento",
    )
    procedimento = models.ForeignKey(
        Procedimento,
        on_delete=models.PROTECT,
        related_name="execucoes",
        verbose_name="procedimento",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="execucoes_procedimento",
        verbose_name="profissional responsável",
    )
    equipe = models.ManyToManyField(
        Profissional,
        blank=True,
        related_name="execucoes_como_equipe",
        verbose_name="equipe",
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    resultado = models.TextField(blank=True, verbose_name="resultado")
    intercorrencias = models.TextField(
        blank=True, verbose_name="intercorrências"
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ATIVA,
        db_index=True,
        verbose_name="situação",
    )
    motivo_cancelamento = models.CharField(
        max_length=255, blank=True, verbose_name="motivo do cancelamento"
    )
    cancelada_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="cancelada em"
    )
    cancelada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="cancelada por",
    )
    chave_idempotencia = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
        help_text=(
            "Evita duplicidade quando o mesmo registro é enviado duas vezes "
            "(ex.: duplo clique)."
        ),
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "execução de procedimento"
        verbose_name_plural = "execuções de procedimento"
        indexes = [
            models.Index(fields=["pet", "-data_hora"], name="idx_exec_pet_data"),
            models.Index(
                fields=["procedimento", "-data_hora"],
                name="idx_exec_proc_data",
            ),
            models.Index(
                fields=["profissional", "-data_hora"],
                name="idx_exec_prof_data",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.procedimento.nome} — {self.pet.nome} "
            f"({self.data_hora:%d/%m/%Y %H:%M})"
        )

    @property
    def cancelada(self) -> bool:
        return self.status == self.Status.CANCELADA


class MaterialUtilizadoProcedimento(BaseModel):
    """Material/medicamento consumido durante uma execução.

    Cada linha aponta para a movimentação de consumo clínico gerada e, em caso
    de cancelamento da execução, para a movimentação de devolução. O histórico
    original nunca é apagado.
    """

    execucao = models.ForeignKey(
        ExecucaoProcedimento,
        on_delete=models.CASCADE,
        related_name="materiais",
        verbose_name="execução",
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="materiais_utilizados_procedimento",
        verbose_name="produto",
    )
    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name="materiais_utilizados_procedimento",
        verbose_name="lote",
    )
    quantidade = models.DecimalField(
        max_digits=12, decimal_places=3, verbose_name="quantidade"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    movimentacao = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.SET_NULL,
        related_name="material_utilizado_procedimento",
        null=True,
        blank=True,
        editable=False,
        verbose_name="movimentação de consumo",
    )
    estorno_movimentacao = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.SET_NULL,
        related_name="estorno_material_procedimento",
        null=True,
        blank=True,
        editable=False,
        verbose_name="movimentação de estorno",
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name = "material utilizado"
        verbose_name_plural = "materiais utilizados"
        indexes = [
            models.Index(
                fields=["execucao", "produto"],
                name="idx_mat_util_exec_prod",
            )
        ]

    def __str__(self) -> str:
        return f"{self.produto.nome} — {self.quantidade}"
