"""Modelos do portal externo do tutor.

O portal é uma superfície **separada** da API interna. O vínculo entre um
usuário do Django e um cadastro de ``Tutor`` nunca é criado livremente pelo
tutor: ele só nasce do resgate de um convite emitido por um usuário interno
autorizado (ver :mod:`apps.portal.services`).

Os registros de sessão existem para permitir revogação explícita. Um token
JWT de portal só é aceito enquanto a sessão correspondente estiver ativa e o
vínculo ``AcessoPortal`` não tiver sido revogado.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.atendimentos.models import Atendimento
from apps.base.models import BaseModel
from apps.pets.models import Pet
from apps.tutores.models import Tutor


class ConviteAcessoPortal(BaseModel):
    """Convite de uso único para vincular um usuário a um tutor.

    O token em texto plano só existe no momento da emissão (devolvido uma
    única vez pela API interna). O banco guarda apenas o hash SHA-256.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        USADO = "usado", "Usado"
        REVOGADO = "revogado", "Revogado"
        EXPIRADO = "expirado", "Expirado"

    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="convites_portal",
        verbose_name="tutor",
    )
    email = models.EmailField(verbose_name="e-mail do convite")
    nome = models.CharField(
        max_length=150, blank=True, verbose_name="nome para o convite"
    )
    token_hash = models.CharField(
        max_length=64, unique=True, editable=False, verbose_name="hash do token"
    )
    expira_em = models.DateTimeField(verbose_name="expira em")
    usado_em = models.DateTimeField(
        null=True, blank=True, verbose_name="usado em"
    )
    revogado_em = models.DateTimeField(
        null=True, blank=True, verbose_name="revogado em"
    )
    convidado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
        verbose_name="convidado por",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "convite de acesso ao portal"
        verbose_name_plural = "convites de acesso ao portal"
        indexes = [
            models.Index(fields=["tutor", "-created_at"]),
            models.Index(fields=["email", "-created_at"]),
            models.Index(fields=["expira_em"]),
        ]

    def __str__(self):
        return f"Convite de {self.email} para {self.tutor.nome}"

    @property
    def expirado(self) -> bool:
        return timezone.now() >= self.expira_em

    @property
    def status(self) -> str:
        if self.revogado_em:
            return self.Status.REVOGADO
        if self.usado_em:
            return self.Status.USADO
        if self.expirado:
            return self.Status.EXPIRADO
        return self.Status.PENDENTE

    @property
    def utilizavel(self) -> bool:
        return self.status == self.Status.PENDENTE


