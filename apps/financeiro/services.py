"""Regras transacionais de contas a receber, pagamentos e caixa.

Nenhum pagamento é apagado: o estorno gera movimentos inversos nas parcelas,
na conta e no caixa (quando aplicável), mantendo a trilha contábil. Todas as
operações de escrita usam ``select_for_update`` e chave de idempotência para
suportar duplo clique e repetição de requisição.
"""

import calendar
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    AplicacaoPagamento,
    Caixa,
    ContaReceber,
    FormaPagamento,
    HistoricoContaReceber,
    MovimentacaoCaixa,
    Pagamento,
    ParcelaContaReceber,
)

CENTAVOS = Decimal("0.01")
ZERO = Decimal("0.00")


def _decimal(valor, campo, *, positivo=False, nao_negativo=True):
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
    if nao_negativo and numero < 0:
        raise ValidationError({campo: ["O valor não pode ser negativo."]})
    return numero.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def _somar_meses(data: date, meses: int) -> date:
    total = data.month - 1 + meses
    ano = data.year + total // 12
    mes = total % 12 + 1
    dia = min(data.day, calendar.monthrange(ano, mes)[1])
    return date(ano, mes, dia)


def _distribuir_parcelas(valor, numero_parcelas, primeiro_vencimento):
    if numero_parcelas is None:
        numero_parcelas = 1
    try:
        numero_parcelas = int(numero_parcelas)
    except (TypeError, ValueError):
        raise ValidationError(
            {"numero_parcelas": ["Informe um número de parcelas válido."]}
        )
    if numero_parcelas < 1 or numero_parcelas > 60:
        raise ValidationError(
            {"numero_parcelas": ["O número de parcelas deve ficar entre 1 e 60."]}
        )

    base = (valor / numero_parcelas).quantize(CENTAVOS, rounding=ROUND_DOWN)
    resto = (valor - base * numero_parcelas).quantize(CENTAVOS)
    parcelas = []
    for indice in range(numero_parcelas):
        valor_parcela = base
        if indice == numero_parcelas - 1:
            valor_parcela = (valor_parcela + resto).quantize(CENTAVOS)
        parcelas.append(
            {
                "numero": indice + 1,
                "vencimento": _somar_meses(primeiro_vencimento, indice),
                "valor": valor_parcela,
            }
        )
    return parcelas


def _normalizar_parcelas_entrada(parcelas, valor_total):
    normalizadas = []
    for indice, item in enumerate(parcelas):
        if not isinstance(item, dict):
            raise ValidationError({"parcelas_entrada": ["Parcela inválida."]})
        vencimento = item.get("vencimento")
        if vencimento is None:
            raise ValidationError(
                {"parcelas_entrada": {indice: {"vencimento": ["Informe o vencimento."]}}}
            )
        valor = _decimal(
            item.get("valor"), "valor", positivo=True
        )
        normalizadas.append(
            {
                "numero": indice + 1,
                "vencimento": vencimento,
                "valor": valor,
            }
        )
    if not normalizadas:
        raise ValidationError(
            {"parcelas_entrada": ["Informe pelo menos uma parcela."]}
        )
    soma = sum((item["valor"] for item in normalizadas), ZERO)
    if soma != valor_total:
        raise ValidationError(
            {
                "parcelas_entrada": [
                    "A soma das parcelas deve ser igual ao valor da conta."
                ]
            }
        )
    return normalizadas


def _status_por_saldo(valor_pago, saldo):
    if saldo <= 0:
        return ContaReceber.Status.PAGA
    if valor_pago > 0:
        return ContaReceber.Status.PARCIAL
    return ContaReceber.Status.ABERTA


def _recalcular_parcela(parcela):
    if parcela.status == ParcelaContaReceber.Status.CANCELADA:
        return parcela
    parcela.saldo = (parcela.valor - parcela.valor_pago).quantize(CENTAVOS)
    if parcela.saldo < 0:
        parcela.saldo = ZERO
    if parcela.saldo <= 0:
        parcela.status = ParcelaContaReceber.Status.PAGA
    elif parcela.valor_pago > 0:
        parcela.status = ParcelaContaReceber.Status.PARCIAL
    else:
        parcela.status = ParcelaContaReceber.Status.ABERTA
    parcela.save(update_fields=["valor_pago", "saldo", "status", "updated_at"])
    return parcela


