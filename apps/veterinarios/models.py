"""Modelos de profissionais, veterinários e catálogos relacionados à agenda."""

import uuid

from django.conf import settings
from django.db import models

from apps.base.models import BaseModel


class Profissional(BaseModel):
    """Profissional da clínica (veterinário, tosador, banhista, etc.)."""

    class Cargo(models.TextChoices):
        VETERINARIO = "Veterinário", "Veterinário"
        TOSADOR = "tosador", "Tosador"
        BANHISTA = "banhista", "Banhista"
        OUTRO = "Outro", "Outro"

    nome = models.CharField(max_length=150)
    cargo = models.CharField(max_length=20, choices=Cargo.choices)
    telefone = models.CharField(max_length=20, blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["nome"]
        verbose_name = "profissional"
        verbose_name_plural = "profissionais"

    def __str__(self):
        return f"{self.nome} ({self.get_cargo_display()})"


class Veterinario(BaseModel):
    """Veterinário: profissional com CRMV e especialidade.

    Vinculado 1:1 a Profissional. A consistência entre Profissional.cargo
    e Veterinário é validada no backend: apenas profissionais com cargo
    "Veterinário" podem ter registro de Veterinário.
    """

    profissional = models.OneToOneField(
        Profissional,
        on_delete=models.CASCADE,
        related_name="veterinario",
    )

    crmv = models.CharField(max_length=20, unique=True)
    especialidade = models.CharField(max_length=100, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        verbose_name = "veterinário"
        verbose_name_plural = "veterinários"

    def __str__(self):
        return f"Dr(a). {self.profissional.nome} - CRMV: {self.crmv}"

    def save(self, *args, **kwargs):
        """Garante que o profissional vinculado tenha cargo 'Veterinário'."""
        if (
            self.profissional_id
            and self.profissional.cargo != "Veterinário"
        ):
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {
                    "profissional": [
                        "Somente profissionais com cargo 'Veterinário' podem ter "
                        "registro de veterinário."
                    ]
                }
            )
        return super().save(*args, **kwargs)


class TipoServico(BaseModel):
    """Catálogo de tipos de serviço com duração e intervalo configuráveis.

    Permite definir duração padrão e intervalo entre atendimentos para cada
    tipo de serviço, usados na validação de conflitos e geração de agenda.
    """

    nome = models.CharField(max_length=60, unique=True)
    duracao_padrao_minutos = models.PositiveIntegerField(
        default=30, help_text="Duração padrão em minutos."
    )
    intervalo_minutos = models.PositiveIntegerField(
        default=0, help_text="Intervalo entre atendimentos deste tipo (minutos)."
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["nome"]
        verbose_name = "tipo de serviço"
        verbose_name_plural = "tipos de serviço"

    def __str__(self):
        return self.nome


class SalaConsultorio(BaseModel):
    """Sala de consulta / consultório disponível para agendamentos."""

    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["nome"]
        verbose_name = "sala"
        verbose_name_plural = "salas"

    def __str__(self):
        return self.nome


class HorarioTrabalho(BaseModel):
    """Horário de trabalho semanal de um profissional.

    Define em quais dias da semana e em qual horário o profissional atende.
    Usado para validar se um agendamento está dentro do expediente.
    """

    class DiaSemana(models.IntegerChoices):
        SEGUNDA = 0, "Segunda-feira"
        TERCA = 1, "Terça-feira"
        QUARTA = 2, "Quarta-feira"
        QUINTA = 3, "Quinta-feira"
        SEXTA = 4, "Sexta-feira"
        SABADO = 5, "Sábado"
        DOMINGO = 6, "Domingo"

    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.CASCADE,
        related_name="horarios_trabalho",
    )
    dia_semana = models.PositiveSmallIntegerField(choices=DiaSemana.choices)
    hora_inicio = models.TimeField()
    hora_fim = models.TimeField()
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["profissional", "dia_semana", "hora_inicio"]
        unique_together = [("profissional", "dia_semana", "hora_inicio")]
        verbose_name = "horário de trabalho"
        verbose_name_plural = "horários de trabalho"

    def __str__(self):
        return (
            f"{self.profissional.nome} - {self.get_dia_semana_display()} "
            f"{self.hora_inicio}-{self.hora_fim}"
        )


class BloqueioAgenda(BaseModel):
    """Bloqueio de agenda: feriados, folgas, ausências, manutenção.

    Pode ser aplicado a um profissional específico ou a todos (feriado).
    """

    class TipoBloqueio(models.TextChoices):
        FERIADO = "feriado", "Feriado"
        FOLGA = "folga", "Folga"
        AUSENCIA = "ausencia", "Ausência"
        MANUTENCAO = "manutencao", "Manutenção"
        OUTRO = "outro", "Outro"

    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.CASCADE,
        related_name="bloqueios_agenda",
        null=True,
        blank=True,
        help_text="Se vazio, aplica a todos os profissionais (feriado).",
    )
    sala = models.ForeignKey(
        SalaConsultorio,
        on_delete=models.CASCADE,
        related_name="bloqueios_agenda",
        null=True,
        blank=True,
        help_text="Se vazio, aplica a todas as salas.",
    )
    tipo = models.CharField(max_length=20, choices=TipoBloqueio.choices)
    motivo = models.CharField(max_length=255, blank=True)
    data_inicio = models.DateTimeField()
    data_fim = models.DateTimeField()
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["data_inicio"]
        verbose_name = "bloqueio de agenda"
        verbose_name_plural = "bloqueios de agenda"

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.data_inicio:%d/%m/%Y %H:%M}"


