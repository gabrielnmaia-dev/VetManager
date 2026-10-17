"""Regras de negócio do app tutores.

Views e serializers apenas validam e delegam para cá. Toda criação que envolve
mais de um objeto roda dentro de transaction.atomic: falhou qualquer etapa,
nada é persistido (rollback total).
"""

from django.db import transaction

from apps.pets.models import Pet

from .models import Tutor


@transaction.atomic
def criar_tutor_com_pets(tutor_data: dict, pets_data: list | None = None) -> Tutor:
    """Cria o tutor e, opcionalmente, seus pets em uma única transação.

    Args:
        tutor_data: dados validados do tutor (sem a chave "pets").
        pets_data: lista de dicts validados dos pets (sem a chave "tutor").

    Returns:
        O tutor criado (com os pets já persistidos).

    Raises:
        Qualquer exceção de persistência desfaz tutor e pets criados.
    """
    pets_data = pets_data or []
    tutor = Tutor.objects.create(**tutor_data)
    for pet_data in pets_data:
        Pet.objects.create(tutor=tutor, **pet_data)
    return tutor