def _recalcular_conta(conta, *, usuario=None):
    if conta.status == ContaReceber.Status.CANCELADA:
        return conta
    parcelas = list(
        conta.parcelas.filter(is_deleted=False).exclude(
            status=ParcelaContaReceber.Status.CANCELADA
        )
    )
    total = sum((parcela.valor for parcela in parcelas), ZERO)
    pago = sum((parcela.valor_pago for parcela in parcelas), ZERO)
    conta.valor_pago = pago.quantize(CENTAVOS)
    conta.saldo = (total - pago).quantize(CENTAVOS)
    if conta.saldo < 0:
        conta.saldo = ZERO
    conta.status = _status_por_saldo(conta.valor_pago, conta.saldo)
    conta.updated_by = usuario
    conta.save(
        update_fields=[
            "valor_pago",
            "saldo",
            "status",
            "updated_by",
            "updated_at",
        ]
    )
    return conta


def _registrar_historico(conta, *, anterior, novo, usuario, observacao=""):
    return HistoricoContaReceber.objects.create(
        conta=conta,
        status_anterior=anterior or "",
        status_novo=novo,
        valor_pago=conta.valor_pago,
        saldo=conta.saldo,
        usuario=usuario,
        observacao=(observacao or "")[:255],
        created_by=usuario,
        updated_by=usuario,
    )


def _conta_por_chave(chave):
    if not chave:
        return None
    return ContaReceber.objects.filter(chave_idempotencia=chave).first()


@transaction.atomic
def criar_conta_receber(
    *,
    dados,
    numero_parcelas=1,
    parcelas_entrada=None,
    usuario=None,
):
    """Cria o lançamento, as parcelas e o histórico inicial."""
    dados = dict(dados)
    chave = dados.get("chave_idempotencia") or None
    if chave:
        existente = _conta_por_chave(chave)
        if existente is not None:
            existente.criada_agora = False
            return existente

    tutor = dados.get("tutor")
    atendimento = dados.get("atendimento")
    if atendimento is not None:
        if atendimento.is_deleted:
            raise ValidationError({"atendimento": ["Atendimento excluído."]})
        if tutor is None:
            tutor = atendimento.pet.tutor
        elif atendimento.pet.tutor_id != tutor.pk:
            raise ValidationError(
                {"atendimento": ["O atendimento pertence a outro tutor."]}
            )
    if tutor is None or tutor.is_deleted:
        raise ValidationError({"tutor": ["Informe o tutor responsável."]})

    descricao = (dados.get("descricao") or "").strip()
    if not descricao:
        raise ValidationError({"descricao": ["Informe a descrição da conta."]})

    valor = _decimal(dados.get("valor"), "valor", positivo=True)
    data_emissao = dados.get("data_emissao") or timezone.localdate()
    vencimento = dados.get("vencimento") or _somar_meses(data_emissao, 1)

    if parcelas_entrada:
        parcelas = _normalizar_parcelas_entrada(parcelas_entrada, valor)
    else:
        parcelas = _distribuir_parcelas(valor, numero_parcelas, vencimento)

    try:
        with transaction.atomic():
            conta = ContaReceber.objects.create(
                tutor=tutor,
                atendimento=atendimento,
                descricao=descricao[:255],
                valor=valor,
                data_emissao=data_emissao,
                vencimento=parcelas[0]["vencimento"],
                status=ContaReceber.Status.ABERTA,
                valor_pago=ZERO,
                saldo=valor,
                observacoes=dados.get("observacoes") or "",
                chave_idempotencia=chave,
                created_by=usuario,
                updated_by=usuario,
            )
    except IntegrityError:
        existente = _conta_por_chave(chave)
        if existente is not None:
            existente.criada_agora = False
            return existente
        raise
    for parcela in parcelas:
        ParcelaContaReceber.objects.create(
            conta=conta,
            numero=parcela["numero"],
            vencimento=parcela["vencimento"],
            valor=parcela["valor"],
            valor_pago=ZERO,
            saldo=parcela["valor"],
            status=ParcelaContaReceber.Status.ABERTA,
            created_by=usuario,
            updated_by=usuario,
        )

    _registrar_historico(
        conta,
        anterior="",
        novo=ContaReceber.Status.ABERTA,
        usuario=usuario,
        observacao="Conta a receber criada.",
    )
    conta.criada_agora = True
    return conta


