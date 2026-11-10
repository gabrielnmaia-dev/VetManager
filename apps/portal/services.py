"""Regras de negócio do portal do tutor.

Concentra a emissão/resgate de convites, o ciclo de vida das sessões, a
recuperação de senha e a criação de notificações. As views apenas validam a
entrada e chamam estes serviços — o vínculo User–Tutor nunca é criado fora
daqui.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.auditoria.models import AuditLog
from apps.auditoria.services import registrar

from .models import (
    AcessoPortal,
    ConviteAcessoPortal,
    NotificacaoPortal,
    RecuperacaoSenhaPortal,
    SessaoPortal,
)

User = get_user_model()

VERSAO_POLITICA_PRIVACIDADE = "2026-11"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _novo_token() -> str:
    return secrets.token_urlsafe(32)


def _expiracao_convite() -> timedelta:
    return timedelta(hours=getattr(settings, "PORTAL_CONVITE_HORAS", 72))


def _expiracao_recuperacao() -> timedelta:
    return timedelta(minutes=getattr(settings, "PORTAL_RECUPERACAO_MINUTOS", 60))


def _expiracao_refresh() -> timedelta:
    return timedelta(days=getattr(settings, "PORTAL_REFRESH_DIAS", 7))


def _expiracao_access() -> timedelta:
    return timedelta(minutes=getattr(settings, "PORTAL_ACCESS_MINUTOS", 30))


def _ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def _user_agent(request) -> str:
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "")[:255]


# ---------------------------------------------------------------------------
# Convites
# ---------------------------------------------------------------------------


@transaction.atomic
def criar_convite(*, tutor, email: str = "", nome: str = "", usuario=None, request=None):
    """Emite um convite de uso único e devolve ``(convite, token)``.

    Convites pendentes anteriores para o mesmo tutor/e-mail são revogados para
    que exista apenas um token válido por vez.
    """
    email = (email or tutor.email or "").strip().lower()
    if not email:
        raise DjangoValidationError(
            "Informe um e-mail para o convite (o tutor não possui e-mail cadastrado)."
        )

    if AcessoPortal.objects.filter(
        tutor=tutor,
        ativo=True,
        is_deleted=False,
        user__is_active=True,
        user__email__iexact=email,
    ).exists():
        raise DjangoValidationError(
            "Já existe um acesso ativo do portal para este tutor com este e-mail."
        )

    agora = timezone.now()
    ConviteAcessoPortal.objects.filter(
        tutor=tutor,
        email__iexact=email,
        usado_em__isnull=True,
        revogado_em__isnull=True,
        is_deleted=False,
    ).update(revogado_em=agora)

    token = _novo_token()
    convite = ConviteAcessoPortal.objects.create(
        tutor=tutor,
        email=email,
        nome=(nome or "").strip()[:150],
        token_hash=_hash_token(token),
        expira_em=agora + _expiracao_convite(),
        convidado_por=usuario if getattr(usuario, "is_authenticated", False) else None,
    )
    registrar(
        usuario=usuario,
        acao=AuditLog.Acao.CRIACAO,
        instancia=convite,
        justificativa="Convite de acesso ao portal emitido.",
        request=request,
    )
    return convite, token


@transaction.atomic
def resgatar_convite(
    *, token: str, username: str, password: str, aceite_privacidade: bool
):
    """Cria a conta do tutor a partir de um convite válido.

    A conta criada não pertence a nenhum grupo interno, nunca é staff e só
    recebe acesso ao tutor indicado no convite.
    """
    token = (token or "").strip()
    if not token:
        raise DjangoValidationError("Token do convite não informado.")
    if not aceite_privacidade:
        raise DjangoValidationError(
            "É necessário aceitar a política de privacidade para usar o portal."
        )

    convite = (
        ConviteAcessoPortal.objects.select_for_update()
        .select_related("tutor")
        .filter(token_hash=_hash_token(token), is_deleted=False)
        .first()
    )
    if convite is None:
        raise DjangoValidationError("Convite inválido ou não encontrado.")
    if convite.revogado_em:
        raise DjangoValidationError("Este convite foi revogado.")
    if convite.usado_em:
        raise DjangoValidationError("Este convite já foi utilizado.")
    if convite.expirado:
        raise DjangoValidationError("Este convite expirou. Solicite um novo à clínica.")

    username = (username or convite.email).strip()
    if not username:
        raise DjangoValidationError("Informe um nome de usuário.")
    if User.objects.filter(username__iexact=username).exists():
        raise DjangoValidationError("Este nome de usuário já está em uso.")

    try:
        password_validation.validate_password(password)
    except DjangoValidationError as exc:
        raise DjangoValidationError(list(exc.messages))

    user = User(
        username=username,
        email=convite.email,
        first_name=(convite.nome or convite.tutor.nome or "").strip()[:150],
        is_staff=False,
        is_superuser=False,
        is_active=True,
    )
    user.set_password(password)
    user.save()

    acesso = AcessoPortal.objects.create(
        user=user,
        tutor=convite.tutor,
        ativo=True,
        consentimento_privacidade_em=timezone.now(),
        consentimento_privacidade_versao=VERSAO_POLITICA_PRIVACIDADE,
    )

    convite.usado_em = timezone.now()
    convite.save(update_fields=["usado_em", "updated_at"])

    registrar(
        usuario=user,
        acao=AuditLog.Acao.CRIACAO,
        instancia=acesso,
        justificativa="Acesso ao portal criado por resgate de convite.",
    )
    return user, acesso


@transaction.atomic
def revogar_convite(convite: ConviteAcessoPortal, *, usuario=None, request=None):
    if convite.revogado_em or convite.usado_em:
        return convite
    convite.revogado_em = timezone.now()
    convite.save(update_fields=["revogado_em", "updated_at"])
    registrar(
        usuario=usuario,
        acao=AuditLog.Acao.ATUALIZACAO,
        instancia=convite,
        justificativa="Convite de acesso ao portal revogado.",
        request=request,
    )
    return convite


# ---------------------------------------------------------------------------
# Acesso e sessões
# ---------------------------------------------------------------------------


@transaction.atomic
def revogar_acesso(acesso: AcessoPortal, *, usuario=None, motivo: str = "", request=None):
    """Desativa o vínculo e todas as sessões do portal imediatamente."""
    agora = timezone.now()
    acesso.ativo = False
    acesso.revogado_em = agora
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        acesso.revogado_por = usuario
    acesso.save(
        update_fields=[
            "ativo",
            "revogado_em",
            "revogado_por",
            "updated_at",
        ]
    )
    revogar_sessoes(acesso)
    registrar(
        usuario=usuario,
        acao=AuditLog.Acao.ATUALIZACAO,
        instancia=acesso,
        justificativa=(motivo or "Acesso ao portal revogado.").strip(),
        request=request,
    )
    return acesso


def revogar_sessoes(acesso: AcessoPortal, *, exceto: SessaoPortal | None = None):
    qs = SessaoPortal.objects.filter(acesso=acesso, revogada_em__isnull=True)
    if exceto is not None:
        qs = qs.exclude(pk=exceto.pk)
    qs.update(revogada_em=timezone.now(), updated_at=timezone.now())


def _claims_sessao(acesso: AcessoPortal, sessao: SessaoPortal) -> dict:
    return {
        "tipo": "portal",
        "tutor_id": str(acesso.tutor_id),
        "acesso_id": str(acesso.id),
        "sid": str(sessao.id),
        "groups": [],
    }


def criar_tokens(*, acesso: AcessoPortal, request=None):
    """Cria uma sessão e emite o par de tokens do portal.

    Retorna ``(access, refresh, sessao)``. O refresh recebe rotação no
    endpoint de renovação.
    """
    from .tokens import PortalRefreshToken

    agora = timezone.now()
    sessao = SessaoPortal(
        acesso=acesso,
        jti=uuid.uuid4().hex,
        expira_em=agora + _expiracao_refresh(),
        ip=_ip(request),
        user_agent=_user_agent(request),
    )

    refresh = PortalRefreshToken.for_user(acesso.user)
    for chave, valor in _claims_sessao(acesso, sessao).items():
        refresh[chave] = valor
    refresh.set_exp(lifetime=_expiracao_refresh())

    access = refresh.access_token
    access.set_exp(lifetime=_expiracao_access())

    sessao.jti = refresh["jti"]
    sessao.save()

    acesso.ultimo_acesso_em = agora
    acesso.save(update_fields=["ultimo_acesso_em", "updated_at"])
    return access, refresh, sessao


def renovar_tokens(*, refresh_token, request=None):
    """Rotaciona o refresh token e devolve ``(access, refresh, sessao)``.

    Exige que o refresh seja de portal, que a sessão exista, esteja ativa e
    que o ``jti`` corrente coincida com o token apresentado. Um refresh antigo
    (já rotacionado) não pode ser reutilizado.
    """
    from .tokens import PortalRefreshToken

    if refresh_token.get("tipo") != "portal":
        raise DjangoValidationError("Token não pertence ao portal.")

    sid = refresh_token.get("sid")
    acesso_id = refresh_token.get("acesso_id")
    sessao = (
        SessaoPortal.objects.select_related("acesso", "acesso__user", "acesso__tutor")
        .filter(
            id=sid,
            acesso_id=acesso_id,
            revogada_em__isnull=True,
            is_deleted=False,
        )
        .first()
    )
    if sessao is None or not sessao.ativa:
        raise DjangoValidationError("Sessão expirada ou revogada.")
    if sessao.jti != refresh_token.get("jti"):
        # Reuso de refresh antigo: revoga a sessão inteira por precaução.
        sessao.revogada_em = timezone.now()
        sessao.save(update_fields=["revogada_em", "updated_at"])
        raise DjangoValidationError("Sessão inválida. Entre novamente.")
    if not sessao.acesso.valido or not sessao.acesso.user.is_active:
        raise DjangoValidationError("Acesso revogado. Entre em contato com a clínica.")

    # Blacklista o refresh apresentado antes de emitir o novo.
    try:
        refresh_token.blacklist()
    except Exception:
        # A blacklist é uma proteção extra; a checagem de jti acima já impede
        # reutilização dentro do portal.
        pass

    refresh = PortalRefreshToken.for_user(sessao.acesso.user)
    for chave, valor in _claims_sessao(sessao.acesso, sessao).items():
        refresh[chave] = valor
    refresh.set_exp(lifetime=_expiracao_refresh())
    access = refresh.access_token
    access.set_exp(lifetime=_expiracao_access())

    sessao.jti = refresh["jti"]
    sessao.expira_em = timezone.now() + _expiracao_refresh()
    if request is not None:
        sessao.ip = _ip(request)
        sessao.user_agent = _user_agent(request)
    sessao.save(
        update_fields=["jti", "expira_em", "ip", "user_agent", "updated_at"]
    )
    return access, refresh, sessao


def revogar_sessao(sessao: SessaoPortal):
    if sessao.revogada_em is None:
        sessao.revogada_em = timezone.now()
        sessao.save(update_fields=["revogada_em", "updated_at"])


# ---------------------------------------------------------------------------
# Recuperação de senha
# ---------------------------------------------------------------------------


def recuperar_senha(*, email: str, request=None) -> int:
    """Emite tokens de recuperação para contas ativas do portal.

    Sempre retorna a quantidade de contas encontradas; a view não revela esse
    número ao cliente para não permitir enumeração de e-mails.
    """
    email = (email or "").strip().lower()
    if not email:
        return 0

    acessos = (
        AcessoPortal.objects.select_related("user", "tutor")
        .filter(ativo=True, is_deleted=False, user__is_active=True)
        .filter(models_q_email(email))
        .distinct()
    )

    total = 0
    for acesso in acessos:
        token = _novo_token()
        RecuperacaoSenhaPortal.objects.create(
            user=acesso.user,
            token_hash=_hash_token(token),
            expira_em=timezone.now() + _expiracao_recuperacao(),
            ip=_ip(request),
        )
        total += 1
        _enviar_email_recuperacao(acesso, token)
    return total


def models_q_email(email: str):
    from django.db.models import Q

    return Q(user__email__iexact=email) | Q(tutor__email__iexact=email)


def _enviar_email_recuperacao(acesso: AcessoPortal, token: str):
    base = getattr(settings, "PORTAL_URL", "http://localhost:5173/portal").rstrip("/")
    link = f"{base}/redefinir-senha?token={token}"
    assunto = "VetManager — redefinição de senha do portal do tutor"
    mensagem = (
        f"Olá, {acesso.tutor.nome}.\n\n"
        "Recebemos um pedido para redefinir a senha do seu acesso ao portal "
        "do tutor. O link abaixo é de uso único e expira em "
        f"{getattr(settings, 'PORTAL_RECUPERACAO_MINUTOS', 60)} minutos:\n\n"
        f"{link}\n\n"
        "Se você não fez este pedido, ignore esta mensagem. Sua senha atual "
        "continua válida.\n"
    )
    send_mail(
        assunto,
        mensagem,
        getattr(settings, "DEFAULT_FROM_EMAIL", "nao-responda@vetmanager.local"),
        [acesso.user.email or acesso.tutor.email],
        fail_silently=True,
    )


@transaction.atomic
def redefinir_senha(*, token: str, nova_senha: str):
    token = (token or "").strip()
    if not token:
        raise DjangoValidationError("Token não informado.")

    registro = (
        RecuperacaoSenhaPortal.objects.select_for_update()
        .select_related("user")
        .filter(token_hash=_hash_token(token), is_deleted=False)
        .first()
    )
    if registro is None or not registro.utilizavel:
        raise DjangoValidationError("Link inválido ou expirado. Solicite um novo.")
    if not registro.user.is_active:
        raise DjangoValidationError("Conta inativa. Entre em contato com a clínica.")

    try:
        password_validation.validate_password(nova_senha, user=registro.user)
    except DjangoValidationError as exc:
        raise DjangoValidationError(list(exc.messages))

    registro.user.set_password(nova_senha)
    registro.user.save(update_fields=["password"])
    registro.usado_em = timezone.now()
    registro.save(update_fields=["usado_em", "updated_at"])

    acesso = getattr(registro.user, "acesso_portal", None)
    if acesso is not None:
        revogar_sessoes(acesso)

    # Invalida outros tokens de recuperação ainda pendentes.
    RecuperacaoSenhaPortal.objects.filter(
        user=registro.user,
        usado_em__isnull=True,
        is_deleted=False,
    ).exclude(pk=registro.pk).update(
        usado_em=timezone.now(), updated_at=timezone.now()
    )
    return registro.user


# ---------------------------------------------------------------------------
# Notificações
# ---------------------------------------------------------------------------


def criar_notificacao(
    *,
    tutor,
    titulo: str,
    mensagem: str,
    tipo: str = NotificacaoPortal.Tipo.GERAL,
    pet=None,
    usuario=None,
):
    return NotificacaoPortal.objects.create(
        tutor=tutor,
        pet=pet,
        tipo=tipo,
        titulo=titulo.strip()[:150],
        mensagem=mensagem.strip(),
        criada_por=usuario if getattr(usuario, "is_authenticated", False) else None,
    )
