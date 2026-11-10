"""Modelos financeiros: contas a receber, pagamentos e caixa.

Princípios de integridade:

* ``ContaReceber`` é o lançamento financeiro e possui uma ou mais parcelas.
* ``Pagamento`` nunca é apagado: estornos mudam o status e geram aplicações
  inversas, preservando a trilha contábil.
* ``ParcelaContaReceber`` guarda o saldo devedor de cada vencimento.
* ``MovimentacaoCaixa`` é o livro-razão do caixa; entradas e saídas geradas
  por pagamentos ficam vinculadas ao pagamento original.
* Toda operação sensível é transacional e idempotente por chave.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.atendimentos.models import Atendimento
from apps.base.models import BaseModel
from apps.tutores.models import Tutor


class FormaPagamento(BaseModel):
    """Forma de pagamento configurável (dinheiro, Pix, cartão etc.)."""

    class Tipo(models.TextChoices):
        DINHEIRO = "dinheiro", "Dinheiro"
        PIX = "pix", "Pix"
        CARTAO_CREDITO = "cartao_credito", "Cartão de crédito"
        CARTAO_DEBITO = "cartao_debito", "Cartão de débito"
        TRANSFERENCIA = "transferencia", "Transferência"
        CHEQUE = "cheque", "Cheque"
        OUTROS = "outros", "Outros"

    nome = models.CharField(max_length=80, verbose_name="nome")
    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.OUTROS,
        db_index=True,
        verbose_name="tipo",
    )
    ativo = models.BooleanField(default=True, db_index=True, verbose_name="ativa")
    permite_parcelamento = models.BooleanField(
        default=False, verbose_name="permite parcelamento"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["nome"]
        verbose_name = "forma de pagamento"
        verbose_name_plural = "formas de pagamento"
        constraints = [
            models.UniqueConstraint(
                Lower("nome"),
                condition=Q(is_deleted=False),
                name="uniq_forma_pagamento_nome_ativa",
            )
        ]

    def __str__(self) -> str:
        return self.nome


class ContaReceber(BaseModel):
    """Lançamento de conta a receber, com parcelas e histórico."""

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        PARCIAL = "parcial", "Parcialmente paga"
        PAGA = "paga", "Paga"
        CANCELADA = "cancelada", "Cancelada"

    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="contas_receber",
        verbose_name="tutor",
    )
    atendimento = models.ForeignKey(
        Atendimento,
        on_delete=models.SET_NULL,
        related_name="contas_receber",
        null=True,
        blank=True,
        verbose_name="atendimento relacionado",
    )
    descricao = models.CharField(max_length=255, verbose_name="descrição")
    valor = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor"
    )
    data_emissao = models.DateField(
        default=timezone.localdate, db_index=True, verbose_name="data de emissão"
    )
    vencimento = models.DateField(db_index=True, verbose_name="vencimento")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ABERTA,
        db_index=True,
        verbose_name="situação",
    )
    valor_pago = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="valor pago",
    )
    saldo = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="saldo",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    cancelado_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="cancelado em"
    )
    motivo_cancelamento = models.CharField(
        max_length=255, blank=True, verbose_name="motivo do cancelamento"
    )
    cancelado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="cancelado por",
    )
    chave_idempotencia = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
    )

    class Meta:
        ordering = ["-data_emissao", "-created_at"]
        verbose_name = "conta a receber"
        verbose_name_plural = "contas a receber"
        indexes = [
            models.Index(
                fields=["status", "vencimento"], name="idx_conta_status_venc"
            ),
            models.Index(
                fields=["tutor", "status"], name="idx_conta_tutor_status"
            ),
            models.Index(
                fields=["atendimento", "status"], name="idx_conta_atend_status"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.descricao} — {self.tutor.nome}"

    @property
    def vencida(self) -> bool:
        return (
            self.status in {self.Status.ABERTA, self.Status.PARCIAL}
            and self.saldo > 0
            and self.vencimento < timezone.localdate()
        )

    @property
    def dias_atraso(self) -> int:
        if not self.vencida:
            return 0
        return (timezone.localdate() - self.vencimento).days

    @property
    def status_efetivo(self) -> str:
        return "vencida" if self.vencida else self.status


class ParcelaContaReceber(BaseModel):
    """Parcela/vencimento individual de uma conta a receber."""

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        PARCIAL = "parcial", "Parcialmente paga"
        PAGA = "paga", "Paga"
        CANCELADA = "cancelada", "Cancelada"

    conta = models.ForeignKey(
        ContaReceber,
        on_delete=models.CASCADE,
        related_name="parcelas",
        verbose_name="conta a receber",
    )
    numero = models.PositiveIntegerField(verbose_name="número")
    vencimento = models.DateField(db_index=True, verbose_name="vencimento")
    valor = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor"
    )
    valor_pago = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="valor pago",
    )
    saldo = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="saldo",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ABERTA,
        db_index=True,
        verbose_name="situação",
    )

    class Meta:
        ordering = ["numero"]
        verbose_name = "parcela de conta a receber"
        verbose_name_plural = "parcelas de conta a receber"
        constraints = [
            models.UniqueConstraint(
                "conta",
                "numero",
                condition=Q(is_deleted=False),
                name="uniq_parcela_conta_numero",
            )
        ]
        indexes = [
            models.Index(
                fields=["conta", "vencimento"], name="idx_parc_conta_venc"
            ),
            models.Index(
                fields=["status", "vencimento"], name="idx_parc_status_venc"
            ),
        ]

    def __str__(self) -> str:
        return f"Parcela {self.numero} — {self.conta.descricao}"

    @property
    def vencida(self) -> bool:
        return (
            self.status in {self.Status.ABERTA, self.Status.PARCIAL}
            and self.saldo > 0
            and self.vencimento < timezone.localdate()
        )


class Pagamento(BaseModel):
    """Pagamento confirmado ou estornado de uma conta a receber."""

    class Status(models.TextChoices):
        CONFIRMADO = "confirmado", "Confirmado"
        ESTORNADO = "estornado", "Estornado"

    conta = models.ForeignKey(
        ContaReceber,
        on_delete=models.PROTECT,
        related_name="pagamentos",
        verbose_name="conta a receber",
    )
    parcela = models.ForeignKey(
        ParcelaContaReceber,
        on_delete=models.PROTECT,
        related_name="pagamentos",
        null=True,
        blank=True,
        verbose_name="parcela",
    )
    forma_pagamento = models.ForeignKey(
        FormaPagamento,
        on_delete=models.PROTECT,
        related_name="pagamentos",
        verbose_name="forma de pagamento",
    )
    valor = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor"
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMADO,
        db_index=True,
        verbose_name="situação",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    caixa = models.ForeignKey(
        "Caixa",
        on_delete=models.SET_NULL,
        related_name="pagamentos",
        null=True,
        blank=True,
        verbose_name="caixa",
    )
    estornado_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="estornado em"
    )
    estornado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="estornado por",
    )
    motivo_estorno = models.CharField(
        max_length=255, blank=True, verbose_name="motivo do estorno"
    )
    chave_idempotencia = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        indexes = [
            models.Index(
                fields=["conta", "status"], name="idx_pag_conta_status"
            ),
            models.Index(
                fields=["forma_pagamento", "data_hora"],
                name="idx_pag_forma_data",
            ),
            models.Index(fields=["status", "data_hora"], name="idx_pag_status_data"),
        ]

    def __str__(self) -> str:
        return f"Pagamento {self.valor} — {self.conta.descricao}"


class AplicacaoPagamento(BaseModel):
    """Quanto de um pagamento foi aplicado em cada parcela."""

    pagamento = models.ForeignKey(
        Pagamento,
        on_delete=models.CASCADE,
        related_name="aplicacoes",
        verbose_name="pagamento",
    )
    parcela = models.ForeignKey(
        ParcelaContaReceber,
        on_delete=models.PROTECT,
        related_name="aplicacoes",
        verbose_name="parcela",
    )
    valor = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor aplicado"
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name = "aplicação de pagamento"
        verbose_name_plural = "aplicações de pagamento"
        constraints = [
            models.UniqueConstraint(
                "pagamento",
                "parcela",
                condition=Q(is_deleted=False),
                name="uniq_aplicacao_pagamento_parcela",
            )
        ]

    def __str__(self) -> str:
        return f"{self.valor} em {self.parcela}"


class Caixa(BaseModel):
    """Sessão de caixa com abertura, movimentações e fechamento."""

    class Status(models.TextChoices):
        ABERTO = "aberto", "Aberto"
        FECHADO = "fechado", "Fechado"

    descricao = models.CharField(max_length=150, verbose_name="descrição")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ABERTO,
        db_index=True,
        verbose_name="situação",
    )
    data_abertura = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data de abertura"
    )
    data_fechamento = models.DateTimeField(
        null=True, blank=True, verbose_name="data de fechamento"
    )
    valor_abertura = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="valor de abertura",
    )
    valor_fechamento_informado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="valor de fechamento informado",
    )
    valor_fechamento_sistema = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
        verbose_name="valor de fechamento do sistema",
    )
    diferenca = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
        verbose_name="diferença",
    )
    usuario_abertura = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="responsável pela abertura",
    )
    usuario_fechamento = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="responsável pelo fechamento",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    observacoes_fechamento = models.TextField(
        blank=True, verbose_name="observações do fechamento"
    )
    chave_idempotencia = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
    )

    class Meta:
        ordering = ["-data_abertura", "-created_at"]
        verbose_name = "caixa"
        verbose_name_plural = "caixas"
        indexes = [
            models.Index(fields=["status", "-data_abertura"], name="idx_caixa_status_data")
        ]

    def __str__(self) -> str:
        return f"Caixa {self.descricao} ({self.get_status_display()})"

    @property
    def aberto(self) -> bool:
        return self.status == self.Status.ABERTO


class MovimentacaoCaixa(BaseModel):
    """Lançamento manual ou automático no livro-razão do caixa."""

    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SAIDA = "saida", "Saída"
        AJUSTE = "ajuste", "Ajuste"

    caixa = models.ForeignKey(
        Caixa,
        on_delete=models.PROTECT,
        related_name="movimentacoes",
        verbose_name="caixa",
    )
    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        db_index=True,
        verbose_name="tipo",
    )
    valor = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor"
    )
    descricao = models.CharField(max_length=255, verbose_name="descrição")
    forma_pagamento = models.ForeignKey(
        FormaPagamento,
        on_delete=models.PROTECT,
        related_name="movimentacoes_caixa",
        null=True,
        blank=True,
        verbose_name="forma de pagamento",
    )
    pagamento = models.ForeignKey(
        Pagamento,
        on_delete=models.SET_NULL,
        related_name="movimentacoes_caixa",
        null=True,
        blank=True,
        verbose_name="pagamento",
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    chave_idempotencia = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "movimentação de caixa"
        verbose_name_plural = "movimentações de caixa"
        indexes = [
            models.Index(
                fields=["caixa", "-data_hora"], name="idx_mov_caixa_data"
            ),
            models.Index(fields=["tipo", "-data_hora"], name="idx_mov_caixa_tipo_data"),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} {self.valor} — {self.descricao}"

    @property
    def valor_assinado(self) -> Decimal:
        if self.tipo == self.Tipo.SAIDA:
            return -self.valor
        return self.valor


class HistoricoContaReceber(BaseModel):
    """Trilha imutável de mudanças de status/saldo da conta."""

    conta = models.ForeignKey(
        ContaReceber,
        on_delete=models.CASCADE,
        related_name="historico",
        verbose_name="conta a receber",
    )
    status_anterior = models.CharField(
        max_length=20,
        choices=ContaReceber.Status.choices,
        blank=True,
        verbose_name="status anterior",
    )
    status_novo = models.CharField(
        max_length=20, choices=ContaReceber.Status.choices, verbose_name="status novo"
    )
    valor_pago = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor pago"
    )
    saldo = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="saldo"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="usuário",
    )
    observacao = models.CharField(
        max_length=255, blank=True, verbose_name="observação"
    )

    class Meta:
        ordering = ["created_at"]
        verbose_name = "histórico de conta a receber"
        verbose_name_plural = "históricos de conta a receber"
        indexes = [
            models.Index(
                fields=["conta", "created_at"], name="idx_hist_conta_data"
            )
        ]

    def __str__(self) -> str:
        return f"{self.conta_id}: {self.status_anterior or '—'} → {self.status_novo}"