class AcessoPortal(BaseModel):
    """Vínculo ativo entre um usuário e um tutor.

    ``OneToOneField`` garante que uma conta de login represente apenas um
    tutor. Um mesmo tutor pode ter mais de uma conta (por exemplo, dois
    responsáveis pelo mesmo animal), mas cada conta tem seu próprio vínculo.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="acesso_portal",
        verbose_name="usuário",
    )
    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="acessos_portal",
        verbose_name="tutor",
    )
    ativo = models.BooleanField(default=True, verbose_name="ativo")
    revogado_em = models.DateTimeField(
        null=True, blank=True, verbose_name="revogado em"
    )
    revogado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
        verbose_name="revogado por",
    )
    consentimento_privacidade_em = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="aceite da política de privacidade em",
    )
    consentimento_privacidade_versao = models.CharField(
        max_length=20, blank=True, verbose_name="versão da política aceita"
    )
    ultimo_acesso_em = models.DateTimeField(
        null=True, blank=True, verbose_name="último acesso em"
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "acesso ao portal"
        verbose_name_plural = "acessos ao portal"
        indexes = [
            models.Index(fields=["tutor", "ativo"]),
            models.Index(fields=["ativo", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user.get_username()} → {self.tutor.nome}"

    @property
    def valido(self) -> bool:
        return self.ativo and self.revogado_em is None and not self.is_deleted


class SessaoPortal(BaseModel):
    """Sessão autenticada do portal, vinculada ao refresh token corrente.

    Guardar o ``jti`` do refresh permite revogar uma sessão específica e
    detectar reutilização de refresh antigo (rotação).
    """

    acesso = models.ForeignKey(
        AcessoPortal,
        on_delete=models.CASCADE,
        related_name="sessoes",
        verbose_name="acesso",
    )
    jti = models.CharField(
        max_length=64, unique=True, verbose_name="identificador do refresh"
    )
    expira_em = models.DateTimeField(verbose_name="expira em")
    revogada_em = models.DateTimeField(
        null=True, blank=True, verbose_name="revogada em"
    )
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    user_agent = models.CharField(
        max_length=255, blank=True, verbose_name="user agent"
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "sessão do portal"
        verbose_name_plural = "sessões do portal"
        indexes = [
            models.Index(fields=["acesso", "-created_at"]),
            models.Index(fields=["revogada_em", "expira_em"]),
        ]

    def __str__(self):
        return f"Sessão {self.id} de {self.acesso}"

    @property
    def ativa(self) -> bool:
        return (
            self.revogada_em is None
            and not self.is_deleted
            and self.expira_em > timezone.now()
        )


class SolicitacaoAgendamento(BaseModel):
    """Pedido de agendamento feito pelo tutor.

    A solicitação não cria automaticamente um ``Atendimento``: ela entra na
    fila interna para análise da recepção/veterinário. Isso evita que o tutor
    ocupe a agenda sem confirmação da clínica.
    """

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADA = "aprovada", "Aprovada"
        RECUSADA = "recusada", "Recusada"
        CANCELADA = "cancelada", "Cancelada"

    class Periodo(models.TextChoices):
        MANHA = "manha", "Manhã"
        TARDE = "tarde", "Tarde"
        INDIFERENTE = "indiferente", "Indiferente"

    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="solicitacoes_agendamento_portal",
        verbose_name="tutor",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.PROTECT,
        related_name="solicitacoes_agendamento_portal",
        verbose_name="animal",
    )
    tipo_servico = models.CharField(
        max_length=60,
        choices=Atendimento.TipoServico.choices,
        verbose_name="tipo de serviço",
    )
    data_preferida = models.DateField(verbose_name="data preferida")
    periodo = models.CharField(
        max_length=20,
        choices=Periodo.choices,
        default=Periodo.INDIFERENTE,
        verbose_name="período",
    )
    observacoes = models.TextField(blank=True, verbose_name="observações")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
        db_index=True,
        verbose_name="situação",
    )
    resposta = models.TextField(blank=True, verbose_name="resposta da clínica")
    respondido_em = models.DateTimeField(
        null=True, blank=True, verbose_name="respondido em"
    )
    respondido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="respondido por",
    )
    atendimento = models.ForeignKey(
        Atendimento,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitacoes_portal",
        verbose_name="atendimento gerado",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "solicitação de agendamento"
        verbose_name_plural = "solicitações de agendamento"
        indexes = [
            models.Index(fields=["tutor", "status", "-created_at"]),
            models.Index(fields=["pet", "-data_preferida"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.pet.nome} — {self.data_preferida} ({self.status})"


class NotificacaoPortal(BaseModel):
    """Comunicado interno visível para o tutor no portal."""

    class Tipo(models.TextChoices):
        GERAL = "geral", "Geral"
        AGENDAMENTO = "agendamento", "Agendamento"
        DOCUMENTO = "documento", "Documento"
        PRESCRICAO = "prescricao", "Prescrição"
        VACINA = "vacina", "Vacina"

    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.PROTECT,
        related_name="notificacoes_portal",
        verbose_name="tutor",
    )
    pet = models.ForeignKey(
        Pet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notificacoes_portal",
        verbose_name="animal",
    )
    tipo = models.CharField(
        max_length=20,
        choices=Tipo.choices,
        default=Tipo.GERAL,
        verbose_name="tipo",
    )
    titulo = models.CharField(max_length=150, verbose_name="título")
    mensagem = models.TextField(verbose_name="mensagem")
    lida = models.BooleanField(default=False, db_index=True, verbose_name="lida")
    lida_em = models.DateTimeField(
        null=True, blank=True, verbose_name="lida em"
    )
    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
        verbose_name="criada por",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "notificação do portal"
        verbose_name_plural = "notificações do portal"
        indexes = [
            models.Index(fields=["tutor", "lida", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.titulo} — {self.tutor.nome}"


class RecuperacaoSenhaPortal(BaseModel):
    """Token de uso único para redefinição de senha do portal.

    Assim como os convites, o token em texto plano não é persistido: apenas
    o hash. O token é invalidado após o uso, ao expirar ou quando a senha é
    alterada.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recuperacoes_senha_portal",
        verbose_name="usuário",
    )
    token_hash = models.CharField(
        max_length=64, unique=True, editable=False, verbose_name="hash do token"
    )
    expira_em = models.DateTimeField(verbose_name="expira em")
    usado_em = models.DateTimeField(
        null=True, blank=True, verbose_name="usado em"
    )
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "recuperação de senha do portal"
        verbose_name_plural = "recuperações de senha do portal"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["expira_em"]),
        ]

    def __str__(self):
        return f"Recuperação de {self.user.get_username()}"

    @property
    def utilizavel(self) -> bool:
        return (
            self.usado_em is None
            and not self.is_deleted
            and self.expira_em > timezone.now()
        )
