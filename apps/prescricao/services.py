"""Regras transacionais de prescrição e administração de medicamentos.

Separação de responsabilidades:

* ``criar_prescricao`` grava somente dados clínicos; nunca toca no estoque.
* ``registrar_administracao`` cria a administração e a movimentação de
  consumo clínico na mesma transação, com bloqueio do lote.
* ``cancelar_administracao`` registra uma devolução (estorno) e preserva a
  movimentação original, pois o livro-razão é imutável.

Toda criação usa ``transaction.atomic``: se qualquer etapa falhar (saldo,
lote vencido, produto divergente), nada é persistido.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.estoque.models import Lote, MovimentacaoEstoque, Produto
from apps.estoque.services import _normalizar_quantidade, registrar_movimentacao
from apps.pets.models import Pet
from apps.veterinarios.models import Profissional

from .models import (
    AdministracaoMedicamento,
    ItemPrescricao,
    Prescricao,
)


def _validar_produto_medicamento(produto, *, exigir_estoque=False):
    if produto is None:
        raise ValidationError({"produto": ["Informe o medicamento."]})
    if produto.is_deleted:
        raise ValidationError({"produto": ["Medicamento excluído."]})
    if not produto.ativo:
        raise ValidationError({"produto": ["Medicamento inativo."]})
    if not produto.is_medicamento:
        raise ValidationError(
            {"produto": ["Selecione um produto da categoria Medicamento."]}
        )
    if exigir_estoque:
        if produto.tipo_estoque != Produto.TipoEstoque.CLINICO:
            raise ValidationError(
                {
                    "produto": [
                        "Somente medicamentos do estoque clínico podem ser "
                        "administrados."
                    ]
                }
            )
        if not produto.controla_estoque:
            raise ValidationError(
                {"produto": ["Este medicamento não controla estoque."]}
            )


def _validar_atendimento(atendimento, pet):
    if atendimento is None:
        return
    if atendimento.is_deleted:
        raise ValidationError({"atendimento": ["Atendimento excluído."]})
    if pet is not None and atendimento.pet_id != pet.pk:
        raise ValidationError(
            {"atendimento": ["O atendimento pertence a outro animal."]}
        )


def _validar_veterinario(veterinario):
    if veterinario is None:
        raise ValidationError(
            {"veterinario": ["Informe o veterinário responsável."]}
        )
    if veterinario.is_deleted:
        raise ValidationError({"veterinario": ["Veterinário excluído."]})
    if veterinario.profissional.cargo != "Veterinário":
        raise ValidationError(
            {
                "veterinario": [
                    "Somente profissionais com cargo 'Veterinário' podem "
                    "assinar prescrições."
                ]
            }
        )


@transaction.atomic
def criar_prescricao(
    *,
    itens,
    pet=None,
    veterinario=None,
    prontuario=None,
    atendimento=None,
    data_prescricao=None,
    observacoes="",
    usuario=None,
):
    """Cria a prescrição e seus itens sem gerar movimentação de estoque."""
    itens = list(itens or [])
    if not itens:
        raise ValidationError(
            {"itens": ["Inclua ao menos um medicamento na prescrição."]}
        )

    if prontuario is not None:
        if prontuario.is_deleted:
            raise ValidationError({"prontuario": ["Prontuário excluído."]})
        if pet is None:
            pet = prontuario.pet
        if veterinario is None:
            veterinario = prontuario.veterinario
        if atendimento is None:
            atendimento = prontuario.atendimento
        if pet is not None and prontuario.pet_id != pet.pk:
            raise ValidationError(
                {"prontuario": ["O prontuário pertence a outro animal."]}
            )

    if atendimento is not None and pet is None:
        pet = atendimento.pet

    if pet is None:
        raise ValidationError({"pet": ["Informe o animal."]})
    if pet.is_deleted:
        raise ValidationError({"pet": ["Animal excluído."]})
    _validar_atendimento(atendimento, pet)
    _validar_veterinario(veterinario)

    prescricao = Prescricao.objects.create(
        prontuario=prontuario,
        atendimento=atendimento,
        pet=pet,
        veterinario=veterinario,
        data_prescricao=data_prescricao or timezone.now(),
        observacoes=observacoes or "",
        created_by=usuario,
        updated_by=usuario,
    )

    for indice, dados in enumerate(itens):
        produto = dados.get("produto")
        try:
            _validar_produto_medicamento(produto)
        except ValidationError as exc:
            # Aponta o índice do item para a interface destacar a linha.
            raise ValidationError(
                {"itens": {indice: exc.detail}}
            ) from exc

        quantidade = dados.get("quantidade_prescrita", 0) or 0
        try:
            quantidade = _normalizar_quantidade(quantidade, permitir_zero=True)
        except ValidationError as exc:
            raise ValidationError(
                {"itens": {indice: exc.detail}}
            ) from exc

        ItemPrescricao.objects.create(
            prescricao=prescricao,
            produto=produto,
            dose=(dados.get("dose") or "").strip(),
            via=dados.get("via") or "oral",
            frequencia=(dados.get("frequencia") or "").strip(),
            duracao=(dados.get("duracao") or "").strip(),
            quantidade_prescrita=quantidade,
            observacoes=dados.get("observacoes") or "",
            created_by=usuario,
            updated_by=usuario,
        )

    return prescricao


def _administracao_existente(chave):
    if not chave:
        return None
    return (
        AdministracaoMedicamento.objects.select_related(
            "pet", "produto", "lote", "profissional", "prescricao"
        )
        .filter(chave_idempotencia=chave)
        .first()
    )


@transaction.atomic
def registrar_administracao(
    *,
    quantidade,
    lote=None,
    produto=None,
    pet=None,
    profissional=None,
    atendimento=None,
    item_prescricao=None,
    dose="",
    via="",
    data_hora=None,
    observacoes="",
    chave_idempotencia="",
    usuario=None,
):
    """Registra a administração e baixa o lote como consumo clínico.

    Retorna ``(administracao, criada)``. Quando a chave de idempotência já
    existe, devolve o registro anterior sem criar uma segunda movimentação.
    """
    chave = (chave_idempotencia or "").strip() or None
    existente = _administracao_existente(chave)
    if existente is not None:
        return existente, False

    prescricao = None
    if item_prescricao is not None:
        item = (
            ItemPrescricao.objects.select_for_update()
            .select_related(
                "produto",
                "prescricao",
                "prescricao__pet",
                "prescricao__veterinario__profissional",
                "prescricao__atendimento",
            )
            .filter(pk=item_prescricao.pk, is_deleted=False)
            .first()
        )
        if item is None:
            raise ValidationError(
                {"item_prescricao": ["Item de prescrição não encontrado."]}
            )
        prescricao = (
            Prescricao.objects.select_for_update()
            .select_related("pet", "veterinario__profissional", "atendimento")
            .filter(pk=item.prescricao_id, is_deleted=False)
            .first()
        )
        if prescricao is None:
            raise ValidationError(
                {"item_prescricao": ["Prescrição não encontrada."]}
            )
        if prescricao.status != Prescricao.Status.ATIVA:
            raise ValidationError(
                {"item_prescricao": ["Não é possível administrar item de uma prescrição cancelada."]}
            )
        if produto is not None and produto.pk != item.produto_id:
            raise ValidationError(
                {"produto": ["O medicamento não corresponde ao item prescrito."]}
            )
        produto = item.produto
        if pet is not None and pet.pk != prescricao.pet_id:
            raise ValidationError(
                {"pet": ["O animal não corresponde ao da prescrição."]}
            )
        pet = prescricao.pet
        if not dose:
            dose = item.dose
        if not via:
            via = item.via
        if profissional is None:
            profissional = prescricao.veterinario.profissional
        if atendimento is None:
            atendimento = prescricao.atendimento
        elif (
            prescricao.atendimento_id is not None
            and atendimento.pk != prescricao.atendimento_id
        ):
            raise ValidationError(
                {"atendimento": ["O atendimento não corresponde ao da prescrição."]}
            )

    if atendimento is not None and pet is None:
        pet = atendimento.pet
    if pet is None:
        raise ValidationError({"pet": ["Informe o animal."]})
    if pet.is_deleted:
        raise ValidationError({"pet": ["Animal excluído."]})
    _validar_atendimento(atendimento, pet)

    if produto is None and lote is not None:
        produto = lote.produto
    if lote is None:
        raise ValidationError({"lote": ["Informe o lote utilizado."]})
    lote = (
        Lote.objects.select_related("produto")
        .filter(pk=lote.pk, is_deleted=False)
        .first()
    )
    if lote is None:
        raise ValidationError({"lote": ["Lote não encontrado."]})
    if produto is None:
        produto = lote.produto
    if lote.produto_id != produto.pk:
        raise ValidationError(
            {"lote": ["O lote informado não pertence ao medicamento selecionado."]}
        )
    _validar_produto_medicamento(produto, exigir_estoque=True)

    if profissional is None:
        raise ValidationError(
            {"profissional": ["Informe o profissional responsável."]}
        )
    if profissional.is_deleted:
        raise ValidationError({"profissional": ["Profissional excluído."]})

    quantidade = _normalizar_quantidade(quantidade)

    dados = {
        "item_prescricao": item_prescricao,
        "prescricao": prescricao,
        "pet": pet,
        "produto": produto,
        "lote": lote,
        "atendimento": atendimento,
        "profissional": profissional,
        "quantidade": quantidade,
        "dose": (dose or "").strip(),
        "via": via or "oral",
        "data_hora": data_hora or timezone.now(),
        "observacoes": observacoes or "",
        "chave_idempotencia": chave,
        "created_by": usuario,
        "updated_by": usuario,
    }

    try:
        with transaction.atomic():
            administracao = AdministracaoMedicamento.objects.create(**dados)
    except IntegrityError:
        # Corrida entre duas requisições com a mesma chave: a segunda perde
        # a constraint única e reaproveita o registro já persistido.
        existente = _administracao_existente(chave)
        if existente is not None:
            return existente, False
        raise

    movimentacao = registrar_movimentacao(
        produto=produto,
        lote=lote,
        tipo=MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
        quantidade=quantidade,
        motivo=f"Administração de medicamento {administracao.id}",
        atendimento=atendimento,
        documento_referencia=str(administracao.id),
        usuario=usuario,
    )
    administracao.movimentacao = movimentacao
    administracao.save(
        user=usuario,
        update_fields=["movimentacao", "updated_at", "updated_by"],
    )
    return administracao, True


@transaction.atomic
def cancelar_administracao(
    *, administracao_id, motivo, usuario=None
):
    """Cancela a administração e devolve a quantidade ao lote original."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError(
            {"motivo": ["Informe o motivo do cancelamento/estorno."]}
        )

    administracao = (
        AdministracaoMedicamento.objects.select_for_update()
        .select_related("pet", "produto", "lote", "prescricao", "atendimento")
        .filter(pk=administracao_id, is_deleted=False)
        .first()
    )
    if administracao is None:
        raise ValidationError(
            {"detail": "Administração de medicamento não encontrada."}
        )
    if administracao.status == AdministracaoMedicamento.Status.CANCELADA:
        raise ValidationError(
            {"detail": "Esta administração já foi cancelada."}
        )

    estorno = registrar_movimentacao(
        produto=administracao.produto,
        lote=administracao.lote,
        tipo=MovimentacaoEstoque.Tipo.DEVOLUCAO,
        quantidade=administracao.quantidade,
        motivo=f"Estorno da administração {administracao.id}: {motivo}",
        atendimento=administracao.atendimento,
        documento_referencia=str(administracao.id),
        usuario=usuario,
    )

    administracao.status = AdministracaoMedicamento.Status.CANCELADA
    administracao.motivo_cancelamento = motivo
    administracao.cancelada_em = timezone.now()
    administracao.cancelada_por = usuario
    administracao.estorno_movimentacao = estorno
    administracao.save(
        user=usuario,
        update_fields=[
            "status",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "estorno_movimentacao",
            "updated_at",
            "updated_by",
        ],
    )
    return administracao


@transaction.atomic
def cancelar_prescricao(*, prescricao_id, motivo, usuario=None):
    """Cancela dados clínicos; não altera estoque."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError(
            {"motivo": ["Informe o motivo do cancelamento da prescrição."]}
        )

    prescricao = (
        Prescricao.objects.select_for_update()
        .filter(pk=prescricao_id, is_deleted=False)
        .first()
    )
    if prescricao is None:
        raise ValidationError({"detail": "Prescrição não encontrada."})
    if prescricao.status == Prescricao.Status.CANCELADA:
        raise ValidationError({"detail": "Esta prescrição já foi cancelada."})
    if prescricao.administracoes.filter(
        status=AdministracaoMedicamento.Status.ATIVA
    ).exists():
        raise ValidationError(
            {
                "detail": (
                    "Cancele as administrações ativas desta prescrição antes "
                    "de cancelá-la."
                )
            }
        )

    prescricao.status = Prescricao.Status.CANCELADA
    prescricao.motivo_cancelamento = motivo
    prescricao.cancelada_em = timezone.now()
    prescricao.cancelada_por = usuario
    prescricao.save(
        user=usuario,
        update_fields=[
            "status",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "updated_at",
            "updated_by",
        ],
    )
    return prescricao
