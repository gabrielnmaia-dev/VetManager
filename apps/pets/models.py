from django.db import models
from apps.base.models import BaseModel
from apps.tutores.models import Tutor

# Create your models here.




class Pet(BaseModel):
    class Sexo(models.TextChoices):
        MACHO = "M", "Macho"
        FEMEA = "F", "Fêmea"

    tutor = models.ForeignKey(Tutor, on_delete=models.PROTECT, related_name="pets")

    nome = models.CharField(max_length=100)
    especie = models.CharField(max_length=50)
    raca = models.CharField(max_length=50, blank=True)
    cor = models.CharField(max_length=50, blank=True)
    sexo = models.CharField(max_length=1, choices=Sexo.choices, blank=True)
    castrado = models.BooleanField(default=False)
    vermifugado = models.BooleanField(default=False)
    data_nascimento = models.DateField(null=True, blank=True)
    observacoes = models.TextField(blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.tutor.nome})"