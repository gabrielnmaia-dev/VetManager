"""Catálogo de serviços, serviços realizados e orçamentos.

O módulo separa três responsabilidades:

* ``Servico`` é o catálogo comercial (preço base, duração e regras). Não usa
  ``Atendimento.tipo_servico`` como fonte financeira.
* ``Orcamento`` é a proposta comercial enviada ao tutor, com itens, validade,
  decisão e histórico de status.
* ``ServicoRealizado`` é a linha efetivamente executada e cobrável, ligada ao
  atendimento, ao animal e ao profissional responsável.

Valores monetários são sempre calculados no backend. O frontend apenas envia
quantidade, valor unitário e desconto; o total persistido é a fonte de verdade.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.atendimentos.models import Atendimento
from apps.base.models import BaseModel
from apps.pets.models import Pet
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional


def validade_padrao():
    """Validade sugerida de 30 dias para novos orçamentos."""
    return timezone.localdate() + timedelta(days=30)


class CategoriaServico(BaseModel):
    """Agrupamento do catálogo comercial (ex.: consultas, banho e tosa)."""

    nome = models.CharField(max_length=100, verbose_name="nome")
    descricao = models.TextField(blank=True, verbose_name="descrição")
    ativo = models.BooleanField(default=True, db_index=True, verbose_name="ativa")

    class Meta:
        ordering = ["nome"]
        verbose_name = "categoria de serviço"
        verbose_name_plural = "categorias de serviço"
        constraints = [
            models.UniqueConstraint(
                Lower("nome"),
                condition=Q(is_deleted=False),
                name="uniq_categoria_servico_nome_ativo",
            )
        ]

    def __str__(self) -> str:
        return self.nome


class Servico(BaseModel):
    """Item do catálogo de serviços com preço base e regras comerciais."""

    class Situacao(models.TextChoices):
        ATIVO = "ativo", "Ativo"
        INATIVO = "inativo", "Inativo"

    nome = models.CharField(max_length=150, verbose_name="nome")
    categoria = models.ForeignKey(
        CategoriaServico,
        on_delete=models.PROTECT,
        related_name="servicos",
        verbose_name="categoria",
    )
    descricao = models.TextField(blank=True, verbose_name="descrição")
    preco_base = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="preço base",
    )
    duracao_estimada_minutos = models.PositiveIntegerField(
        default=0, verbose_name="duração estimada (minutos)"
    )
    situacao = models.CharField(
        max_length=20,
        choices=Situacao.choices,
        default=Situacao.ATIVO,
        db_index=True,
        verbose_name="situação",
    )
    regras = models.TextField(
        blank=True,
        verbose_name="regras aplicáveis",
        help_text="Condições comerciais, restrições e observações do serviço.",
    )
    permite_desconto = models.BooleanField(
        default=True, verbose_name="permite desconto"
    )
    desconto_maximo_percentual = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="desconto máximo (%)",
        help_text="Percentual máximo que um usuário não administrador pode aplicar.",
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "serviço"
        verbose_name_plural = "serviços"
        indexes = [
            models.Index(
                fields=["categoria", "situacao"],
                name="idx_serv_categoria_situacao",
            ),
            models.Index(
                fields=["situacao", "nome"], name="idx_serv_situacao_nome"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("nome"),
                condition=Q(is_deleted=False),
                name="uniq_servico_nome_ativo",
            )
        ]

    def __str__(self) -> str:
        return self.nome

    @property
    def ativo(self) -> bool:
        return self.situacao == self.Situacao.ATIVO


class Orcamento(BaseModel):
    """Proposta comercial com itens, validade, decisão e histórico."""

    class Status(models.TextChoices):
        RASCUNHO = "rascunho", "Rascunho"
        ENVIADO = "enviado", "Enviado ao tutor"
        APROVADO = "aprovado", "Aprovado"
        RECUSADO = "recusado", "Recusado"
        EXPIRADO = "expirado", "Expirado"
        CONVERTIDO = "convertido", "Convertido em serviços realizados"
        CANCELADO = "cancelado", "Cancelado"

    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="orcamentos",
        verbose_name="tutor",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="orcamentos",
        verbose_name="animal",
    )
    atendimento = models.ForeignKey(
        Atendimento,
        on_delete=models.SET_NULL,
        related_name="orcamentos",
        null=True,
        blank=True,
        verbose_name="atendimento relacionado",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="orcamentos",
        null=True,
        blank=True,
        verbose_name="profissional responsável",
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    validade = models.DateField(
        default=validade_padrao, db_index=True, verbose_name="validade"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RASCUNHO,
        db_index=True,
        verbose_name="situação",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    subtotal = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        verbose_name="subtotal",
    )
    valor_desconto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        verbose_name="valor do desconto",
    )
    valor_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
        verbose_name="valor total",
    )
    motivo_recusa = models.CharField(
        max_length=255, blank=True, verbose_name="motivo da recusa"
    )
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="decidido por",
    )
    aprovado_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="aprovado em"
    )
    recusado_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="recusado em"
    )
    convertido_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="convertido em"
    )
    cancelado_em = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="cancelado em"
    )
    chave_idempotencia = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
        help_text="Evita duplicidade quando o mesmo orçamento é enviado duas vezes.",
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "orçamento"
        verbose_name_plural = "orçamentos"
        indexes = [
            models.Index(fields=["status", "-data_hora"], name="idx_orc_status_data"),
            models.Index(fields=["pet", "-data_hora"], name="idx_orc_pet_data"),
            models.Index(fields=["tutor", "-data_hora"], name="idx_orc_tutor_data"),
        ]

    def __str__(self) -> str:
        return f"Orçamento {self.pk} — {self.pet.nome}"

    @property
    def vencido(self) -> bool:
        return (
            self.status in {self.Status.RASCUNHO, self.Status.ENVIADO}
            and self.validade < timezone.localdate()
        )

    @property
    def editavel(self) -> bool:
        return self.status in {self.Status.RASCUNHO, self.Status.ENVIADO}


class ItemOrcamento(BaseModel):
    """Linha de serviço de um orçamento."""

    orcamento = models.ForeignKey(
        Orcamento,
        on_delete=models.CASCADE,
        related_name="itens",
        verbose_name="orçamento",
    )
    servico = models.ForeignKey(
        Servico,
        on_delete=models.PROTECT,
        related_name="itens_orcamento",
        verbose_name="serviço",
    )
    quantidade = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal("1.000"), verbose_name="quantidade"
    )
    valor_unitario = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor unitário"
    )
    desconto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="desconto",
    )
    valor_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
        verbose_name="valor total",
    )
    desconto_autorizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="desconto autorizado por",
    )
    desconto_motivo = models.CharField(
        max_length=255, blank=True, verbose_name="motivo do desconto"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "item de orçamento"
        verbose_name_plural = "itens de orçamento"
        constraints = [
            models.UniqueConstraint(
                "orcamento",
                "servico",
                condition=Q(is_deleted=False),
                name="uniq_item_orcamento_servico",
            )
        ]
        indexes = [
            models.Index(
                fields=["orcamento", "servico"], name="idx_item_orc_servico"
            )
        ]

    def __str__(self) -> str:
        return f"{self.servico.nome} — {self.quantidade}"


class HistoricoOrcamento(BaseModel):
    """Trilha imutável de status e alterações do orçamento."""

    orcamento = models.ForeignKey(
        Orcamento,
        on_delete=models.CASCADE,
        related_name="historico",
        verbose_name="orçamento",
    )
    status_anterior = models.CharField(
        max_length=20,
        choices=Orcamento.Status.choices,
        blank=True,
        verbose_name="status anterior",
    )
    status_novo = models.CharField(
        max_length=20, choices=Orcamento.Status.choices, verbose_name="status novo"
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
        verbose_name = "histórico de orçamento"
        verbose_name_plural = "históricos de orçamento"
        indexes = [
            models.Index(
                fields=["orcamento", "created_at"],
                name="idx_hist_orcamento_data",
            )
        ]

    def __str__(self) -> str:
        return f"{self.orcamento_id}: {self.status_anterior or '—'} → {self.status_novo}"


class ServicoRealizado(BaseModel):
    """Serviço efetivamente executado, com valor fechado para cobrança."""

    atendimento = models.ForeignKey(
        Atendimento,
        on_delete=models.PROTECT,
        related_name="servicos_realizados",
        verbose_name="atendimento",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="servicos_realizados",
        verbose_name="animal",
    )
    servico = models.ForeignKey(
        Servico,
        on_delete=models.PROTECT,
        related_name="servicos_realizados",
        verbose_name="serviço",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="servicos_realizados",
        verbose_name="profissional responsável",
    )
    quantidade = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal("1.000"), verbose_name="quantidade"
    )
    valor_unitario = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="valor unitário"
    )
    desconto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="desconto",
    )
    valor_total = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False, verbose_name="valor total"
    )
    desconto_autorizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="desconto autorizado por",
    )
    desconto_motivo = models.CharField(
        max_length=255, blank=True, verbose_name="motivo do desconto"
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    orcamento_item = models.OneToOneField(
        ItemOrcamento,
        on_delete=models.PROTECT,
        related_name="servico_realizado",
        null=True,
        blank=True,
        editable=False,
        verbose_name="item do orçamento",
    )
    chave_idempotencia = models.CharField(
        max_length=120,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
        help_text="Evita duplicidade quando o mesmo serviço é enviado duas vezes.",
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "serviço realizado"
        verbose_name_plural = "serviços realizados"
        indexes = [
            models.Index(
                fields=["pet", "-data_hora"], name="idx_serv_real_pet_data"
            ),
            models.Index(
                fields=["atendimento", "-data_hora"],
                name="idx_serv_real_atend_data",
            ),
            models.Index(
                fields=["profissional", "-data_hora"],
                name="idx_serv_real_prof_data",
            ),
            models.Index(
                fields=["servico", "-data_hora"], name="idx_serv_real_serv_data"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.servico.nome} — {self.pet.nome} "
            f"({self.data_hora:%d/%m/%Y %H:%M})"
        )