@transaction.atomic
def cancelar_conta_receber(*, conta_id, motivo, usuario=None):
    conta = (
        ContaReceber.objects.select_for_update()
        .select_related("tutor")
        .filter(pk=conta_id, is_deleted=False)
        .first()
    )
    if conta is None:
        raise ValidationError({"detail": "Conta a receber não encontrada."})
    if conta.status == ContaReceber.Status.CANCELADA:
        raise ValidationError({"detail": "Esta conta já está cancelada."})
    if Pagamento.objects.filter(
        conta=conta, status=Pagamento.Status.CONFIRMADO
    ).exists():
        raise ValidationError(
            {"detail": "Estorne os pagamentos antes de cancelar a conta."}
        )
    motivo = (motivo or "").strip()
    anterior = conta.status
    conta.status = ContaReceber.Status.CANCELADA
    conta.saldo = ZERO
    conta.cancelado_em = timezone.now()
    conta.motivo_cancelamento = motivo[:255]
    conta.cancelado_por = usuario
    conta.updated_by = usuario
    conta.save(
        update_fields=[
            "status",
            "saldo",
            "cancelado_em",
            "motivo_cancelamento",
            "cancelado_por",
            "updated_by",
            "updated_at",
        ]
    )
    for parcela in conta.parcelas.filter(is_deleted=False):
        parcela.status = ParcelaContaReceber.Status.CANCELADA
        parcela.saldo = ZERO
        parcela.updated_by = usuario
        parcela.save(update_fields=["status", "saldo", "updated_by", "updated_at"])
    _registrar_historico(
        conta,
        anterior=anterior,
        novo=conta.status,
        usuario=usuario,
        observacao=f"Conta cancelada. {motivo}".strip(),
    )
    return conta


def _forma_valida(forma):
    if forma is None:
        raise ValidationError({"forma_pagamento": ["Informe a forma de pagamento."]})
    if forma.is_deleted:
        raise ValidationError({"forma_pagamento": ["Forma de pagamento excluída."]})
    if not forma.ativo:
        raise ValidationError({"forma_pagamento": ["Forma de pagamento inativa."]})


def _pagamento_por_chave(chave):
    if not chave:
        return None
    return Pagamento.objects.filter(chave_idempotencia=chave).first()


def _caixa_para_pagamento(caixa):
    if caixa is None:
        caixa = (
            Caixa.objects.select_for_update()
            .filter(status=Caixa.Status.ABERTO, is_deleted=False)
            .order_by("-data_abertura")
            .first()
        )
    else:
        caixa = (
            Caixa.objects.select_for_update()
            .filter(pk=caixa.pk, is_deleted=False)
            .first()
        )
        if caixa is None:
            raise ValidationError({"caixa": ["Caixa não encontrado."]})
    if caixa is not None and caixa.status != Caixa.Status.ABERTO:
        raise ValidationError({"caixa": ["O caixa informado está fechado."]})
    return caixa


