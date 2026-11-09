"""Modelos de atendimentos e agenda."""

from django.db import models

from apps.base.models import BaseModel
from apps.pets.models import Pet


class Atendimento(BaseModel):
    class TipoServico(models.TextChoices):
        CONSULTA = "consulta", "Consulta"
        RETORNO = "retorno", "Retorno"
        VACINA = "vacina", "Vacina"
        BANHO = "banho", "Banho"
        TOSA = "tosa", "Tosa"
        BANHO_E_TOSA = "banho_e_tosa", "Banho e Tosa"
        BANHO_E_TOSA_HIGIENICA = "banho_e_tosa_higienica", "Banho e Tosa Higiênica"

    class Status(models.TextChoices):
        AGENDADO = "agendado", "Agendado"
        CONFIRMADO = "confirmado", "Confirmado"
        REALIZADO = "realizado", "Realizado"
        CANCELADO = "cancelado", "Cancelado"
        FALTOU = "faltou", "Faltou"

    pet = models.ForeignKey(
        Pet, on_delete=models.PROTECT, related_name="atendimentos"
    )

    # Fonte de verdade: FK para Profissional.
    profissional = models.ForeignKey(
        "veterinarios.Profissional",
        on_delete=models.PROTECT,
        related_name="atendimentos",
        null=True,
        blank=True,
    )

    # Legado: espelho do nome do profissional para os leitores antigos.
    nome_profissional = models.CharField(max_length=100, blank=True)

    # Sala/consultório onde será realizado o atendimento.
    sala = models.ForeignKey(
        "veterinarios.SalaConsultorio",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="atendimentos",
        verbose_name="sala",
    )

    tipo_servico = models.CharField(max_length=60, choices=TipoServico.choices)
    queixa = models.CharField(max_length=255, blank=True)

    data_hora_inicio = models.DateTimeField()
    duracao_minutos = models.PositiveIntegerField(default=30)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AGENDADO
    )

    observacoes = models.TextField(blank=True)
    taxidog = models.BooleanField(default=False)

    # Controle de status e histórico
    motivo_cancelamento = models.CharField(max_length=255, blank=True)
    data_confirmacao = models.DateTimeField(null=True, blank=True)
    data_cancelamento = models.DateTimeField(null=True, blank=True)
    reagendado_de = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reagendamentos",
        verbose_name="reagendado de",
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_hora_inicio"]
        verbose_name = "atendimento"
        verbose_name_plural = "atendimentos"

    def __str__(self):
        return (
            f"{self.pet.nome} - {self.get_tipo_servico_display()} "
            f"em {self.data_hora_inicio:%d/%m/%Y %H:%M}"
        )

    @property
    def tutor(self):
        return self.pet.tutor

    @property
    def fim(self):
        from datetime import timedelta

        return self.data_hora_inicio + timedelta(minutes=self.duracao_minutos)

    def pode_confirmar(self):
        return self.status == self.Status.AGENDADO

    def pode_cancelar(self):
        return self.status in (
            self.Status.AGENDADO,
            self.Status.CONFIRMADO,
        )

    def pode_reagendar(self):
        return self.status in (
            self.Status.AGENDADO,
            self.Status.CONFIRMADO,
        )
