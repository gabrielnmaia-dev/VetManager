"""Regras transacionais do catálogo e da execução de procedimentos.

A criação da execução e o consumo de materiais rodam na mesma transação: se
qualquer lote estiver vencido, sem saldo ou divergente, nada é persistido.

O cancelamento não apaga a movimentação original. Ele registra uma devolução
por material e mantém o vínculo de estorno para auditoria.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.estoque.models import Lote, MovimentacaoEstoque, Produto
from apps.estoque.services import _normalizar_quantidade, registrar_movimentacao
from apps.pets.models import Pet
from apps.veterinarios.models import Profissional

from .models import (
    ExecucaoProcedimento,
    MaterialPrevistoProcedimento,
    MaterialUtilizadoProcedimento,
    Procedimento,
)


def _validar_produto_estoque(produto):
    if produto is None:
        raise ValidationError({"produto": ["Informe o produto."]})
    if produto.is_deleted:
        raise ValidationError({"produto": ["Produto excluído."]})
    if not produto.ativo:
        raise ValidationError({"produto": ["Produto inativo."]})
    if not produto.controla_estoque:
        raise ValidationError(
            {"produto": ["Este produto não controla estoque."]}
        )
    if produto.tipo_estoque != Produto.TipoEstoque.CLINICO:
        raise ValidationError(
            {
                "produto": [
                    "Somente produtos do estoque clínico podem ser usados em "
                    "procedimentos."
                ]
            }
        )


def _validar_procedimento(procedimento):
    if procedimento is None:
        raise ValidationError({"procedimento": ["Informe o procedimento."]})
    if procedimento.is_deleted:
        raise ValidationError({"procedimento": ["Procedimento excluído."]})
    if not procedimento.ativo:
        raise ValidationError(
            {"procedimento": ["Procedimento inativo não pode ser executado."]}
        )


def _validar_atendimento(atendimento, pet):
    if atendimento is None:
        raise ValidationError({"atendimento": ["Informe o atendimento."]})
    if atendimento.is_deleted:
        raise ValidationError({"atendimento": ["Atendimento excluído."]})
    if pet is not None and atendimento.pet_id != pet.pk:
        raise ValidationError(
            {"atendimento": ["O atendimento pertence a outro animal."]}
        )


def _validar_profissional(profissional):
    if profissional is None:
        raise ValidationError(
            {"profissional": ["Informe o profissional responsável."]}
        )
    if profissional.is_deleted:
        raise ValidationError({"profissional": ["Profissional excluído."]})


def _validar_equipe(equipe):
    integrantes = []
    vistos = set()
    for profissional in equipe or []:
        if profissional is None:
            continue
        if profissional.is_deleted:
            raise ValidationError({"equipe": ["Profissional da equipe excluído."]})
        if profissional.pk in vistos:
            continue
        vistos.add(profissional.pk)
        integrantes.append(profissional)
    return integrantes


def _validar_material(produto, lote, quantidade):
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
            {"lote": ["O lote informado não pertence ao produto selecionado."]}
        )
    _validar_produto_estoque(produto)
    return produto, lote, _normalizar_quantidade(quantidade)


@transaction.atomic
def salvar_procedimento(*, dados, materiais=None, procedimento=None, usuario=None):
    """Cria/atualiza o catálogo e sincroniza os materiais previstos.

    ``materiais=None`` preserva os itens existentes; uma lista (mesmo vazia)
    substitui integralmente o planejamento.
    """
    if procedimento is None:
        procedimento = Procedimento.objects.create(
            created_by=usuario, updated_by=usuario, **dados
        )
    else:
        for campo, valor in dados.items():
            setattr(procedimento, campo, valor)
        procedimento.updated_by = usuario
        procedimento.save()

    if materiais is not None:
        vistos = set()
        normalizados = []
        for indice, item in enumerate(materiais):
            produto = item.get("produto")
            if produto is None:
                raise ValidationError(
                    {"materiais_previstos": {indice: {"produto": ["Informe o produto."]}}}
                )
            if produto.pk in vistos:
                raise ValidationError(
                    {
                        "materiais_previstos": {
                            indice: {
                                "produto": [
                                    "Este produto já está previsto no procedimento."
                                ]
                            }
                        }
                    }
                )
            vistos.add(produto.pk)
            try:
                _validar_produto_estoque(produto)
            except ValidationError as exc:
                raise ValidationError(
                    {"materiais_previstos": {indice: exc.detail}}
                ) from exc
            try:
                quantidade = _normalizar_quantidade(
                    item.get("quantidade_prevista", 1)
                )
            except ValidationError as exc:
                raise ValidationError(
                    {"materiais_previstos": {indice: exc.detail}}
                ) from exc
            normalizados.append((produto, quantidade, item.get("observacoes") or ""))

        for anterior in procedimento.materiais_previstos.all():
            anterior.soft_delete(user=usuario)

        for produto, quantidade, observacoes in normalizados:
            MaterialPrevistoProcedimento.objects.create(
                procedimento=procedimento,
                produto=produto,
                quantidade_prevista=quantidade,
                observacoes=observacoes,
                created_by=usuario,
                updated_by=usuario,
            )

    return procedimento


def _execucao_existente(chave):
    if not chave:
        return None
    return (
        ExecucaoProcedimento.objects.select_related(
            "pet", "atendimento", "procedimento", "profissional"
        )
        .prefetch_related("equipe", "materiais")
        .filter(chave_idempotencia=chave)
        .first()
    )


@transaction.atomic
def registrar_execucao(
    *,
    procedimento=None,
    pet=None,
    atendimento=None,
    profissional=None,
    equipe=None,
    data_hora=None,
    observacoes="",
    resultado="",
    intercorrencias="",
    materiais=None,
    chave_idempotencia="",
    usuario=None,
):
    """Registra a execução e baixa os materiais como consumo clínico.

    Retorna ``(execucao, criada)``. Com chave de idempotência repetida,
    devolve o registro anterior sem gerar novas movimentações.
    """
    chave = (chave_idempotencia or "").strip() or None
    existente = _execucao_existente(chave)
    if existente is not None:
        return existente, False

    _validar_procedimento(procedimento)

    if atendimento is not None and pet is None:
        pet = atendimento.pet
    if pet is None:
        raise ValidationError({"pet": ["Informe o animal."]})
    if pet.is_deleted:
        raise ValidationError({"pet": ["Animal excluído."]})
    _validar_atendimento(atendimento, pet)
    _validar_profissional(profissional)
    integrantes = _validar_equipe(equipe)
    integrantes = [p for p in integrantes if p.pk != profissional.pk]

    materiais = list(materiais or [])
    dados_materiais = []
    lotes_vistos = set()
    for indice, item in enumerate(materiais):
        try:
            produto, lote, quantidade = _validar_material(
                item.get("produto"), item.get("lote"), item.get("quantidade")
            )
        except ValidationError as exc:
            raise ValidationError({"materiais": {indice: exc.detail}}) from exc
        if lote.pk in lotes_vistos:
            raise ValidationError(
                {
                    "materiais": {
                        indice: {
                            "lote": [
                                "Este lote já foi incluído na execução. "
                                "Some as quantidades em uma única linha."
                            ]
                        }
                    }
                }
            )
        lotes_vistos.add(lote.pk)
        dados_materiais.append(
            {
                "produto": produto,
                "lote": lote,
                "quantidade": quantidade,
                "observacoes": item.get("observacoes") or "",
            }
        )

    dados_execucao = {
        "pet": pet,
        "atendimento": atendimento,
        "procedimento": procedimento,
        "profissional": profissional,
        "data_hora": data_hora or timezone.now(),
        "observacoes": observacoes or "",
        "resultado": resultado or "",
        "intercorrencias": intercorrencias or "",
        "chave_idempotencia": chave,
        "created_by": usuario,
        "updated_by": usuario,
    }

    try:
        with transaction.atomic():
            execucao = ExecucaoProcedimento.objects.create(**dados_execucao)
    except IntegrityError:
        existente = _execucao_existente(chave)
        if existente is not None:
            return existente, False
        raise

    if integrantes:
        execucao.equipe.set(integrantes)

    for dados in dados_materiais:
        material = MaterialUtilizadoProcedimento.objects.create(
            execucao=execucao,
            produto=dados["produto"],
            lote=dados["lote"],
            quantidade=dados["quantidade"],
            observacoes=dados["observacoes"],
            created_by=usuario,
            updated_by=usuario,
        )
        movimentacao = registrar_movimentacao(
            produto=material.produto,
            lote=material.lote,
            tipo=MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
            quantidade=material.quantidade,
            motivo=f"Execução de procedimento {execucao.id}",
            atendimento=atendimento,
            documento_referencia=str(execucao.id),
            usuario=usuario,
        )
        material.movimentacao = movimentacao
        material.save(
            user=usuario,
            update_fields=["movimentacao", "updated_at", "updated_by"],
        )

    return execucao, True


@transaction.atomic
def cancelar_execucao(*, execucao_id, motivo, usuario=None):
    """Cancela a execução e devolve todos os materiais ao lote original."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError(
            {"motivo": ["Informe o motivo do cancelamento da execução."]}
        )

    execucao = (
        ExecucaoProcedimento.objects.select_for_update()
        .select_related("pet", "atendimento", "procedimento")
        .filter(pk=execucao_id, is_deleted=False)
        .first()
    )
    if execucao is None:
        raise ValidationError({"detail": "Execução de procedimento não encontrada."})
    if execucao.status == ExecucaoProcedimento.Status.CANCELADA:
        raise ValidationError({"detail": "Esta execução já foi cancelada."})

    materiais = list(
        MaterialUtilizadoProcedimento.objects.select_for_update()
        .select_related("produto", "lote")
        .filter(execucao=execucao, is_deleted=False)
    )
    for material in materiais:
        estorno = registrar_movimentacao(
            produto=material.produto,
            lote=material.lote,
            tipo=MovimentacaoEstoque.Tipo.DEVOLUCAO,
            quantidade=material.quantidade,
            motivo=f"Estorno da execução {execucao.id}: {motivo}",
            atendimento=execucao.atendimento,
            documento_referencia=str(execucao.id),
            usuario=usuario,
        )
        material.estorno_movimentacao = estorno
        material.save(
            user=usuario,
            update_fields=["estorno_movimentacao", "updated_at", "updated_by"],
        )

    execucao.status = ExecucaoProcedimento.Status.CANCELADA
    execucao.motivo_cancelamento = motivo
    execucao.cancelada_em = timezone.now()
    execucao.cancelada_por = usuario
    execucao.save(
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
    return execucao