@transaction.atomic
def registrar_pagamento(
    *,
    conta_id,
    forma_pagamento,
    valor,
    parcela=None,
    data_hora=None,
    observacoes="",
    caixa=None,
    chave_idempotencia=None,
    usuario=None,
):
    """Registra um pagamento e distribui o valor entre as parcelas.

    Se ``parcela`` for informada, o pagamento fica restrito a ela. Caso
    contrário, o valor é aplicado nas parcelas mais antigas primeiro.
    """
    chave_idempotencia = chave_idempotencia or None
    if chave_idempotencia:
        existente = _pagamento_por_chave(chave_idempotencia)
        if existente is not None:
            existente.criada_agora = False
            return existente

    _forma_valida(forma_pagamento)
    valor = _decimal(valor, "valor", positivo=True)

    conta = (
        ContaReceber.objects.select_for_update()
        .select_related("tutor")
        .filter(pk=conta_id, is_deleted=False)
        .first()
    )
    if conta is None:
        raise ValidationError({"conta": ["Conta a receber não encontrada."]})
    if conta.status == ContaReceber.Status.CANCELADA:
        raise ValidationError({"conta": ["Esta conta está cancelada."]})
    if conta.saldo <= 0:
        raise ValidationError({"conta": ["Esta conta não possui saldo em aberto."]})
    if valor > conta.saldo:
        raise ValidationError(
            {"valor": ["O pagamento não pode ser maior que o saldo da conta."]}
        )

    parcelas = list(
        ParcelaContaReceber.objects.select_for_update()
        .filter(
            conta=conta,
            is_deleted=False,
            status__in=[
                ParcelaContaReceber.Status.ABERTA,
                ParcelaContaReceber.Status.PARCIAL,
            ],
        )
        .order_by("vencimento", "numero")
    )
    if parcela is not None:
        parcela = next(
            (item for item in parcelas if item.pk == parcela.pk), None
        )
        if parcela is None:
            raise ValidationError(
                {"parcela": ["A parcela informada não está em aberto."]}
            )
        if valor > parcela.saldo:
            raise ValidationError(
                {"valor": ["O pagamento não pode ser maior que o saldo da parcela."]}
            )
        alocacoes = [(parcela, valor)]
    else:
        restante = valor
        alocacoes = []
        for item in parcelas:
            if restante <= 0:
                break
            aplicado = min(restante, item.saldo)
            if aplicado > 0:
                alocacoes.append((item, aplicado))
                restante -= aplicado
        if restante > 0:
            raise ValidationError(
                {"valor": ["O valor excede o saldo das parcelas em aberto."]}
            )

    caixa_obj = _caixa_para_pagamento(caixa)
    try:
        with transaction.atomic():
            pagamento = Pagamento.objects.create(
                conta=conta,
                parcela=parcela,
                forma_pagamento=forma_pagamento,
                valor=valor,
                data_hora=data_hora or timezone.now(),
                observacoes=observacoes or "",
                caixa=caixa_obj,
                chave_idempotencia=chave_idempotencia,
                created_by=usuario,
                updated_by=usuario,
            )
    except IntegrityError:
        existente = _pagamento_por_chave(chave_idempotencia)
        if existente is not None:
            existente.criada_agora = False
            return existente
        raise

    for item, aplicado in alocacoes:
        AplicacaoPagamento.objects.create(
            pagamento=pagamento,
            parcela=item,
            valor=aplicado,
            created_by=usuario,
            updated_by=usuario,
        )
        item.valor_pago = (item.valor_pago + aplicado).quantize(CENTAVOS)
        _recalcular_parcela(item)

    anterior = conta.status
    _recalcular_conta(conta, usuario=usuario)
    _registrar_historico(
        conta,
        anterior=anterior,
        novo=conta.status,
        usuario=usuario,
        observacao=(
            f"Pagamento de R$ {valor} via {forma_pagamento.nome}."
        ),
    )

    if caixa_obj is not None:
        MovimentacaoCaixa.objects.create(
            caixa=caixa_obj,
            tipo=MovimentacaoCaixa.Tipo.ENTRADA,
            valor=valor,
            descricao=f"Recebimento — {conta.descricao}"[:255],
            forma_pagamento=forma_pagamento,
            pagamento=pagamento,
            data_hora=pagamento.data_hora,
            chave_idempotencia=f"pagamento:{pagamento.pk}",
            created_by=usuario,
            updated_by=usuario,
        )

    pagamento.criada_agora = True
    return pagamento


