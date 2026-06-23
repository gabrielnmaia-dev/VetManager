from apps.base.models import BaseModel, ActiveManager
from django.db import models
from apps.pets.models import Pet
from apps.veterinarios.models import Veterinario
from apps.atendimentos.models import Atendimento


# Create your models here.
class Prontuario(BaseModel):
    atendimento = models.OneToOneField(
        Atendimento,
        on_delete=models.SET_NULL,
        related_name="prontuario",
        null=True,
        blank=True,
    )
    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name="prontuarios")
    veterinario = models.ForeignKey(
        Veterinario, on_delete=models.PROTECT, related_name="prontuarios"
    )
    
    data_consulta = models.DateTimeField()
    peso = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    temperatura = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    diagnostico = models.TextField(blank=True)
    observacoes = models.TextField(blank=True)
    prescricao = models.TextField(blank=True)
    retorno_recomendado = models.DateTimeField(null=True, blank=True)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["-data_consulta"]
        
        def __str__(self):
            return f"Prontuário de {self.pet.nome} - {self.data_consulta:%d/%m/%Y}"
        
        
class Vacina(models.Model):
    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name="vacinas")
    prontuario = models.ForeignKey(
        Prontuario,
        on_delete=models.SET_NULL,
        related_name="vacinas",
        null=True,
        blank=True,
    )
    nome_vacina = models.CharField(max_length=100)
    data_aplicacao = models.DateField()
    data_retorno = models.DateField(null=True, blank=True)
    observacoes = models.TextField(blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_aplicacao"]

    def __str__(self):
        return f"{self.nome_vacina} - {self.pet.nome} ({self.data_aplicacao:%d/%m/%Y})"