"""Modelos de pets, catálogos controlados e rastreabilidade de responsabilidade."""

from django.db import models
from django.utils import timezone

from apps.base.models import BaseModel
from apps.tutores.models import Tutor


class Especie(BaseModel):
    """Catálogo controlado de espécies animais (ex.: Cão, Gato, Pássaro)."""

    nome = models.CharField(max_length=50, unique=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "espécie"
        verbose_name_plural = "espécies"

    def __str__(self):
        return self.nome


class Raca(BaseModel):
    """Catálogo controlado de raças, vinculado a uma espécie."""

    especie = models.ForeignKey(
        Especie,
        on_delete=models.PROTECT,
        related_name="racas",
        verbose_name="espécie",
    )
    nome = models.CharField(max_length=50)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["especie__nome", "nome"]
        unique_together = [("especie", "nome")]
        verbose_name = "raça"
        verbose_name_plural = "raças"

    def __str__(self):
        return f"{self.nome} ({self.especie.nome})"


class Pet(BaseModel):
    """Cadastro completo do animal paciente."""

    class Sexo(models.TextChoices):
        MACHO = "M", "Macho"
        FEMEA = "F", "Fêmea"

    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="pets",
        verbose_name="tutor",
    )

    # Catálogos controlados (FKs substituem campos de texto livre).
    especie = models.ForeignKey(
        Especie,
        on_delete=models.PROTECT,
        related_name="pets",
        verbose_name="espécie",
    )
    raca = models.ForeignKey(
        Raca,
        on_delete=models.PROTECT,
        related_name="pets",
        null=True,
        blank=True,
        verbose_name="raça",
    )

    nome = models.CharField(max_length=100, verbose_name="nome")
    cor = models.CharField(max_length=50, blank=True, verbose_name="cor")
    sexo = models.CharField(
        max_length=1,
        choices=Sexo.choices,
        blank=True,
        verbose_name="sexo",
    )
    castrado = models.BooleanField(default=False, verbose_name="castrado")
    vermifugado = models.BooleanField(default=False, verbose_name="vermifugado")
    microchip = models.CharField(
        max_length=50, blank=True, verbose_name="microchip"
    )
    identificacao_adicional = models.CharField(
        max_length=255, blank=True, verbose_name="identificação adicional"
    )
    data_nascimento = models.DateField(
        null=True, blank=True, verbose_name="data de nascimento"
    )
    idade = models.IntegerField(
        null=True, blank=True, verbose_name="idade (anos)"
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    observacoes = models.TextField(blank=True, verbose_name="observações")
    alergias = models.TextField(blank=True, verbose_name="alergias")
    condicoes_preexistentes = models.TextField(
        blank=True, verbose_name="condições preexistentes"
    )
    historico_relevante = models.TextField(
        blank=True, verbose_name="histórico relevante"
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "pet"
        verbose_name_plural = "pets"

    def __str__(self):
        return f"{self.nome} ({self.tutor.nome})"

    @property
    def idade_calculada(self):
        if not self.data_nascimento:
            return None
        hoje = timezone.now().date
        if callable(hoje):
            hoje = hoje()
        nascimento = self.data_nascimento
        anos = hoje.year - nascimento.year
        if (hoje.month, hoje.day) < (nascimento.month, nascimento.day):
            anos -= 1
        return max(anos, 0)

    def save(self, *args, user=None, **kwargs):
        if user is not None and getattr(user, "is_authenticated", False):
            if self._state.adding:
                self.created_by = user
            self.updated_by = user
        return super().save(*args, **kwargs)


class HistoricoResponsabilidadePet(BaseModel):
    """Rastreabilidade de troca de responsável (tutor) de um pet."""

    pet = models.ForeignKey(
        Pet,
        on_delete=models.CASCADE,
        related_name="historico_responsaveis",
        verbose_name="pet",
    )
    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="pets_responsaveis_historico",
        verbose_name="tutor",
    )
    data_inicio = models.DateField(default=timezone.now, verbose_name="início")
    data_fim = models.DateField(
        null=True, blank=True, verbose_name="término"
    )
    motivo = models.CharField(
        max_length=255, blank=True, verbose_name="motivo da troca"
    )

    class Meta:
        ordering = ["-data_inicio"]
        verbose_name = "histórico de responsabilidade"
        verbose_name_plural = "históricos de responsabilidade"

    def __str__(self):
        return f"{self.pet.nome} → {self.tutor.nome} ({self.data_inicio})"

    @property
    def is_atual(self) -> bool:
        return self.data_fim is None
