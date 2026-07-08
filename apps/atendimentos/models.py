from django.db import models

# Create your models here.
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

    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name="atendimentos")

    # Por enquanto simples, vira FK pra Profissional depois.
    nome_profissional = models.CharField(max_length=100)

    tipo_servico = models.CharField(max_length=60, choices=TipoServico.choices)
    queixa = models.CharField(max_length=255, blank=True)

    data_hora_inicio = models.DateTimeField()
    duracao_minutos = models.PositiveIntegerField(default=30)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AGENDADO
    )

    observacoes = models.TextField(blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_hora_inicio"]

    def __str__(self):
        return f"{self.pet.nome} - {self.get_tipo_servico_display()} em {self.data_hora_inicio:%d/%m/%Y %H:%M}"

    @property
    def tutor(self):
        return self.pet.tutor