class ListaEspera(BaseModel):
    """Lista de espera por vaga em horário desejado."""

    pet = models.ForeignKey(
        "pets.Pet",
        on_delete=models.CASCADE,
        related_name="lista_espera",
    )
    tutor = models.ForeignKey(
        "tutores.Tutor",
        on_delete=models.CASCADE,
        related_name="lista_espera",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lista_espera",
    )
    tipo_servico = models.ForeignKey(
        TipoServico,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lista_espera",
    )
    data_desejada = models.DateField()
    horario_inicio_desejado = models.TimeField()
    horario_fim_desejado = models.TimeField(
        null=True, blank=True, help_text="Horário limite aceitável."
    )
    observacoes = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    atendimento_gerado = models.ForeignKey(
        "atendimentos.Atendimento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lista_espera_origem",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["-criado_em"]
        verbose_name = "lista de espera"
        verbose_name_plural = "listas de espera"

    def __str__(self):
        return f"{self.pet.nome} - {self.data_desejada}"


class AgendamentoRecorrente(BaseModel):
    """Template de agendamento recorrente (ex.: toda terça às 10h)."""

    pet = models.ForeignKey(
        "pets.Pet",
        on_delete=models.CASCADE,
        related_name="agendamentos_recorrentes",
    )
    tutor = models.ForeignKey(
        "tutores.Tutor",
        on_delete=models.CASCADE,
        related_name="agendamentos_recorrentes",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.CASCADE,
        related_name="agendamentos_recorrentes",
    )
    tipo_servico = models.ForeignKey(
        TipoServico,
        on_delete=models.CASCADE,
        related_name="agendamentos_recorrentes",
    )
    sala = models.ForeignKey(
        SalaConsultorio,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agendamentos_recorrentes",
    )
    duracao_minutos = models.PositiveIntegerField(default=30)
    dia_semana = models.PositiveSmallIntegerField(
        choices=HorarioTrabalho.DiaSemana.choices
    )
    hora_inicio = models.TimeField()
    data_inicio = models.DateField()
    data_fim = models.DateField(
        null=True,
        blank=True,
        help_text="Data final da recorrência (opcional).",
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta(BaseModel.Meta):
        ordering = ["dia_semana", "hora_inicio"]
        verbose_name = "agendamento recorrente"
        verbose_name_plural = "agendamentos recorrentes"

    def __str__(self):
        return (
            f"{self.pet.nome} - {self.get_dia_semana_display()} {self.hora_inicio}"
        )


class HistoricoStatusAtendimento(BaseModel):
    """Registro de mudança de status de atendimento (audit trail de status)."""

    atendimento = models.ForeignKey(
        "atendimentos.Atendimento",
        on_delete=models.CASCADE,
        related_name="historico_status",
    )
    status_anterior = models.CharField(max_length=20, blank=True)
    status_novo = models.CharField(max_length=20)
    motivo = models.CharField(max_length=255, blank=True)
    data_operacao = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mudancas_status_atendimento",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-data_operacao"]
        verbose_name = "histórico de status"
        verbose_name_plural = "históricos de status"

    def __str__(self):
        return f"{self.atendimento_id}: {self.status_anterior} → {self.status_novo}"
