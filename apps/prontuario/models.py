from django.conf import settings
from django.db import models
from apps.pets.models import Pet
from apps.veterinarios.models import Veterinario
from apps.atendimentos.models import Atendimento
from apps.base.models import BaseModel, SoftDeleteModel


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
    data_nascimento = models.DateField(null=True, blank=True)
    idade = models.IntegerField(null=True, blank=True)
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
        
        
class Vacina(SoftDeleteModel):
    """Registro de vacina.

    Não herda ``BaseModel`` para preservar a PK numérica já existente (dados em
    produção), mas recebe autoria e exclusão lógica — registros clínicos não
    são apagados fisicamente pelo fluxo normal.

    ``criado_em``/``atualizado_em`` já existem no modelo; ``created_by``/
    ``updated_by`` vêm de ``SoftDeleteModel``/``AuditFieldsModel`` via campos
    adicionados nesta herança. Não há duplicação de ``created_at``/``updated_at``
    porque ``AuditFieldsModel`` não é usada aqui.
    """

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
    atualizado_em = models.DateTimeField(auto_now=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="criado por",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="atualizado por",
    )

    class Meta(SoftDeleteModel.Meta):
        ordering = ["-data_aplicacao"]

    def __str__(self):
        return f"{self.nome_vacina} - {self.pet.nome} ({self.data_aplicacao:%d/%m/%Y})"

    def save(self, *args, user=None, **kwargs):
        """Propaga o usuário autenticado para created_by/updated_by."""
        if user is not None and getattr(user, "is_authenticated", False):
            if self._state.adding:
                self.created_by = user
            self.updated_by = user
        return super().save(*args, **kwargs)