"""Prescrição clínica e administração de medicamentos.

A prescrição guarda apenas dados clínicos (animal, profissional, itens,
dose e via). Ela **não** movimenta o estoque: a baixa acontece somente no
registro explícito de uma administração, que gera uma
``MovimentacaoEstoque`` do tipo ``consumo_clinico``.

O cancelamento de uma administração não apaga a movimentação original
(o livro-razão é imutável). Ele registra uma movimentação de devolução e
mantém o vínculo de estorno para auditoria.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.atendimentos.models import Atendimento
from apps.base.models import BaseModel
from apps.estoque.models import Lote, MovimentacaoEstoque, Produto
from apps.pets.models import Pet
from apps.prontuario.models import Prontuario
from apps.veterinarios.models import Profissional, Veterinario


class ViaAdministracao(models.TextChoices):
    """Vias aceitas tanto na prescrição quanto na administração."""

    ORAL = "oral", "Oral"
    SUBCUTANEA = "subcutanea", "Subcutânea"
    INTRAMUSCULAR = "intramuscular", "Intramuscular"
    INTRAVENOSA = "intravenosa", "Intravenosa"
    TOPICA = "topica", "Tópica"
    OFTALMICA = "oftalmica", "Oftálmica"
    OTOLOGICA = "otologica", "Otológica"
    INALATORIA = "inalatoria", "Inalatória"
    RETAL = "retal", "Retal"
    OUTRA = "outra", "Outra"


class Prescricao(BaseModel):
    """Receita clínica estruturada, vinculada ao prontuário/atendimento.

    A prescrição pode existir sem prontuário (atendimento avulso), mas sempre
    aponta para um animal e um veterinário responsável. Itens referenciam o
    catálogo de produtos, sem gerar qualquer baixa de estoque.
    """

    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        CANCELADA = "cancelada", "Cancelada"

    prontuario = models.ForeignKey(
        Prontuario,
        on_delete=models.PROTECT,
        related_name="prescricoes_estruturadas",
        null=True,
        blank=True,
        verbose_name="prontuário",
    )
    atendimento = models.ForeignKey(
        Atendimento,
        on_delete=models.SET_NULL,
        related_name="prescricoes",
        null=True,
        blank=True,
        verbose_name="atendimento",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="prescricoes",
        verbose_name="animal",
    )
    veterinario = models.ForeignKey(
        Veterinario,
        on_delete=models.PROTECT,
        related_name="prescricoes",
        verbose_name="veterinário responsável",
    )
    data_prescricao = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data da prescrição"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

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

    # Liberação explícita para o portal do tutor (padrão: não expor).
    liberado_portal = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="liberada no portal do tutor",
    )
    liberado_portal_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="liberada no portal em",
    )
    liberado_portal_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="liberada no portal por",
    )

    class Meta:
        ordering = ["-data_prescricao", "-created_at"]
        verbose_name = "prescrição"
        verbose_name_plural = "prescrições"
        indexes = [
            models.Index(
                fields=["pet", "-data_prescricao"], name="idx_presc_pet_data"
            ),
            models.Index(
                fields=["veterinario", "-data_prescricao"],
                name="idx_presc_vet_data",
            ),
        ]

    def __str__(self) -> str:
        return f"Prescrição de {self.pet.nome} ({self.data_prescricao:%d/%m/%Y})"

    @property
    def cancelada(self) -> bool:
        return self.status == self.Status.CANCELADA


class ItemPrescricao(BaseModel):
    """Medicamento prescrito, com posologia clínica.

    ``quantidade_prescrita`` é apenas a quantidade prevista na receita. Ela
    não desconta estoque: o saldo só muda quando há administração registrada.
    """

    prescricao = models.ForeignKey(
        Prescricao,
        on_delete=models.PROTECT,
        related_name="itens",
        verbose_name="prescrição",
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="itens_prescricao",
        verbose_name="medicamento",
    )
    dose = models.CharField(max_length=60, blank=True, verbose_name="dose")
    via = models.CharField(
        max_length=20,
        choices=ViaAdministracao.choices,
        default=ViaAdministracao.ORAL,
        verbose_name="via",
    )
    frequencia = models.CharField(
        max_length=60, blank=True, verbose_name="frequência"
    )
    duracao = models.CharField(
        max_length=60, blank=True, verbose_name="duração"
    )
    quantidade_prescrita = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name="quantidade prescrita",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "item de prescrição"
        verbose_name_plural = "itens de prescrição"
        indexes = [
            models.Index(
                fields=["prescricao", "produto"],
                name="idx_item_presc_produto",
            )
        ]

    def __str__(self) -> str:
        return f"{self.produto.nome} — {self.prescricao}"


class AdministracaoMedicamento(BaseModel):
    """Registro de medicamento efetivamente administrado no animal.

    Cada administração está ligada a **uma** movimentação de consumo clínico.
    O vínculo é ``OneToOne`` para impedir que a mesma baixa seja associada a
    duas administrações. Cancelamentos geram uma devolução separada e mantêm
    tanto a movimentação original quanto o estorno rastreáveis.
    """

    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        CANCELADA = "cancelada", "Cancelada"

    item_prescricao = models.ForeignKey(
        ItemPrescricao,
        on_delete=models.PROTECT,
        related_name="administracoes",
        null=True,
        blank=True,
        verbose_name="item da prescrição",
    )
    prescricao = models.ForeignKey(
        Prescricao,
        on_delete=models.PROTECT,
        related_name="administracoes",
        null=True,
        blank=True,
        verbose_name="prescrição",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="administracoes_medicamento",
        verbose_name="animal",
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="administracoes_medicamento",
        verbose_name="medicamento",
    )
    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name="administracoes_medicamento",
        verbose_name="lote",
    )
    atendimento = models.ForeignKey(
        Atendimento,
        on_delete=models.SET_NULL,
        related_name="administracoes_medicamento",
        null=True,
        blank=True,
        verbose_name="atendimento",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="administracoes_medicamento",
        verbose_name="profissional responsável",
    )

    quantidade = models.DecimalField(
        max_digits=12, decimal_places=3, verbose_name="quantidade administrada"
    )
    dose = models.CharField(
        max_length=60, blank=True, verbose_name="dose administrada"
    )
    via = models.CharField(
        max_length=20,
        choices=ViaAdministracao.choices,
        default=ViaAdministracao.ORAL,
        verbose_name="via",
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ATIVA,
        db_index=True,
        verbose_name="situação",
    )
    movimentacao = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.SET_NULL,
        related_name="administracao_medicamento",
        null=True,
        blank=True,
        editable=False,
        verbose_name="movimentação de consumo",
    )
    estorno_movimentacao = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.SET_NULL,
        related_name="estorno_administracao",
        null=True,
        blank=True,
        editable=False,
        verbose_name="movimentação de estorno",
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
            "Evita duplicidade quando a mesma administração é enviada duas "
            "vezes (ex.: duplo clique)."
        ),
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "administração de medicamento"
        verbose_name_plural = "administrações de medicamento"
        indexes = [
            models.Index(
                fields=["pet", "-data_hora"], name="idx_admin_pet_data"
            ),
            models.Index(
                fields=["produto", "-data_hora"], name="idx_admin_prod_data"
            ),
            models.Index(
                fields=["prescricao", "-data_hora"], name="idx_admin_presc_data"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.produto.nome} — {self.pet.nome} "
            f"({self.data_hora:%d/%m/%Y %H:%M})"
        )

    @property
    def cancelada(self) -> bool:
        return self.status == self.Status.CANCELADA
