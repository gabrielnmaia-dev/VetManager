"""Modelos de internação veterinária.

O módulo cobre admissão, ocupação de leitos, evolução clínica, cuidados,
administração de medicamentos com baixa de estoque e alta.

Princípios:

* ``OcupacaoLeito`` é o histórico de ocupação. Cada admissão/transferência
  cria uma ocupação; alta/transferência encerra a anterior com ``data_saida``.
* A disponibilidade do leito é derivada da capacidade e das ocupações abertas.
* Evoluções e cuidados são registros históricos: não há update nem delete.
* Administrações de medicamentos geram movimentação de consumo clínico e
  devolução no cancelamento, preservando o livro-razão imutável do estoque.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.atendimentos.models import Atendimento
from apps.base.models import BaseModel
from apps.documentos.models import DocumentoClinico
from apps.estoque.models import Lote, MovimentacaoEstoque, Produto
from apps.pets.models import Pet
from apps.prescricao.models import ItemPrescricao, Prescricao, ViaAdministracao
from apps.prontuario.models import Prontuario
from apps.veterinarios.models import Profissional


class Leito(BaseModel):
    """Leito/unidade de internação."""

    class Tipo(models.TextChoices):
        CLINICO = "clinico", "Clínico"
        CIRURGICO = "cirurgico", "Cirúrgico"
        ISOLAMENTO = "isolamento", "Isolamento"
        UTI = "uti", "UTI"
        OBSERVACAO = "observacao", "Observação"
        BERCARIO = "bercario", "Berçário"

    class Situacao(models.TextChoices):
        ATIVO = "ativo", "Ativo"
        INATIVO = "inativo", "Inativo"
        MANUTENCAO = "manutencao", "Em manutenção"

    nome = models.CharField(max_length=80, verbose_name="nome")
    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.CLINICO,
        db_index=True,
        verbose_name="tipo de leito",
    )
    capacidade = models.PositiveIntegerField(
        default=1, verbose_name="capacidade"
    )
    situacao = models.CharField(
        max_length=20,
        choices=Situacao.choices,
        default=Situacao.ATIVO,
        db_index=True,
        verbose_name="situação",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["nome"]
        verbose_name = "leito"
        verbose_name_plural = "leitos"
        constraints = [
            models.UniqueConstraint(
                "nome",
                condition=models.Q(is_deleted=False),
                name="uniq_leito_nome_ativo",
            )
        ]
        indexes = [
            models.Index(fields=["situacao", "tipo"], name="idx_leito_sit_tipo")
        ]

    def __str__(self) -> str:
        return f"{self.nome} ({self.get_tipo_display()})"

    @property
    def ocupacoes_abertas(self):
        return self.ocupacoes.filter(data_saida__isnull=True, is_deleted=False)

    @property
    def ocupados(self) -> int:
        if hasattr(self, "ocupados_count"):
            return self.ocupados_count
        return self.ocupacoes_abertas.count()

    @property
    def disponivel(self) -> bool:
        return (
            self.situacao == self.Situacao.ATIVO
            and self.ocupados < max(self.capacidade or 1, 1)
        )

    @property
    def situacao_operacional(self) -> str:
        if self.situacao == self.Situacao.INATIVO:
            return "inativo"
        if self.situacao == self.Situacao.MANUTENCAO:
            return "manutencao"
        if self.ocupados >= max(self.capacidade or 1, 1):
            return "lotado"
        return "disponivel"


class Internacao(BaseModel):
    """Episódio de internação de um animal."""

    class Status(models.TextChoices):
        INTERNADO = "internado", "Internado"
        ALTA = "alta", "Alta"
        OBITO = "obito", "Óbito"
        TRANSFERIDO = "transferido", "Transferido"

    class EstadoClinico(models.TextChoices):
        ESTAVEL = "estavel", "Estável"
        GRAVE = "grave", "Grave"
        CRITICO = "critico", "Crítico"
        EM_OBSERVACAO = "em_observacao", "Em observação"
        RECUPERACAO = "recuperacao", "Em recuperação"

    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="internacoes",
        verbose_name="animal",
    )
    atendimento_origem = models.ForeignKey(
        Atendimento,
        on_delete=models.SET_NULL,
        related_name="internacoes",
        null=True,
        blank=True,
        verbose_name="atendimento de origem",
    )
    prontuario = models.ForeignKey(
        Prontuario,
        on_delete=models.SET_NULL,
        related_name="internacoes",
        null=True,
        blank=True,
        verbose_name="prontuário",
    )
    leito = models.ForeignKey(
        Leito,
        on_delete=models.PROTECT,
        related_name="internacoes",
        null=True,
        blank=True,
        verbose_name="leito atual",
    )
    profissional_responsavel = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="internacoes_responsavel",
        verbose_name="profissional responsável",
    )
    motivo_internacao = models.TextField(verbose_name="motivo da internação")
    data_hora_entrada = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora de entrada"
    )
    diagnostico_inicial = models.TextField(
        blank=True, verbose_name="diagnóstico inicial"
    )
    estado_clinico = models.CharField(
        max_length=20,
        choices=EstadoClinico.choices,
        default=EstadoClinico.ESTAVEL,
        db_index=True,
        verbose_name="estado clínico",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.INTERNADO,
        db_index=True,
        verbose_name="situação",
    )
    data_hora_alta = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="data e hora da alta"
    )
    profissional_alta = models.ForeignKey(
        Profissional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="altas_internacao",
        verbose_name="profissional da alta",
    )
    condicao_alta = models.TextField(blank=True, verbose_name="condição na alta")
    orientacoes_tutor = models.TextField(
        blank=True, verbose_name="orientações ao tutor"
    )
    resumo_internacao = models.TextField(
        blank=True, verbose_name="resumo da internação"
    )
    prescricoes = models.ManyToManyField(
        Prescricao,
        blank=True,
        related_name="internacoes",
        verbose_name="prescrições de alta",
    )
    documentos = models.ManyToManyField(
        DocumentoClinico,
        blank=True,
        related_name="internacoes",
        verbose_name="documentos de alta",
    )
    chave_idempotencia = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        editable=False,
        verbose_name="chave de idempotência",
        help_text=(
            "Evita duplicidade quando a admissão é enviada duas vezes "
            "(ex.: duplo clique)."
        ),
    )

    class Meta:
        ordering = ["-data_hora_entrada", "-created_at"]
        verbose_name = "internação"
        verbose_name_plural = "internações"
        indexes = [
            models.Index(
                fields=["pet", "-data_hora_entrada"], name="idx_intern_pet_data"
            ),
            models.Index(fields=["status", "-data_hora_entrada"], name="idx_intern_status"),
            models.Index(
                fields=["profissional_responsavel", "-data_hora_entrada"],
                name="idx_intern_prof_data",
            ),
        ]

    def __str__(self) -> str:
        return f"Internação de {self.pet.nome} ({self.get_status_display()})"

    @property
    def ativa(self) -> bool:
        return self.status == self.Status.INTERNADO


class OcupacaoLeito(BaseModel):
    """Período de ocupação de um leito por uma internação."""

    internacao = models.ForeignKey(
        Internacao,
        on_delete=models.CASCADE,
        related_name="ocupacoes",
        verbose_name="internação",
    )
    leito = models.ForeignKey(
        Leito,
        on_delete=models.PROTECT,
        related_name="ocupacoes",
        verbose_name="leito",
    )
    data_entrada = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data de entrada"
    )
    data_saida = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name="data de saída"
    )
    motivo_saida = models.CharField(
        max_length=120, blank=True, verbose_name="motivo da saída"
    )

    class Meta:
        ordering = ["-data_entrada", "-created_at"]
        verbose_name = "ocupação de leito"
        verbose_name_plural = "ocupações de leito"
        indexes = [
            models.Index(
                fields=["leito", "data_saida"], name="idx_ocup_leito_saida"
            ),
            models.Index(
                fields=["internacao", "data_saida"],
                name="idx_ocup_intern_saida",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.leito.nome} — {self.internacao.pet.nome}"

    @property
    def ativa(self) -> bool:
        return self.data_saida is None


class EvolucaoInternacao(BaseModel):
    """Evolução clínica imutável de uma internação.

    Sinais vitais são opcionais: registre apenas o que foi medido. Evoluções
    anteriores nunca são sobrescritas.
    """

    internacao = models.ForeignKey(
        Internacao,
        on_delete=models.CASCADE,
        related_name="evolucoes",
        verbose_name="internação",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="evolucoes_internacao",
        verbose_name="profissional responsável",
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    evolucao_clinica = models.TextField(verbose_name="evolução clínica")
    observacoes = models.TextField(blank=True, verbose_name="observações")
    intercorrencias = models.TextField(blank=True, verbose_name="intercorrências")

    peso = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="peso (kg)",
    )
    temperatura = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name="temperatura (°C)",
    )
    frequencia_cardiaca = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="frequência cardíaca (bpm)"
    )
    frequencia_respiratoria = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="frequência respiratória (ipm)"
    )
    pressao_arterial = models.CharField(
        max_length=20, blank=True, verbose_name="pressão arterial (mmHg)"
    )
    saturacao = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="saturação de O2 (%)"
    )
    glicemia = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name="glicemia (mg/dL)",
    )
    escore_corporal = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name="escore corporal"
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "evolução de internação"
        verbose_name_plural = "evoluções de internação"
        indexes = [
            models.Index(
                fields=["internacao", "-data_hora"],
                name="idx_evol_intern_data",
            )
        ]

    def __str__(self) -> str:
        return f"Evolução de {self.internacao.pet.nome} ({self.data_hora:%d/%m/%Y %H:%M})"


class CuidadoInternacao(BaseModel):
    """Registro de cuidado de enfermagem/rotina da internação."""

    class Tipo(models.TextChoices):
        ALIMENTACAO = "alimentacao", "Alimentação"
        HIDRATACAO = "hidratacao", "Hidratação"
        MEDICACAO = "medicacao", "Medicação (registro)"
        PROCEDIMENTO = "procedimento", "Procedimento"
        MONITORAMENTO = "monitoramento", "Monitoramento"
        ENFERMAGEM = "enfermagem", "Observação de enfermagem"

    internacao = models.ForeignKey(
        Internacao,
        on_delete=models.CASCADE,
        related_name="cuidados",
        verbose_name="internação",
    )
    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        db_index=True,
        verbose_name="tipo de cuidado",
    )
    descricao = models.TextField(verbose_name="descrição")
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="cuidados_internacao",
        verbose_name="profissional responsável",
    )
    data_hora = models.DateTimeField(
        default=timezone.now, db_index=True, verbose_name="data e hora"
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "cuidado de internação"
        verbose_name_plural = "cuidados de internação"
        indexes = [
            models.Index(
                fields=["internacao", "-data_hora"],
                name="idx_cuidado_intern_data",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.internacao.pet.nome}"


class AdministracaoMedicamentoInternacao(BaseModel):
    """Medicamento efetivamente administrado durante a internação.

    Cada administração gera uma movimentação de consumo clínico. O
    cancelamento gera devolução e mantém a movimentação original para
    auditoria.
    """

    class Status(models.TextChoices):
        ATIVA = "ativa", "Ativa"
        CANCELADA = "cancelada", "Cancelada"

    internacao = models.ForeignKey(
        Internacao,
        on_delete=models.PROTECT,
        related_name="administracoes",
        verbose_name="internação",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="administracoes_internacao",
        verbose_name="animal",
    )
    item_prescricao = models.ForeignKey(
        ItemPrescricao,
        on_delete=models.SET_NULL,
        related_name="administracoes_internacao",
        null=True,
        blank=True,
        verbose_name="item da prescrição",
    )
    prescricao = models.ForeignKey(
        Prescricao,
        on_delete=models.SET_NULL,
        related_name="administracoes_internacao",
        null=True,
        blank=True,
        verbose_name="prescrição",
    )
    produto = models.ForeignKey(
        Produto,
        on_delete=models.PROTECT,
        related_name="administracoes_internacao",
        verbose_name="medicamento",
    )
    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name="administracoes_internacao",
        verbose_name="lote",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="administracoes_internacao",
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
        related_name="administracao_internacao",
        null=True,
        blank=True,
        editable=False,
        verbose_name="movimentação de consumo",
    )
    estorno_movimentacao = models.OneToOneField(
        MovimentacaoEstoque,
        on_delete=models.SET_NULL,
        related_name="estorno_administracao_internacao",
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
    )

    class Meta:
        ordering = ["-data_hora", "-created_at"]
        verbose_name = "administração de medicamento na internação"
        verbose_name_plural = "administrações de medicamento na internação"
        indexes = [
            models.Index(
                fields=["internacao", "-data_hora"],
                name="idx_adm_intern_data",
            ),
            models.Index(
                fields=["pet", "-data_hora"], name="idx_adm_intern_pet_data"
            ),
            models.Index(
                fields=["produto", "-data_hora"],
                name="idx_adm_intern_prod_data",
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