@transaction.atomic
def estornar_pagamento(*, pagamento_id, motivo, usuario=None):
    pagamento = (
        Pagamento.objects.select_for_update()
        .select_related("conta", "forma_pagamento", "caixa")
        .filter(pk=pagamento_id, is_deleted=False)
        .first()
    )
    if pagamento is None:
        raise ValidationError({"detail": "Pagamento não encontrado."})
    if pagamento.status == Pagamento.Status.ESTORNADO:
        raise ValidationError({"detail": "Este pagamento já foi estornado."})
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError({"motivo": ["Informe o motivo do estorno."]})

    conta = (
        ContaReceber.objects.select_for_update()
        .filter(pk=pagamento.conta_id, is_deleted=False)
        .first()
    )
    if conta is None:
        raise ValidationError({"detail": "Conta a receber não encontrada."})

    aplicacoes = list(
        pagamento.aplicacoes.select_related("parcela")
        .filter(is_deleted=False)
        .order_by("created_at")
    )
    for aplicacao in aplicacoes:
        parcela = (
            ParcelaContaReceber.objects.select_for_update()
            .filter(pk=aplicacao.parcela_id)
            .first()
        )
        if parcela is None:
            continue
        parcela.valor_pago = (parcela.valor_pago - aplicacao.valor).quantize(
            CENTAVOS
        )
        if parcela.valor_pago < 0:
            parcela.valor_pago = ZERO
        _recalcular_parcela(parcela)

    anterior = conta.status
    _recalcular_conta(conta, usuario=usuario)
    pagamento.status = Pagamento.Status.ESTORNADO
    pagamento.estornado_em = timezone.now()
    pagamento.estornado_por = usuario
    pagamento.motivo_estorno = motivo[:255]
    pagamento.updated_by = usuario
    pagamento.save(
        update_fields=[
            "status",
            "estornado_em",
            "estornado_por",
            "motivo_estorno",
            "updated_by",
            "updated_at",
        ]
    )
    _registrar_historico(
        conta,
        anterior=anterior,
        novo=conta.status,
        usuario=usuario,
        observacao=f"Estorno de R$ {pagamento.valor}: {motivo}",
    )

    if pagamento.caixa_id is not None:
        caixa = Caixa.objects.filter(pk=pagamento.caixa_id).first()
        if caixa is not None and caixa.status == Caixa.Status.ABERTO:
            MovimentacaoCaixa.objects.create(
                caixa=caixa,
                tipo=MovimentacaoCaixa.Tipo.SAIDA,
                valor=pagamento.valor,
                descricao=f"Estorno — {conta.descricao}"[:255],
                forma_pagamento=pagamento.forma_pagamento,
                pagamento=pagamento,
                chave_idempotencia=f"estorno-pagamento:{pagamento.pk}",
                created_by=usuario,
                updated_by=usuario,
            )
    return pagamento


@transaction.atomic
def abrir_caixa(
    *,
    descricao,
    valor_abertura,
    observacoes="",
    usuario=None,
    chave_idempotencia=None,
):
    chave_idempotencia = chave_idempotencia or None
    if chave_idempotencia:
        existente = Caixa.objects.filter(
            chave_idempotencia=chave_idempotencia
        ).first()
        if existente is not None:
            existente.criada_agora = False
            return existente

    aberto = (
        Caixa.objects.select_for_update()
        .filter(status=Caixa.Status.ABERTO, is_deleted=False)
        .first()
    )
    if aberto is not None:
        raise ValidationError(
            {"detail": "Já existe um caixa aberto. Feche-o antes de abrir outro."}
        )

    descricao = (descricao or "").strip()
    if not descricao:
        raise ValidationError({"descricao": ["Informe a descrição do caixa."]})
    valor_abertura = _decimal(valor_abertura or ZERO, "valor_abertura")

    caixa = Caixa.objects.create(
        descricao=descricao[:150],
        status=Caixa.Status.ABERTO,
        data_abertura=timezone.now(),
        valor_abertura=valor_abertura,
        observacoes=observacoes or "",
        usuario_abertura=usuario,
        chave_idempotencia=chave_idempotencia,
        created_by=usuario,
        updated_by=usuario,
    )
    caixa.criada_agora = True
    return caixa


