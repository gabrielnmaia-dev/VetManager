"""Regras de negócio do app atendimentos.

Views e serializers apenas validam e delegam para cá. Toda criação que envolve
mais de um objeto roda dentro de transaction.atomic: falhou qualquer etapa,
nada é persistido (rollback total).

Concorrência: as validações de conflito usam ``select_for_update()`` dentro de
transação para evitar race conditions no PostgreSQL quando dois atendimentos
são criados/atualizados simultaneamente para o mesmo profissional.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.pets.models import Pet
from apps.tutores.models import Tutor
from apps.tutores.services import criar_tutor_com_pets
from apps.veterinarios.models import (
    BloqueioAgenda,
    HistoricoStatusAtendimento,
    HorarioTrabalho,
    Profissional,
    SalaConsultorio,
    TipoServico,
)

from .models import Atendimento

# Campos do próprio Atendimento aceitos no atendimento rápido.
CAMPOS_ATENDIMENTO = (
    "profissional_id",
    "nome_profissional",
    "tipo_servico",
    "queixa",
    "data_hora_inicio",
    "duracao_minutos",
    "status",
    "observacoes",
    "taxidog",
    "sala",
)


# ---------------------------------------------------------------------------
# Validação de conflito de horário (concorrência-safe)
# ---------------------------------------------------------------------------

def _bloqueio_ativa(profissional, sala, data_inicio, data_fim):
    """Verifica se há um bloqueio de agenda que sobreponha o intervalo."""
    qs = BloqueioAgenda.objects.filter(ativo=True, data_inicio__lt=data_fim, data_fim__gt=data_inicio)
    if profissional is not None:
        qs = qs.filter(Q(profissional=profissional) | Q(profissional__isnull=True))
    if sala is not None:
        qs = qs.filter(Q(sala=sala) | Q(sala__isnull=True))
    return qs.exists()


def _dentro_expediente(profissional, data_inicio, data_fim):
    """Verifica se o intervalo está dentro do horário de trabalho do profissional.

    Retorna True se não houver horários de trabalho definidos (compatibilidade
    com profissionais sem configuração de expediente).
    """
    dia_semana = data_inicio.weekday()
    hora_inicio = data_inicio.time()
    hora_fim = data_fim.time()

    horarios = HorarioTrabalho.objects.filter(
        profissional=profissional,
        ativo=True,
        dia_semana=dia_semana,
    )
    if not horarios.exists():
        return True  # Sem horários definidos: permite qualquer horário

    return horarios.filter(
        hora_inicio__lte=hora_inicio,
        hora_fim__gte=hora_fim,
    ).exists()


def verificar_conflito_horario(
    *,
    profissional,
    data_hora_inicio,
    duracao_minutos,
    status,
    ignorar_pk=None,
    sala=None,
):
    """Impede dois atendimentos sobrepostos para o mesmo profissional/sala.

    Usa ``select_for_update()`` para bloquear as filas do profissional e da
    sala durante a transação, evitando race conditions no PostgreSQL.

    Regras:
    - Sem FK de profissional não há conflito (registros legados).
    - Atendimentos cancelados não geram conflito.
    - Na edição, ignorar_pk evita conflito consigo mesmo.
    - Verifica bloqueio de agenda (feriados, folgas, manutenção).
    - Verifica horário de trabalho do profissional.
    - Verifica conflito de sala (se informada).

    Raises:
        ValidationError (400) com chave "data_hora_inicio" ou "sala".
    """
    if profissional is None or status == Atendimento.Status.CANCELADO:
        return

    fim = data_hora_inicio + timedelta(minutes=duracao_minutos)

    # Bloqueia as filas do profissional para leitura/gravação (concorrência).
    candidatos_qs = (
        Atendimento.objects.filter(profissional=profissional)
        .select_for_update()
        .filter(
            data_hora_inicio__lt=fim,
            data_hora_inicio__gte=data_hora_inicio - timedelta(minutes=duracao_minutos),
        )
        .exclude(status=Atendimento.Status.CANCELADO)
    )
    if ignorar_pk is not None:
        candidatos_qs = candidatos_qs.exclude(pk=ignorar_pk)

    for existente in candidatos_qs:
        fim_existente = existente.data_hora_inicio + timedelta(
            minutes=existente.duracao_minutos
        )
        if fim_existente > data_hora_inicio:
            raise ValidationError(
                {
                    "data_hora_inicio": [
                        "Conflito de horário: {} já possui atendimento das "
                        "{} às {}.".format(
                            profissional.nome,
                            existente.data_hora_inicio.strftime("%d/%m/%Y %H:%M"),
                            fim_existente.strftime("%d/%m/%Y %H:%M"),
                        )
                    ]
                }
            )

    # Conflito de sala.
    if sala is not None:
        candidatos_sala = (
            Atendimento.objects.filter(sala=sala)
            .select_for_update()
            .filter(
                data_hora_inicio__lt=fim,
                data_hora_inicio__gte=data_hora_inicio
                - timedelta(minutes=duracao_minutos),
            )
            .exclude(status=Atendimento.Status.CANCELADO)
        )
        if ignorar_pk is not None:
            candidatos_sala = candidatos_sala.exclude(pk=ignorar_pk)
        if candidatos_sala.exists():
            raise ValidationError(
                {
                    "sala": [
                        f"A sala {sala.nome} já possui atendimento neste horário."
                    ]
                }
            )

    # Bloqueio de agenda.
    if _bloqueio_ativa(profissional, sala, data_hora_inicio, fim):
        raise ValidationError(
            {
                "data_hora_inicio": [
                    "O horário selecionado está bloqueado (feriado, folga ou "
                    "manutenção)."
                ]
            }
        )

    # Fora do expediente do profissional.
    if not _dentro_expediente(profissional, data_hora_inicio, fim):
        raise ValidationError(
            {
                "data_hora_inicio": [
                    "O horário está fora do expediente do profissional."
                ]
            }
        )


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _espelhar_profissional(dados: dict) -> dict:
    profissional = dados.get("profissional")
    if profissional is not None:
        dados["nome_profissional"] = profissional.nome
    return dados


def _preparar_atendimento(dados: dict) -> dict:
    dados = _espelhar_profissional(dados)
    verificar_conflito_horario(
        profissional=dados.get("profissional"),
        data_hora_inicio=dados["data_hora_inicio"],
        duracao_minutos=dados.get(
            "duracao_minutos",
            Atendimento._meta.get_field("duracao_minutos").default,
        ),
        status=dados.get("status", Atendimento.Status.AGENDADO),
        sala=dados.get("sala"),
    )
    return dados


# ---------------------------------------------------------------------------
# Criação / atualização
# ---------------------------------------------------------------------------

@transaction.atomic
def criar_atendimento(dados: dict, user=None) -> Atendimento:
    """Cria um atendimento validando conflito de horário e sala."""
    dados = dict(dados)
    if user is not None:
        dados["created_by"] = user
        dados["updated_by"] = user
    return Atendimento.objects.create(**_preparar_atendimento(dados))


@transaction.atomic
def atualizar_atendimento(
    atendimento: Atendimento, dados: dict, user=None
) -> Atendimento:
    """Atualiza um atendimento validando conflito (ignorando o próprio registro)."""
    dados = dict(dados)

    if user is not None:
        dados["updated_by"] = user

    profissional = dados.get("profissional", atendimento.profissional)
    data_hora_inicio = dados.get(
        "data_hora_inicio", atendimento.data_hora_inicio
    )
    duracao_minutos = dados.get("duracao_minutos", atendimento.duracao_minutos)
    status = dados.get("status", atendimento.status)
    sala = dados.get("sala", atendimento.sala)

    dados = _espelhar_profissional(dados)
    verificar_conflito_horario(
        profissional=profissional,
        data_hora_inicio=data_hora_inicio,
        duracao_minutos=duracao_minutos,
        status=status,
        ignorar_pk=atendimento.pk,
        sala=sala,
    )

    for campo, valor in dados.items():
        setattr(atendimento, campo, valor)
    atendimento.save()
    return atendimento


# ---------------------------------------------------------------------------
# Transições de status
# ---------------------------------------------------------------------------

@transaction.atomic
def confirmar_atendimento(
    atendimento: Atendimento, user=None, justificativa: str = ""
) -> Atendimento:
    """Confirma um atendimento agendado."""
    if not atendimento.pode_confirmar():
        raise ValidationError(
            {"status": ["Só é possível confirmar atendimentos agendados."]}
        )
    status_anterior = atendimento.status
    dados = {
        "status": Atendimento.Status.CONFIRMADO,
        "data_confirmacao": timezone.now(),
        "updated_by": user,
    }
    resultado = atualizar_atendimento(atendimento, dados, user=user)
    HistoricoStatusAtendimento.objects.create(
        atendimento=resultado,
        status_anterior=status_anterior,
        status_novo=resultado.status,
        motivo=justificativa,
        usuario=user,
    )
    return resultado


@transaction.atomic
def cancelar_atendimento(
    atendimento: Atendimento, user=None, motivo: str = ""
) -> Atendimento:
    """Cancela um atendimento agendado ou confirmado."""
    if not atendimento.pode_cancelar():
        raise ValidationError(
            {
                "status": [
                    "Só é possível cancelar atendimentos agendados ou confirmados."
                ]
            }
        )
    status_anterior = atendimento.status
    dados = {
        "status": Atendimento.Status.CANCELADO,
        "motivo_cancelamento": motivo,
        "data_cancelamento": timezone.now(),
        "updated_by": user,
    }
    resultado = atualizar_atendimento(atendimento, dados, user=user)
    HistoricoStatusAtendimento.objects.create(
        atendimento=resultado,
        status_anterior=status_anterior,
        status_novo=resultado.status,
        motivo=motivo,
        usuario=user,
    )
    return resultado


@transaction.atomic
def reagendar_atendimento(
    atendimento: Atendimento,
    user=None,
    nova_data_hora_inicio=None,
    nova_duracao_minutos=None,
    nova_sala=None,
    justificativa: str = "",
) -> Atendimento:
    """Reagenda um atendimento para novo horário/sala."""
    if not atendimento.pode_reagendar():
        raise ValidationError(
            {
                "status": [
                    "Só é possível reagendar atendimentos agendados ou "
                    "confirmados."
                ]
            }
        )
    status_anterior = atendimento.status
    dados = {}
    if nova_data_hora_inicio is not None:
        dados["data_hora_inicio"] = nova_data_hora_inicio
        dados["reagendado_de"] = atendimento
    if nova_duracao_minutos is not None:
        dados["duracao_minutos"] = nova_duracao_minutos
    if nova_sala is not None:
        dados["sala"] = nova_sala
    dados["updated_by"] = user
    resultado = atualizar_atendimento(atendimento, dados, user=user)
    HistoricoStatusAtendimento.objects.create(
        atendimento=resultado,
        status_anterior=status_anterior,
        status_novo=resultado.status,
        motivo=justificativa,
        usuario=user,
    )
    return resultado


@transaction.atomic
def marcar_faltou(
    atendimento: Atendimento, user=None, justificativa: str = ""
) -> Atendimento:
    """Marca um atendimento como no-show (faltou)."""
    if atendimento.status not in (
        Atendimento.Status.AGENDADO,
        Atendimento.Status.CONFIRMADO,
    ):
        raise ValidationError(
            {
                "status": [
                    "Só é possível marcar como falta atendimentos agendados "
                    "ou confirmados."
                ]
            }
        )
    status_anterior = atendimento.status
    dados = {
        "status": Atendimento.Status.FALTOU,
        "updated_by": user,
    }
    resultado = atualizar_atendimento(atendimento, dados, user=user)
    HistoricoStatusAtendimento.objects.create(
        atendimento=resultado,
        status_anterior=status_anterior,
        status_novo=resultado.status,
        motivo=justificativa,
        usuario=user,
    )
    return resultado


@transaction.atomic
def realizar_atendimento(
    atendimento: Atendimento, user=None
) -> Atendimento:
    """Marca um atendimento como realizado."""
    if atendimento.status == Atendimento.Status.REALIZADO:
        raise ValidationError(
            {"status": ["Este atendimento já foi realizado."]}
        )
    if atendimento.status == Atendimento.Status.CANCELADO:
        raise ValidationError(
            {"status": ["Não é possível realizar um atendimento cancelado."]}
        )
    status_anterior = atendimento.status
    dados = {"status": Atendimento.Status.REALIZADO, "updated_by": user}
    resultado = atualizar_atendimento(atendimento, dados, user=user)
    HistoricoStatusAtendimento.objects.create(
        atendimento=resultado,
        status_anterior=status_anterior,
        status_novo=resultado.status,
        usuario=user,
    )
    return resultado


# ---------------------------------------------------------------------------
# Resolvedores de cascade (atendimento rápido)
# ---------------------------------------------------------------------------

def _resolver_tutor(data, user=None) -> Tutor:
    """tutor_id = tutor já cadastrado; tutor (dict) = novo cadastro em cascata."""
    if "tutor_id" in data:
        valor = data["tutor_id"]
        return valor if isinstance(valor, Tutor) else Tutor.objects.get(pk=valor)
    tutor_data = data["tutor"]
    pets_data = tutor_data.get("pets") or []
    dados = {
        chave: valor for chave, valor in tutor_data.items() if chave != "pets"
    }
    return criar_tutor_com_pets(dados, pets_data, user=user)


def _resolver_pet(data, tutor: Tutor, user=None) -> Pet:
    """pet_id = pet já cadastrado; pet (dict) = novo cadastro vinculado."""
    if "pet_id" in data:
        valor = data["pet_id"]
        pet = valor if isinstance(valor, Pet) else Pet.objects.get(pk=valor)
        if pet.tutor_id != tutor.id:
            raise ValidationError(
                {"pet_id": ["O pet informado não pertence ao tutor informado."]}
            )
        return pet
    if user is not None:
        data["pet"]["created_by"] = user
        data["pet"]["updated_by"] = user
    return Pet.objects.create(tutor=tutor, **data["pet"])


@transaction.atomic
def criar_atendimento_rapido(data: dict, user=None) -> Atendimento:
    """Cria um atendimento rápido com tutor e pet existentes ou recém-criados."""
    tutor = _resolver_tutor(data, user=user)
    pet = _resolver_pet(data, tutor, user=user)
    atendimento_data = {
        campo: data[campo] for campo in CAMPOS_ATENDIMENTO if campo in data
    }
    if "profissional_id" in atendimento_data:
        atendimento_data["profissional"] = atendimento_data.pop(
            "profissional_id"
        )
    if user is not None:
        atendimento_data["created_by"] = user
        atendimento_data["updated_by"] = user
    return Atendimento.objects.create(
        pet=pet, **_preparar_atendimento(atendimento_data)
    )
