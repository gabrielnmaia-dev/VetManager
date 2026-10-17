"""Regras de negócio do app atendimentos.

Views e serializers apenas validam e delegam para cá. Toda criação que envolve
mais de um objeto roda dentro de transaction.atomic: falhou qualquer etapa,
nada é persistido (rollback total).
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import ValidationError

from apps.pets.models import Pet
from apps.tutores.models import Tutor
from apps.tutores.services import criar_tutor_com_pets

from .models import Atendimento

# Campos do próprio Atendimento aceitos no atendimento rápido.
# "profissional_id" vem do payload como instância de Profissional;
# "nome_profissional" continua aceito por compatibilidade legada.
CAMPOS_ATENDIMENTO = (
    "profissional_id",
    "nome_profissional",
    "tipo_servico",
    "queixa",
    "data_hora_inicio",
    "duracao_minutos",
    "status",
    "observacoes",
)


def verificar_conflito_horario(
    *,
    profissional,
    data_hora_inicio,
    duracao_minutos,
    status,
    ignorar_pk=None,
):
    """Impede dois atendimentos sobrepostos para o mesmo profissional.

    Intervalo considerado: [data_hora_inicio, data_hora_inicio + duracao).

    - Sem FK de profissional não há como identificar quem colide (registros
      legados que só têm nome) — nesse caso a regra não é aplicada;
    - atendimentos cancelados nunca geram conflito (nem os existentes nem o
      que está sendo salvo);
    - Na edição, ignorar_pk evita o registro dar conflito consigo mesmo.

    Raises:
        ValidationError (400) com a chave "data_hora_inicio" e mensagem PT.
    """
    if profissional is None or status == Atendimento.Status.CANCELADO:
        return

    fim = data_hora_inicio + timedelta(minutes=duracao_minutos)

    # Janela sonora: um candidato só pode sobrepor se começar depois de
    # inicio - maior_duracao. A agregação evita varrer o histórico inteiro.
    maior_duracao = (
        Atendimento.objects.filter(profissional=profissional)
        .aggregate(maior=Max("duracao_minutos"))["maior"]
        or 0
    )
    candidatos = (
        Atendimento.objects.filter(
            profissional=profissional,
            data_hora_inicio__lt=fim,
            data_hora_inicio__gte=data_hora_inicio
            - timedelta(minutes=maior_duracao),
        )
        .exclude(status=Atendimento.Status.CANCELADO)
    )
    if ignorar_pk is not None:
        candidatos = candidatos.exclude(pk=ignorar_pk)

    for existente in candidatos:
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


def _espelhar_profissional(dados: dict) -> dict:
    """A FK é a fonte da verdade: sincroniza nome_profissional com o nome do
    profissional para manter consistentes os leitores legados do campo."""
    profissional = dados.get("profissional")
    if profissional is not None:
        dados["nome_profissional"] = profissional.nome
    return dados


def _preparar_atendimento(dados: dict) -> dict:
    """Espelha o profissional e valida conflito de horário antes do INSERT."""
    dados = _espelhar_profissional(dados)
    verificar_conflito_horario(
        profissional=dados.get("profissional"),
        data_hora_inicio=dados["data_hora_inicio"],
        duracao_minutos=dados.get(
            "duracao_minutos",
            Atendimento._meta.get_field("duracao_minutos").default,
        ),
        status=dados.get("status", Atendimento.Status.AGENDADO),
    )
    return dados


@transaction.atomic
def criar_atendimento(dados: dict) -> Atendimento:
    """Cria um atendimento validando conflito de horário do profissional.

    Args:
        dados: dados validados pelo AtendimentoSerializer (inclui "pet").
    """
    return Atendimento.objects.create(**_preparar_atendimento(dict(dados)))


@transaction.atomic
def atualizar_atendimento(atendimento: Atendimento, dados: dict) -> Atendimento:
    """Atualiza um atendimento validando conflito (ignorando o próprio
    registro) e re-espeelhando o nome quando a FK muda."""
    dados = dict(dados)

    profissional = dados.get("profissional", atendimento.profissional)
    data_hora_inicio = dados.get(
        "data_hora_inicio", atendimento.data_hora_inicio
    )
    duracao_minutos = dados.get("duracao_minutos", atendimento.duracao_minutos)
    status = dados.get("status", atendimento.status)

    dados = _espelhar_profissional(dados)
    verificar_conflito_horario(
        profissional=profissional,
        data_hora_inicio=data_hora_inicio,
        duracao_minutos=duracao_minutos,
        status=status,
        ignorar_pk=atendimento.pk,
    )

    for campo, valor in dados.items():
        setattr(atendimento, campo, valor)
    atendimento.save()
    return atendimento


def _resolver_tutor(data) -> Tutor:
    """tutor_id = tutor já cadastrado; tutor (dict) = novo cadastro em cascata."""
    if "tutor_id" in data:
        valor = data["tutor_id"]
        return valor if isinstance(valor, Tutor) else Tutor.objects.get(pk=valor)
    tutor_data = data["tutor"]
    pets_data = tutor_data.get("pets") or []
    dados = {
        chave: valor for chave, valor in tutor_data.items() if chave != "pets"
    }
    return criar_tutor_com_pets(dados, pets_data)


def _resolver_pet(data, tutor: Tutor) -> Pet:
    """pet_id = pet já cadastrado (precisa pertencer ao tutor);
    pet (dict) = novo cadastro vinculado ao tutor resolvido."""
    if "pet_id" in data:
        valor = data["pet_id"]
        pet = valor if isinstance(valor, Pet) else Pet.objects.get(pk=valor)
        if pet.tutor_id != tutor.id:
            raise ValidationError(
                {"pet_id": ["O pet informado não pertence ao tutor informado."]}
            )
        return pet
    return Pet.objects.create(tutor=tutor, **data["pet"])


@transaction.atomic
def criar_atendimento_rapido(data: dict) -> Atendimento:
    """Cria um atendimento rápido com tutor e pet existentes ou recém-criados.

    Args:
        data: dados validados pelo AtendimentoRapidoSerializer — exatamente
            um de "tutor_id"/"tutor", exatamente um de "pet_id"/"pet", pelo
            menos um de "profissional_id"/"nome_profissional" e os campos de
            CAMPOS_ATENDIMENTO.

    Returns:
        O Atendimento criado (com pet, tutor e profissional já resolvidos).

    Raises:
        ValidationError: quando o pet_id não pertence ao tutor ou quando há
            conflito de horário do profissional. Nesse caso tudo que tenha
            sido criado na chamada é desfeito (rollback).
    """
    tutor = _resolver_tutor(data)
    pet = _resolver_pet(data, tutor)
    atendimento_data = {
        campo: data[campo] for campo in CAMPOS_ATENDIMENTO if campo in data
    }
    # O serializer rápido não usa source: profissional_id vem como instância
    # e o model espera a FK "profissional".
    if "profissional_id" in atendimento_data:
        atendimento_data["profissional"] = atendimento_data.pop(
            "profissional_id"
        )
    return Atendimento.objects.create(
        pet=pet, **_preparar_atendimento(atendimento_data)
    )
