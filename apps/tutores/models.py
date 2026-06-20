from django.db import models
from apps.base.models import BaseModel, ActiveManager

# Create your models here.
    
 
 
class Tutor(BaseModel):
    nome = models.CharField(max_length=150)
    telefone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    cpf = models.CharField(max_length=14, blank=True)
    endereco = models.CharField(max_length=255, blank=True)
 
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ["nome"]
 
    def __str__(self):
        return self.nome
 