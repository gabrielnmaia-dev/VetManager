"""Regras transacionais de serviços, preços e orçamentos.

Toda operação que mexe em valores roda em transação e recalcula os totais no
backend. Aprovação, recusa, cancelamento e conversão são transições de status
registradas no histórico do orçamento; a conversão cria uma única linha de
``ServicoRealizado`` por item, com chave de idempotência derivada do item.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    HistoricoOrcamento,
    ItemOrcamento,
    Orcamento,
    Servico,
    ServicoRealizado,
)

CENTAVOS = Decimal("0.01")
ZERO = Decimal("0.00")


def _decimal(valor, campo, *, positivo=False):
    if valor is None or valor == "":
        raise ValidationError({campo: ["Informe um valor."]})
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({campo: ["Informe um valor numérico válido."]})
    if not numero.is_finite():
        raise ValidationError({campo: ["Informe um valor numérico válido."]})
    if positivo and numero <= 0:
        raise ValidationError({campo: ["O valor deve ser maior que zero."]})
    if not positivo and numero < 0:
        raise ValidationError({campo: ["O valor não pode ser negativo."]})
    return numero


def _usuario_admin(usuario) -> bool:
    if usuario is None:
        return False
    if getattr(usuario, "is_superuser", False):
        return True
    return usuario.groups.filter(name="admin").exists()


def _validar_servico(servico):
    if servico is None:
        raise ValidationError({"servico": ["Informe o serviço."]})
    if servico.is_deleted:
        raise ValidationError({"servico": ["Serviço excluído."]})
    if servico.situacao != Servico.Situacao.ATIVO:
        raise ValidationError(
            {"servico": ["Serviço inativo não pode ser utilizado."]}
        )


def _validar_pet_tutor(pet, tutor):
    if pet is None:
        raise ValidationError({"pet": ["Informe o animal."]})
    if pet.is_deleted:
        raise ValidationError({"pet": ["Animal excluído."]})
    if tutor is None:
        tutor = pet.tutor
    if tutor is None or tutor.is_deleted:
        raise ValidationError({"tutor": ["Informe o tutor."]})
    if pet.tutor_id != tutor.pk:
        raise ValidationError(
            {"tutor": ["O animal informado pertence a outro tutor."]}
        )
    return pet, tutor


def _validar_atendimento(atendimento, pet):
    if atendimento is None:
        return
    if atendimento.is_deleted:
        raise ValidationError({"atendimento": ["Atendimento excluído."]})
    if pet is not None and atendimento.pet_id != pet.pk:
        raise ValidationError(
            {"atendimento": ["O atendimento pertence a outro animal."]}
        )


def _validar_profissional(profissional, *, obrigatorio=True):
    if profissional is None:
        if obrigatorio:
            raise ValidationError(
                {"profissional": ["Informe o profissional responsável."]}
            )
        return
    if profissional.is_deleted:
        raise ValidationError({"profissional": ["Profissional excluído."]})
    if not profissional.ativo:
        raise ValidationError({"profissional": ["Profissional inativo."]})


def _normalizar_item(item, *, usuario):
    """Valida uma linha e devolve os valores normalizados."""
    if not isinstance(item, dict):
        raise ValidationError({"itens": ["Item inválido."]})

    servico = item.get("servico")
    _validar_servico(servico)

    quantidade = _decimal(item.get("quantidade", 1), "quantidade", positivo=True)
    quantidade = quantidade.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    valor_unitario = item.get("valor_unitario")
    if valor_unitario in (None, ""):
        valor_unitario = servico.preco_base
    valor_unitario = _decimal(valor_unitario, "valor_unitario").quantize(
        CENTAVOS, rounding=ROUND_HALF_UP
    )

    desconto = _decimal(item.get("desconto", ZERO), "desconto").quantize(
        CENTAVOS, rounding=ROUND_HALF_UP
    )

    bruto = (quantidade * valor_unitario).quantize(
        CENTAVOS, rounding=ROUND_HALF_UP
    )
    if desconto > bruto:
        raise ValidationError(
            {"desconto": ["O desconto não pode ser maior que o valor do item."]}
        )

    autorizado_por = None
    motivo = (item.get("desconto_motivo") or "").strip()
    if desconto > 0:
        if not servico.permite_desconto:
            raise ValidationError(
                {"desconto": ["Este serviço não permite desconto."]}
            )
        percentual = (desconto / bruto * 100).quantize(
            CENTAVOS, rounding=ROUND_HALF_UP
        )
        if percentual > servico.desconto_maximo_percentual:
            if not _usuario_admin(usuario):
                raise ValidationError(
                    {
                        "desconto": [
                            "Desconto acima do limite do serviço. "
                            "Somente um administrador pode autorizar."
                        ]
                    }
                )
            if not motivo:
                raise ValidationError(
                    {
                        "desconto_motivo": [
                            "Informe o motivo do desconto autorizado."
                        ]
                    }
                )
        autorizado_por = usuario

    return {
        "servico": servico,
        "quantidade": quantidade,
        "valor_unitario": valor_unitario,
        "desconto": desconto,
        "valor_total": (bruto - desconto).quantize(
            CENTAVOS, rounding=ROUND_HALF_UP
        ),
        "desconto_autorizado_por": autorizado_por,
        "desconto_motivo": motivo,
        "observacoes": item.get("observacoes") or "",
        "valor_bruto": bruto,
    }


def calcular_itens(itens, *, usuario=None):
    """Valida e calcula itens sem persistir. Útil para testes e prévia de tela."""
    normalizados = []
    vistos = set()
    erros = {}
    for indice, item in enumerate(itens or []):
        try:
            normalizado = _normalizar_item(item, usuario=usuario)
        except ValidationError as exc:
            erros[indice] = exc.detail
            continue
        servico = normalizado["servico"]
        if servico.pk in vistos:
            erros[indice] = {
                "servico": ["Este serviço já está no orçamento."]
            }
            continue
        vistos.add(servico.pk)
        normalizados.append(normalizado)
    if erros:
        raise ValidationError({"itens": erros})
    return normalizados


def _totais(itens):
    subtotal = sum((item["valor_bruto"] for item in itens), ZERO)
    desconto = sum((item["desconto"] for item in itens), ZERO)
    total = sum((item["valor_total"] for item in itens), ZERO)
    return (
        subtotal.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        desconto.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
        total.quantize(CENTAVOS, rounding=ROUND_HALF_UP),
    )


def _registrar_historico(orcamento, *, anterior, novo, usuario, observacao=""):
    return HistoricoOrcamento.objects.create(
        orcamento=orcamento,
        status_anterior=anterior or "",
        status_novo=novo,
        usuario=usuario,
        observacao=(observacao or "")[:255],
        created_by=usuario,
        updated_by=usuario,
    )


def _orcamento_por_chave(chave):
    if not chave:
        return None
    return Orcamento.objects.filter(chave_idempotencia=chave).first()


@transaction.atomic
def salvar_orcamento(*, dados, itens, orcamento=None, usuario=None):
    """Cria ou atualiza um orçamento, substituindo itens quando informados.

    ``itens=None`` preserva os itens existentes (usado em edições parciais).
    Uma lista, mesmo vazia, substitui integralmente os itens.
    """
    dados = dict(dados)
    chave = dados.get("chave_idempotencia")
    criado_agora = orcamento is None

    if orcamento is None and chave:
        existente = _orcamento_por_chave(chave)
        if existente is not None:
            existente.criada_agora = False
            return existente

    pet = dados.get("pet")
    tutor = dados.get("tutor")
    atendimento = dados.get("atendimento")
    profissional = dados.get("profissional")
    validade = dados.get("validade")

    pet, tutor = _validar_pet_tutor(pet, tutor)
    _validar_atendimento(atendimento, pet)
    _validar_profissional(profissional, obrigatorio=False)

    if validade is None:
        validade = orcamento.validade if orcamento is not None else None
    if validade is not None and validade < timezone.localdate():
        raise ValidationError(
            {"validade": ["A validade não pode estar no passado."]}
        )

    if orcamento is not None:
        if not orcamento.editavel:
            raise ValidationError(
                {
                    "detail": (
                        "Somente orçamentos em rascunho ou enviados podem "
                        "ser alterados."
                    )
                }
            )
        orcamento.tutor = tutor
        orcamento.pet = pet
        orcamento.atendimento = atendimento
        orcamento.profissional = profissional
        if validade is not None:
            orcamento.validade = validade
        if "data_hora" in dados and dados["data_hora"] is not None:
            orcamento.data_hora = dados["data_hora"]
        if "observacoes" in dados:
            orcamento.observacoes = dados["observacoes"] or ""
        orcamento.updated_by = usuario
    else:
        campos = {
            "tutor": tutor,
            "pet": pet,
            "atendimento": atendimento,
            "profissional": profissional,
            "data_hora": dados.get("data_hora") or timezone.now(),
            "observacoes": dados.get("observacoes") or "",
            "chave_idempotencia": chave,
            "created_by": usuario,
            "updated_by": usuario,
        }
        if validade is not None:
            campos["validade"] = validade
        try:
            with transaction.atomic():
                orcamento = Orcamento.objects.create(**campos)
        except IntegrityError:
            existente = _orcamento_por_chave(chave)
            if existente is not None:
                existente.criada_agora = False
                return existente
            raise

    if itens is not None:
        normalizados = calcular_itens(itens, usuario=usuario)
        for anterior in orcamento.itens.filter(is_deleted=False):
            anterior.soft_delete(user=usuario)
        for item in normalizados:
            ItemOrcamento.objects.create(
                orcamento=orcamento,
                servico=item["servico"],
                quantidade=item["quantidade"],
                valor_unitario=item["valor_unitario"],
                desconto=item["desconto"],
                valor_total=item["valor_total"],
                desconto_autorizado_por=item["desconto_autorizado_por"],
                desconto_motivo=item["desconto_motivo"],
                observacoes=item["observacoes"],
                created_by=usuario,
                updated_by=usuario,
            )

    itens_ativos = list(orcamento.itens.filter(is_deleted=False))
    subtotal = sum((item.valor_unitario * item.quantidade for item in itens_ativos), ZERO)
    desconto = sum((item.desconto for item in itens_ativos), ZERO)
    total = sum((item.valor_total for item in itens_ativos), ZERO)
    orcamento.subtotal = subtotal.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    orcamento.valor_desconto = desconto.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    orcamento.valor_total = total.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    orcamento.save(
        update_fields=[
            "tutor",
            "pet",
            "atendimento",
            "profissional",
            "validade",
            "data_hora",
            "observacoes",
            "subtotal",
            "valor_desconto",
            "valor_total",
            "updated_by",
            "updated_at",
        ]
    )

    if criado_agora:
        _registrar_historico(
            orcamento,
            anterior="",
            novo=Orcamento.Status.RASCUNHO,
            usuario=usuario,
            observacao="Orçamento criado.",
        )
    elif orcamento.status in {
        Orcamento.Status.RASCUNHO,
        Orcamento.Status.ENVIADO,
    }:
        _registrar_historico(
            orcamento,
            anterior=orcamento.status,
            novo=orcamento.status,
            usuario=usuario,
            observacao="Orçamento atualizado.",
        )
    orcamento.criada_agora = criado_agora

    return orcamento


def _orcamento_bloqueado(orcamento_id):
    orcamento = (
        Orcamento.objects.select_for_update()
        .select_related("pet", "pet__tutor", "tutor", "atendimento", "profissional")
        .filter(pk=orcamento_id, is_deleted=False)
        .first()
    )
    if orcamento is None:
        raise ValidationError({"detail": "Orçamento não encontrado."})
    return orcamento


def _itens_ativos(orcamento):
    return list(
        orcamento.itens.filter(is_deleted=False).select_related("servico")
    )


@transaction.atomic
def enviar_orcamento(*, orcamento_id, usuario=None, observacao=""):
    orcamento = _orcamento_bloqueado(orcamento_id)
    if orcamento.status != Orcamento.Status.RASCUNHO:
        raise ValidationError(
            {"detail": "Somente orçamentos em rascunho podem ser enviados."}
        )
    if not _itens_ativos(orcamento):
        raise ValidationError(
            {"itens": ["Inclua pelo menos um serviço antes de enviar."]}
        )
    if orcamento.validade < timezone.localdate():
        raise ValidationError({"validade": ["O orçamento está vencido."]})
    anterior = orcamento.status
    orcamento.status = Orcamento.Status.ENVIADO
    orcamento.updated_by = usuario
    orcamento.save(update_fields=["status", "updated_by", "updated_at"])
    _registrar_historico(
        orcamento,
        anterior=anterior,
        novo=orcamento.status,
        usuario=usuario,
        observacao=observacao or "Orçamento enviado ao tutor.",
    )
    return orcamento


@transaction.atomic
def aprovar_orcamento(*, orcamento_id, usuario=None, observacao=""):
    orcamento = _orcamento_bloqueado(orcamento_id)
    if orcamento.status not in {
        Orcamento.Status.RASCUNHO,
        Orcamento.Status.ENVIADO,
    }:
        raise ValidationError(
            {"detail": "Somente orçamentos pendentes podem ser aprovados."}
        )
    if not _itens_ativos(orcamento):
        raise ValidationError(
            {"itens": ["Inclua pelo menos um serviço antes de aprovar."]}
        )
    if orcamento.validade < timezone.localdate():
        raise ValidationError({"validade": ["O orçamento está vencido."]})
    anterior = orcamento.status
    orcamento.status = Orcamento.Status.APROVADO
    orcamento.aprovado_em = timezone.now()
    orcamento.decidido_por = usuario
    orcamento.updated_by = usuario
    orcamento.save(
        update_fields=[
            "status",
            "aprovado_em",
            "decidido_por",
            "updated_by",
            "updated_at",
        ]
    )
    _registrar_historico(
        orcamento,
        anterior=anterior,
        novo=orcamento.status,
        usuario=usuario,
        observacao=observacao or "Orçamento aprovado.",
    )
    return orcamento


@transaction.atomic
def recusar_orcamento(*, orcamento_id, motivo, usuario=None):
    orcamento = _orcamento_bloqueado(orcamento_id)
    if orcamento.status not in {
        Orcamento.Status.RASCUNHO,
        Orcamento.Status.ENVIADO,
    }:
        raise ValidationError(
            {"detail": "Somente orçamentos pendentes podem ser recusados."}
        )
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError({"motivo": ["Informe o motivo da recusa."]})
    anterior = orcamento.status
    orcamento.status = Orcamento.Status.RECUSADO
    orcamento.motivo_recusa = motivo[:255]
    orcamento.recusado_em = timezone.now()
    orcamento.decidido_por = usuario
    orcamento.updated_by = usuario
    orcamento.save(
        update_fields=[
            "status",
            "motivo_recusa",
            "recusado_em",
            "decidido_por",
            "updated_by",
            "updated_at",
        ]
    )
    _registrar_historico(
        orcamento,
        anterior=anterior,
        novo=orcamento.status,
        usuario=usuario,
        observacao=f"Orçamento recusado: {motivo}",
    )
    return orcamento


@transaction.atomic
def cancelar_orcamento(*, orcamento_id, motivo="", usuario=None):
    orcamento = _orcamento_bloqueado(orcamento_id)
    if orcamento.status in {
        Orcamento.Status.CONVERTIDO,
        Orcamento.Status.RECUSADO,
        Orcamento.Status.CANCELADO,
    }:
        raise ValidationError(
            {"detail": "Este orçamento não pode mais ser cancelado."}
        )
    anterior = orcamento.status
    orcamento.status = Orcamento.Status.CANCELADO
    orcamento.cancelado_em = timezone.now()
    orcamento.updated_by = usuario
    orcamento.save(
        update_fields=["status", "cancelado_em", "updated_by", "updated_at"]
    )
    _registrar_historico(
        orcamento,
        anterior=anterior,
        novo=orcamento.status,
        usuario=usuario,
        observacao=(motivo or "Orçamento cancelado.")[:255],
    )
    return orcamento


@transaction.atomic
def converter_orcamento(
    *, orcamento_id, usuario=None, atendimento=None, profissional=None, data_hora=None
):
    """Converte um orçamento aprovado em serviços realizados.

    A operação é idempotente: repetir a chamada depois da conversão devolve o
    mesmo orçamento sem criar novas linhas.
    """
    orcamento = _orcamento_bloqueado(orcamento_id)
    if orcamento.status == Orcamento.Status.CONVERTIDO:
        orcamento.criada_agora = False
        return orcamento
    if orcamento.status != Orcamento.Status.APROVADO:
        raise ValidationError(
            {"detail": "Somente orçamentos aprovados podem ser convertidos."}
        )

    itens = _itens_ativos(orcamento)
    if not itens:
        raise ValidationError({"itens": ["O orçamento não possui itens."]})

    atendimento = atendimento or orcamento.atendimento
    if atendimento is None:
        raise ValidationError(
            {
                "atendimento": [
                    "Informe o atendimento para converter o orçamento."
                ]
            }
        )
    _validar_atendimento(atendimento, orcamento.pet)

    profissional = profissional or orcamento.profissional
    _validar_profissional(profissional)

    data_hora = data_hora or timezone.now()

    for item in itens:
        ServicoRealizado.objects.get_or_create(
            orcamento_item=item,
            defaults={
                "atendimento": atendimento,
                "pet": orcamento.pet,
                "servico": item.servico,
                "profissional": profissional,
                "quantidade": item.quantidade,
                "valor_unitario": item.valor_unitario,
                "desconto": item.desconto,
                "valor_total": item.valor_total,
                "desconto_autorizado_por": item.desconto_autorizado_por,
                "desconto_motivo": item.desconto_motivo,
                "data_hora": data_hora,
                "observacoes": item.observacoes,
                "chave_idempotencia": f"orcamento:{orcamento.pk}:{item.pk}",
                "created_by": usuario,
                "updated_by": usuario,
            },
        )

    anterior = orcamento.status
    orcamento.status = Orcamento.Status.CONVERTIDO
    orcamento.convertido_em = timezone.now()
    orcamento.updated_by = usuario
    orcamento.save(
        update_fields=[
            "status",
            "convertido_em",
            "updated_by",
            "updated_at",
        ]
    )
    _registrar_historico(
        orcamento,
        anterior=anterior,
        novo=orcamento.status,
        usuario=usuario,
        observacao=(
            f"Orçamento convertido em {len(itens)} serviço(s) realizado(s)."
        ),
    )
    orcamento.criada_agora = False
    return orcamento


def _servico_realizado_por_chave(chave):
    if not chave:
        return None
    return ServicoRealizado.objects.filter(chave_idempotencia=chave).first()


@transaction.atomic
def registrar_servico_realizado(*, dados, usuario=None):
    """Registra um serviço executado e calcula o total no backend."""
    dados = dict(dados)
    chave = dados.get("chave_idempotencia")
    if chave:
        existente = _servico_realizado_por_chave(chave)
        if existente is not None:
            existente.criada_agora = False
            return existente

    atendimento = dados.get("atendimento")
    if atendimento is None:
        raise ValidationError({"atendimento": ["Informe o atendimento."]})
    pet = dados.get("pet") or getattr(atendimento, "pet", None)
    servico = dados.get("servico")
    profissional = dados.get("profissional")

    _validar_servico(servico)
    _validar_pet_tutor(pet, getattr(pet, "tutor", None))
    _validar_atendimento(atendimento, pet)
    _validar_profissional(profissional)

    normalizado = _normalizar_item(
        {
            "servico": servico,
            "quantidade": dados.get("quantidade", 1),
            "valor_unitario": dados.get("valor_unitario"),
            "desconto": dados.get("desconto", ZERO),
            "desconto_motivo": dados.get("desconto_motivo", ""),
            "observacoes": dados.get("observacoes", ""),
        },
        usuario=usuario,
    )

    try:
        with transaction.atomic():
            registro = ServicoRealizado.objects.create(
                atendimento=atendimento,
                pet=pet,
                servico=servico,
                profissional=profissional,
                quantidade=normalizado["quantidade"],
                valor_unitario=normalizado["valor_unitario"],
                desconto=normalizado["desconto"],
                valor_total=normalizado["valor_total"],
                desconto_autorizado_por=normalizado[
                    "desconto_autorizado_por"
                ],
                desconto_motivo=normalizado["desconto_motivo"],
                data_hora=dados.get("data_hora") or timezone.now(),
                observacoes=normalizado["observacoes"],
                chave_idempotencia=chave,
                created_by=usuario,
                updated_by=usuario,
            )
    except IntegrityError:
        existente = _servico_realizado_por_chave(chave)
        if existente is not None:
            existente.criada_agora = False
            return existente
        raise

    registro.criada_agora = True
    return registro
