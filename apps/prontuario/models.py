from django.conf import settings
from django.db import models
from django.utils import timezone
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

    Os campos de aplicação (lote, fabricante, via, dose, veterinário) foram
    acrescentados de forma opcional para preservar os registros já existentes,
    que continuam válidos apenas com nome, datas e observações.
    """

    class ViaAplicacao(models.TextChoices):
        SUBCUTANEA = "subcutanea", "Subcutânea"
        INTRAMUSCULAR = "intramuscular", "Intramuscular"
        INTRANASAL = "intranasal", "Intranasal"
        ORAL = "oral", "Oral"
        TOPICA = "topica", "Tópica"
        OUTRA = "outra", "Outra"

    class Situacao(models.TextChoices):
        EM_DIA = "em_dia", "Em dia"
        PROXIMA = "proxima", "Próxima do retorno"
        ATRASADA = "atrasada", "Atrasada"
        SEM_RETORNO = "sem_retorno", "Sem data de retorno"

    # Janela usada para sinalizar doses de retorno próximas.
    DIAS_ALERTA_RETORNO = 30

    pet = models.ForeignKey(Pet, on_delete=models.PROTECT, related_name="vacinas")
    prontuario = models.ForeignKey(
        Prontuario,
        on_delete=models.SET_NULL,
        related_name="vacinas",
        null=True,
        blank=True,
    )
    veterinario = models.ForeignKey(
        Veterinario,
        on_delete=models.PROTECT,
        related_name="vacinas",
        null=True,
        blank=True,
        verbose_name="veterinário responsável",
    )
    nome_vacina = models.CharField(max_length=100)
    data_aplicacao = models.DateField()
    data_retorno = models.DateField(null=True, blank=True)
    lote = models.CharField(max_length=60, blank=True, verbose_name="lote")
    fabricante = models.CharField(
        max_length=100, blank=True, verbose_name="fabricante"
    )
    via_aplicacao = models.CharField(
        max_length=20,
        choices=ViaAplicacao.choices,
        blank=True,
        verbose_name="via de aplicação",
    )
    dose = models.CharField(max_length=40, blank=True, verbose_name="dose")
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
        # ``-id`` garante paginação estável quando duas doses têm a mesma data.
        ordering = ["-data_aplicacao", "-id"]

    def __str__(self):
        return f"{self.nome_vacina} - {self.pet.nome} ({self.data_aplicacao:%d/%m/%Y})"

    @property
    def dias_para_retorno(self) -> int | None:
        """Dias entre hoje e o retorno previsto (negativo = atrasado)."""
        if not self.data_retorno:
            return None
        return (self.data_retorno - timezone.localdate()).days

    @property
    def situacao(self) -> str:
        """Situação calculada a partir da data de retorno.

        Nunca é persistida: reflete sempre a data atual, sem depender de
        rotinas de atualização em lote.
        """
        dias = self.dias_para_retorno
        if dias is None:
            return self.Situacao.SEM_RETORNO
        if dias < 0:
            return self.Situacao.ATRASADA
        if dias <= self.DIAS_ALERTA_RETORNO:
            return self.Situacao.PROXIMA
        return self.Situacao.EM_DIA

    def clean(self):
        """Validações também aplicadas pelo admin do Django."""
        super().clean()
        erros = {}
        if self.data_aplicacao and self.data_aplicacao > timezone.localdate():
            erros["data_aplicacao"] = "A data de aplicação não pode ser futura."
        if (
            self.data_retorno
            and self.data_aplicacao
            and self.data_retorno < self.data_aplicacao
        ):
            erros["data_retorno"] = (
                "A data de retorno não pode ser anterior à aplicação."
            )
        if erros:
            from django.core.exceptions import ValidationError

            raise ValidationError(erros)

    def save(self, *args, user=None, **kwargs):
        """Propaga o usuário autenticado para created_by/updated_by."""
        if user is not None and getattr(user, "is_authenticated", False):
            if self._state.adding:
                self.created_by = user
            self.updated_by = user
        return super().save(*args, **kwargs)


class Vermifugacao(SoftDeleteModel):
    """Registro de vermifugação de um animal.

    Mesmo padrão de ``Vacina``: PK numérica, autoria e exclusão lógica. O
    ``Pet.vermifugado`` existente é mantido como indicador rápido e não é
    alterado automaticamente por este módulo, para não sobrescrever uma
    informação clínica sem ação explícita do usuário.
    """

    class ViaAdministracao(models.TextChoices):
        ORAL = "oral", "Oral"
        TOPICA = "topica", "Tópica"
        INJETAVEL = "injetavel", "Injetável"
        OUTRA = "outra", "Outra"

    class Situacao(models.TextChoices):
        EM_DIA = "em_dia", "Em dia"
        PROXIMA = "proxima", "Próxima do retorno"
        ATRASADA = "atrasada", "Atrasada"
        SEM_RETORNO = "sem_retorno", "Sem data de retorno"

    # Janela usada para sinalizar retornos próximos.
    DIAS_ALERTA_RETORNO = 30

    pet = models.ForeignKey(
        Pet, on_delete=models.PROTECT, related_name="vermifugacoes"
    )
    prontuario = models.ForeignKey(
        Prontuario,
        on_delete=models.SET_NULL,
        related_name="vermifugacoes",
        null=True,
        blank=True,
    )
    veterinario = models.ForeignKey(
        Veterinario,
        on_delete=models.PROTECT,
        related_name="vermifugacoes",
        null=True,
        blank=True,
        verbose_name="veterinário responsável",
    )
    produto = models.CharField(max_length=120, verbose_name="produto")
    principio_ativo = models.CharField(
        max_length=120, blank=True, verbose_name="princípio ativo"
    )
    data_aplicacao = models.DateField(verbose_name="data de aplicação")
    data_retorno = models.DateField(
        null=True, blank=True, verbose_name="data de retorno"
    )
    peso_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="peso (kg)",
    )
    dose = models.CharField(max_length=40, blank=True, verbose_name="dose")
    lote = models.CharField(max_length=60, blank=True, verbose_name="lote")
    via_administracao = models.CharField(
        max_length=20,
        choices=ViaAdministracao.choices,
        blank=True,
        verbose_name="via de administração",
    )
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
        # ``-id`` garante paginação estável quando duas aplicações têm a
        # mesma data.
        ordering = ["-data_aplicacao", "-id"]

    def __str__(self):
        return (
            f"{self.produto} - {self.pet.nome} "
            f"({self.data_aplicacao:%d/%m/%Y})"
        )

    @property
    def dias_para_retorno(self) -> int | None:
        """Dias entre hoje e o retorno previsto (negativo = atrasado)."""
        if not self.data_retorno:
            return None
        return (self.data_retorno - timezone.localdate()).days

    @property
    def situacao(self) -> str:
        """Situação calculada a partir da data de retorno (nunca persistida)."""
        dias = self.dias_para_retorno
        if dias is None:
            return self.Situacao.SEM_RETORNO
        if dias < 0:
            return self.Situacao.ATRASADA
        if dias <= self.DIAS_ALERTA_RETORNO:
            return self.Situacao.PROXIMA
        return self.Situacao.EM_DIA

    def clean(self):
        """Validações também aplicadas pelo admin do Django."""
        super().clean()
        erros = {}
        if self.data_aplicacao and self.data_aplicacao > timezone.localdate():
            erros["data_aplicacao"] = "A data de aplicação não pode ser futura."
        if (
            self.data_retorno
            and self.data_aplicacao
            and self.data_retorno < self.data_aplicacao
        ):
            erros["data_retorno"] = (
                "A data de retorno não pode ser anterior à aplicação."
            )
        if self.peso_kg is not None and self.peso_kg <= 0:
            erros["peso_kg"] = "O peso deve ser maior que zero."
        if erros:
            from django.core.exceptions import ValidationError

            raise ValidationError(erros)

    def save(self, *args, user=None, **kwargs):
        """Propaga o usuário autenticado para created_by/updated_by."""
        if user is not None and getattr(user, "is_authenticated", False):
            if self._state.adding:
                self.created_by = user
            self.updated_by = user
        return super().save(*args, **kwargs)