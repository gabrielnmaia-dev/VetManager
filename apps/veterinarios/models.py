from apps.base.models import BaseModel
from django.db import models

# Create your models here.
class Profissional(BaseModel):
    class Cargo(models.TextChoices):
        VETERINARIO = "Veterinário", "Veterinário"
        TOSADOR  = "tosador", "Tosador"
        Banhista = "banhista", "Banhista"
        OUTRO = "Outro", "Outro"
        
    nome = models.CharField(max_length=150)
    cargo = models.CharField(max_length=20, choices=Cargo.choices)
    telefone = models.CharField(max_length=20, blank=True)
    ativo = models.BooleanField(default=True)
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ["nome"]
        
    def __str__(self):
        return f"{self.nome} ({self.get_cargo_display()})"
    
class Veterinario(models.Model):
    profissional = models.OneToOneField(
        Profissional,
        on_delete=models.CASCADE,
        related_name="veterinario",
        primary_key=True,
    )
    
    crmv = models.CharField(max_length=20, unique=True)
    especialidade = models.CharField(max_length=100, blank=True)
    
    def __str__(self):
        return f"Dr(a). {self.profissional.nome} - CRMV: {self.crmv}"