@transaction.atomic
def registrar_movimentacao_caixa(
    *,
    caixa_id,
    tipo,
    valor,
    descricao,
    forma_pagamento=None,
    data_hora=None,
    chave_idempotencia=None,
    usuario=None,
):
    chave_idempotencia = chave_idempotencia or None
    if chave_idempotencia:
        existente = MovimentacaoCaixa.objects.filter(
            chave_idempotencia=chave_idempotencia
        ).first()
        if existente is not None:
            existente.criada_agora = False
            return existente

    caixa = (
        Caixa.objects.select_for_update()
        .filter(pk=caixa_id, is_deleted=False)
        .first()
    )
    if caixa is None:
        raise ValidationError({"caixa": ["Caixa não encontrado."]})
    if caixa.status != Caixa.Status.ABERTO:
        raise ValidationError({"caixa": ["O caixa está fechado."]})

    if tipo not in dict(MovimentacaoCaixa.Tipo.choices):
        raise ValidationError({"tipo": ["Tipo de movimentação inválido."]})
    if tipo == MovimentacaoCaixa.Tipo.AJUSTE:
        valor = _decimal(valor, "valor", positivo=False, nao_negativo=False)
        if valor == 0:
            raise ValidationError({"valor": ["O ajuste não pode ser zero."]})
    else:
        valor = _decimal(valor, "valor", positivo=True)

    descricao = (descricao or "").strip()
    if not descricao:
        raise ValidationError({"descricao": ["Informe a descrição."]})
    if forma_pagamento is not None:
        _forma_valida(forma_pagamento)

    try:
        with transaction.atomic():
            movimentacao = MovimentacaoCaixa.objects.create(
                caixa=caixa,
                tipo=tipo,
                valor=valor,
                descricao=descricao[:255],
                forma_pagamento=forma_pagamento,
                data_hora=data_hora or timezone.now(),
                chave_idempotencia=chave_idempotencia,
                created_by=usuario,
                updated_by=usuario,
            )
    except IntegrityError:
        existente = MovimentacaoCaixa.objects.filter(
            chave_idempotencia=chave_idempotencia
        ).first()
        if existente is not None:
            existente.criada_agora = False
            return existente
        raise
    movimentacao.criada_agora = True
    return movimentacao


def resumo_caixa(caixa):
    """Totais do caixa calculados a partir do livro-razão."""
    agregados = caixa.movimentacoes.filter(is_deleted=False).aggregate(
        entradas=Sum("valor", filter=Q(tipo=MovimentacaoCaixa.Tipo.ENTRADA)),
        saidas=Sum("valor", filter=Q(tipo=MovimentacaoCaixa.Tipo.SAIDA)),
        ajustes=Sum("valor", filter=Q(tipo=MovimentacaoCaixa.Tipo.AJUSTE)),
    )
    entradas = agregados["entradas"] or ZERO
    saidas = agregados["saidas"] or ZERO
    ajustes = agregados["ajustes"] or ZERO
    saldo = (caixa.valor_abertura + entradas - saidas + ajustes).quantize(
        CENTAVOS
    )
    return {
        "valor_abertura": caixa.valor_abertura,
        "entradas": entradas.quantize(CENTAVOS),
        "saidas": saidas.quantize(CENTAVOS),
        "ajustes": ajustes.quantize(CENTAVOS),
        "saldo_sistema": saldo,
        "quantidade_movimentacoes": caixa.movimentacoes.filter(
            is_deleted=False
        ).count(),
    }


@transaction.atomic
def fechar_caixa(
    *,
    caixa_id,
    valor_fechamento_informado,
    observacoes="",
    usuario=None,
):
    caixa = (
        Caixa.objects.select_for_update()
        .filter(pk=caixa_id, is_deleted=False)
        .first()
    )
    if caixa is None:
        raise ValidationError({"caixa": ["Caixa não encontrado."]})
    if caixa.status != Caixa.Status.ABERTO:
        raise ValidationError({"detail": "Este caixa já está fechado."})
    informado = _decimal(
        valor_fechamento_informado, "valor_fechamento_informado"
    )
    resumo = resumo_caixa(caixa)
    sistema = resumo["saldo_sistema"]
    caixa.status = Caixa.Status.FECHADO
    caixa.data_fechamento = timezone.now()
    caixa.valor_fechamento_informado = informado
    caixa.valor_fechamento_sistema = sistema
    caixa.diferenca = (informado - sistema).quantize(CENTAVOS)
    caixa.usuario_fechamento = usuario
    caixa.observacoes_fechamento = observacoes or ""
    caixa.updated_by = usuario
    caixa.save(
        update_fields=[
            "status",
            "data_fechamento",
            "valor_fechamento_informado",
            "valor_fechamento_sistema",
            "diferenca",
            "usuario_fechamento",
            "observacoes_fechamento",
            "updated_by",
            "updated_at",
        ]
    )
    caixa.resumo = resumo
    return caixa
