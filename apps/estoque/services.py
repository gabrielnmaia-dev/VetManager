"""Regras transacionais do estoque clínico e comercial.

Toda alteração de saldo passa por aqui. Views e serializers apenas validam o
payload e delegam para estas funções, que:

* rodam dentro de ``transaction.atomic``;
* bloqueiam o lote com ``select_for_update()`` antes de calcular o saldo;
* registram uma movimentação imutável com saldo anterior/posterior;
* aplicam FEFO quando a saída não indica um lote específico.
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    Inventario,
    ItemInventario,
    Lote,
    MovimentacaoEstoque,
    Produto,
)

ZERO = Decimal("0")
TRES_CASAS = Decimal("0.001")
DIAS_ALERTA_VALIDADE = 30

TIPOS_ENTRADA = {
    MovimentacaoEstoque.Tipo.ENTRADA,
    MovimentacaoEstoque.Tipo.DEVOLUCAO,
}
TIPOS_SAIDA = {
    MovimentacaoEstoque.Tipo.SAIDA,
    MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
    MovimentacaoEstoque.Tipo.PERDA,
    MovimentacaoEstoque.Tipo.VENCIMENTO,
}


def _decimal(valor) -> Decimal:
    if valor is None or valor == "":
        return ZERO
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"quantidade": ["Quantidade inválida."]})


def _normalizar_quantidade(valor, *, permitir_zero=False) -> Decimal:
    quantidade = _decimal(valor).quantize(TRES_CASAS)
    if quantidade < 0 or (quantidade == 0 and not permitir_zero):
        raise ValidationError(
            {"quantidade": ["Informe uma quantidade maior que zero."]}
        )
    return quantidade


def _direcao_do_tipo(tipo, direcao=None):
    if tipo in TIPOS_ENTRADA:
        esperada = MovimentacaoEstoque.Direcao.ENTRADA
    elif tipo in TIPOS_SAIDA:
        esperada = MovimentacaoEstoque.Direcao.SAIDA
    else:
        esperada = None

    if esperada is not None and direcao and direcao != esperada:
        raise ValidationError(
            {
                "direcao": [
                    f"O tipo {tipo} só permite movimentação de {esperada}."
                ]
            }
        )
    if esperada is not None:
        return esperada
    if direcao not in MovimentacaoEstoque.Direcao.values:
        raise ValidationError(
            {"direcao": ["Informe se o ajuste é de entrada ou de saída."]}
        )
    return direcao


def _validar_tipo(tipo):
    if tipo not in MovimentacaoEstoque.Tipo.values:
        raise ValidationError({"tipo": ["Tipo de movimentação inválido."]})


def _validar_lote_para_saida(lote, tipo):
    """Impede consumo/saída de lote vencido.

    Perdas, vencimentos e ajustes continuam permitidos para que o lote possa
    ser baixado e regularizado.
    """
    if tipo not in {
        MovimentacaoEstoque.Tipo.SAIDA,
        MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
    }:
        return
    if lote.data_validade and lote.data_validade < timezone.localdate():
        raise ValidationError(
            {
                "lote": [
                    "Lote vencido: não pode ser usado em saída ou consumo "
                    "clínico. Registre uma baixa por vencimento."
                ]
            }
        )


@transaction.atomic
def registrar_movimentacao(
    *,
    produto,
    lote,
    tipo,
    quantidade,
    direcao=None,
    motivo="",
    atendimento=None,
    fornecedor=None,
    custo_unitario=None,
    documento_referencia="",
    usuario=None,
):
    """Registra uma movimentação e atualiza o saldo do lote.

    O lote é bloqueado por ``select_for_update`` e o saldo é lido novamente
    dentro da transação; duas requisições concorrentes não conseguem deixar o
    saldo negativo.
    """
    _validar_tipo(tipo)
    quantidade = _normalizar_quantidade(quantidade)
    direcao = _direcao_do_tipo(tipo, direcao)

    if produto is None:
        raise ValidationError({"produto": ["Informe o produto."]})
    if lote is None:
        raise ValidationError({"lote": ["Informe o lote."]})
    if not produto.controla_estoque:
        raise ValidationError(
            {"produto": ["Este produto não controla estoque."]}
        )

    # Reconsulta sob lock: o objeto recebido pode estar desatualizado.
    lote = (
        Lote.objects.select_for_update()
        .select_related("produto")
        .filter(pk=lote.pk, is_deleted=False)
        .first()
    )
    if lote is None:
        raise ValidationError({"lote": ["Lote não encontrado."]})
    if lote.produto_id != produto.pk:
        raise ValidationError(
            {"lote": ["O lote informado não pertence ao produto selecionado."]}
        )

    saldo_anterior = lote.quantidade_atual or ZERO
    if direcao == MovimentacaoEstoque.Direcao.SAIDA:
        _validar_lote_para_saida(lote, tipo)
        if saldo_anterior < quantidade:
            raise ValidationError(
                {
                    "quantidade": [
                        f"Saldo insuficiente no lote {lote.numero_lote}: "
                        f"disponível {saldo_anterior}, solicitado {quantidade}."
                    ]
                }
            )
        saldo_posterior = saldo_anterior - quantidade
    else:
        saldo_posterior = saldo_anterior + quantidade

    lote.quantidade_atual = saldo_posterior
    lote.save(user=usuario, update_fields=["quantidade_atual", "updated_at"])

    return MovimentacaoEstoque.objects.create(
        produto=produto,
        lote=lote,
        tipo=tipo,
        direcao=direcao,
        quantidade=quantidade,
        saldo_anterior=saldo_anterior,
        saldo_posterior=saldo_posterior,
        motivo=(motivo or "").strip(),
        atendimento=atendimento,
        fornecedor=fornecedor,
        custo_unitario=custo_unitario,
        documento_referencia=(documento_referencia or "").strip(),
        created_by=usuario,
        updated_by=usuario,
    )


@transaction.atomic
def registrar_entrada(
    *,
    produto,
    lote,
    quantidade,
    motivo="Entrada de estoque",
    fornecedor=None,
    custo_unitario=None,
    documento_referencia="",
    usuario=None,
):
    return registrar_movimentacao(
        produto=produto,
        lote=lote,
        tipo=MovimentacaoEstoque.Tipo.ENTRADA,
        quantidade=quantidade,
        motivo=motivo,
        fornecedor=fornecedor,
        custo_unitario=custo_unitario,
        documento_referencia=documento_referencia,
        usuario=usuario,
    )


def _lotes_fefo(produto, *, tipo):
    """Lotes disponíveis em ordem FEFO (primeiro a vencer, primeiro a sair).

    Lotes sem validade ficam por último. Para saída/consumo, lotes vencidos
    são excluídos — eles não podem ser usados clinicamente.
    """
    hoje = timezone.localdate()
    qs = (
        Lote.objects.select_for_update()
        .select_related("produto")
        .filter(produto=produto, is_deleted=False, quantidade_atual__gt=0)
    )
    if tipo in {
        MovimentacaoEstoque.Tipo.SAIDA,
        MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
    }:
        qs = qs.exclude(data_validade__lt=hoje)
    return list(qs.order_by(F("data_validade").asc(nulls_last=True), "created_at"))


@transaction.atomic
def registrar_saida(
    *,
    produto,
    quantidade,
    tipo=MovimentacaoEstoque.Tipo.SAIDA,
    lote=None,
    motivo="Saída de estoque",
    atendimento=None,
    documento_referencia="",
    usuario=None,
):
    """Baixa estoque por lote explícito ou por FEFO.

    Sem lote informado, percorre os lotes em ordem FEFO e pode gerar várias
    movimentações para completar a quantidade. Se o saldo total (nos lotes
    válidos) não cobrir o pedido, toda a transação é revertida.
    """
    _validar_tipo(tipo)
    if tipo not in TIPOS_SAIDA:
        raise ValidationError(
            {"tipo": ["Use um tipo de saída, perda ou vencimento."]}
        )
    quantidade = _normalizar_quantidade(quantidade)

    if lote is not None:
        return [
            registrar_movimentacao(
                produto=produto,
                lote=lote,
                tipo=tipo,
                quantidade=quantidade,
                motivo=motivo,
                atendimento=atendimento,
                documento_referencia=documento_referencia,
                usuario=usuario,
            )
        ]

    restante = quantidade
    movimentacoes = []
    for lote_disponivel in _lotes_fefo(produto, tipo=tipo):
        if restante <= 0:
            break
        usar = min(restante, lote_disponivel.quantidade_atual)
        movimentacoes.append(
            registrar_movimentacao(
                produto=produto,
                lote=lote_disponivel,
                tipo=tipo,
                quantidade=usar,
                motivo=motivo,
                atendimento=atendimento,
                documento_referencia=documento_referencia,
                usuario=usuario,
            )
        )
        restante -= usar

    if restante > 0:
        raise ValidationError(
            {
                "quantidade": [
                    "Saldo insuficiente em lotes válidos para atender à saída "
                    f"(faltam {restante})."
                ]
            }
        )
    return movimentacoes


@transaction.atomic
def registrar_ajuste(
    *,
    produto,
    lote,
    quantidade,
    direcao,
    motivo,
    usuario=None,
):
    if not (motivo or "").strip():
        raise ValidationError(
            {"motivo": ["Informe o motivo do ajuste de estoque."]}
        )
    return registrar_movimentacao(
        produto=produto,
        lote=lote,
        tipo=MovimentacaoEstoque.Tipo.AJUSTE,
        direcao=direcao,
        quantidade=quantidade,
        motivo=motivo,
        usuario=usuario,
    )


@transaction.atomic
def criar_lote(
    *,
    produto,
    numero_lote,
    quantidade_inicial=0,
    fabricante="",
    data_fabricacao=None,
    data_validade=None,
    custo_aquisicao=None,
    fornecedor=None,
    observacoes="",
    usuario=None,
):
    """Cria o lote e, se houver saldo inicial, registra a entrada correspondente.

    O lote nasce com saldo zero; a quantidade inicial vira uma movimentação de
    entrada. Assim o saldo nunca aparece "do nada" no histórico.
    """
    quantidade = _normalizar_quantidade(
        quantidade_inicial, permitir_zero=True
    )
    if data_fabricacao and data_validade and data_fabricacao > data_validade:
        raise ValidationError(
            {"data_fabricacao": ["A fabricação não pode ser posterior à validade."]}
        )

    lote = Lote.objects.create(
        produto=produto,
        numero_lote=(numero_lote or "").strip(),
        fabricante=(fabricante or "").strip(),
        data_fabricacao=data_fabricacao,
        data_validade=data_validade,
        quantidade_inicial=quantidade,
        quantidade_atual=ZERO,
        custo_aquisicao=custo_aquisicao,
        fornecedor=fornecedor,
        observacoes=observacoes or "",
        created_by=usuario,
        updated_by=usuario,
    )

    if quantidade > 0:
        registrar_movimentacao(
            produto=produto,
            lote=lote,
            tipo=MovimentacaoEstoque.Tipo.ENTRADA,
            quantidade=quantidade,
            motivo="Saldo inicial do lote",
            fornecedor=fornecedor,
            custo_unitario=custo_aquisicao,
            usuario=usuario,
        )
        lote.refresh_from_db()
    return lote


@transaction.atomic
def abrir_inventario(*, tipo_estoque, observacoes="", usuario=None):
    """Abre um inventário congelando o saldo atual de todos os lotes do tipo."""
    if tipo_estoque not in Produto.TipoEstoque.values:
        raise ValidationError({"tipo_estoque": ["Tipo de estoque inválido."]})

    inventario = Inventario.objects.create(
        tipo_estoque=tipo_estoque,
        observacoes=observacoes or "",
        created_by=usuario,
        updated_by=usuario,
    )

    lotes = (
        Lote.objects.select_for_update()
        .select_related("produto")
        .filter(
            is_deleted=False,
            produto__tipo_estoque=tipo_estoque,
            produto__controla_estoque=True,
        )
        .order_by("produto__nome", "data_validade", "numero_lote")
    )
    for lote in lotes:
        ItemInventario.objects.create(
            inventario=inventario,
            lote=lote,
            quantidade_sistema=lote.quantidade_atual or ZERO,
            quantidade_contada=lote.quantidade_atual or ZERO,
            created_by=usuario,
            updated_by=usuario,
        )
    return inventario


@transaction.atomic
def finalizar_inventario(*, inventario_id, usuario=None):
    """Aplica as diferenças do inventário como movimentações de ajuste.

    O saldo do sistema é recalculado no momento da finalização para considerar
    movimentações ocorridas depois da abertura do inventário.
    """
    inventario = (
        Inventario.objects.select_for_update()
        .filter(pk=inventario_id, is_deleted=False)
        .first()
    )
    if inventario is None:
        raise ValidationError({"detail": "Inventário não encontrado."})
    if inventario.status != Inventario.Status.ABERTO:
        raise ValidationError(
            {"detail": "Somente inventários abertos podem ser finalizados."}
        )

    itens = list(
        ItemInventario.objects.select_for_update()
        .select_related("lote", "lote__produto")
        .filter(inventario=inventario, is_deleted=False)
    )
    for item in itens:
        lote = (
            Lote.objects.select_for_update()
            .select_related("produto")
            .filter(pk=item.lote_id, is_deleted=False)
            .first()
        )
        if lote is None:
            continue

        item.quantidade_sistema = lote.quantidade_atual or ZERO
        diferenca = (item.quantidade_contada or ZERO) - item.quantidade_sistema
        item.diferenca = diferenca

        if diferenca != 0:
            direcao = (
                MovimentacaoEstoque.Direcao.ENTRADA
                if diferenca > 0
                else MovimentacaoEstoque.Direcao.SAIDA
            )
            item.movimentacao = registrar_movimentacao(
                produto=lote.produto,
                lote=lote,
                tipo=MovimentacaoEstoque.Tipo.AJUSTE,
                direcao=direcao,
                quantidade=abs(diferenca),
                motivo=f"Ajuste do inventário {inventario.id}",
                usuario=usuario,
            )
        item.save(user=usuario)

    inventario.status = Inventario.Status.FINALIZADO
    inventario.finalizado_em = timezone.now()
    inventario.finalizado_por = usuario
    inventario.save(user=usuario)
    return inventario


@transaction.atomic
def cancelar_inventario(*, inventario_id, usuario=None):
    inventario = (
        Inventario.objects.select_for_update()
        .filter(pk=inventario_id, is_deleted=False)
        .first()
    )
    if inventario is None:
        raise ValidationError({"detail": "Inventário não encontrado."})
    if inventario.status != Inventario.Status.ABERTO:
        raise ValidationError(
            {"detail": "Somente inventários abertos podem ser cancelados."}
        )
    inventario.status = Inventario.Status.CANCELADO
    inventario.save(user=usuario)
    return inventario


def _saldo_por_produto_queryset():
    return Produto.objects.filter(controla_estoque=True).annotate(
        saldo_total=Coalesce(
            Sum(
                "lotes__quantidade_atual",
                filter=Q(lotes__is_deleted=False),
            ),
            Value(ZERO),
            output_field=DecimalField(max_digits=14, decimal_places=3),
        )
    )


def _dados_lote(lote):
    return {
        "id": str(lote.id),
        "produto": str(lote.produto_id),
        "produto_nome": lote.produto.nome,
        "produto_codigo": lote.produto.codigo_interno,
        "numero_lote": lote.numero_lote,
        "data_validade": lote.data_validade,
        "dias_para_vencer": lote.dias_para_vencer,
        "status_validade": lote.status_validade,
        "quantidade_atual": lote.quantidade_atual,
        "custo_aquisicao": lote.custo_aquisicao,
        "tipo_estoque": lote.produto.tipo_estoque,
    }


def alertas_estoque():
    """Estoque mínimo e validade, usados no dashboard e na tela de alertas."""
    hoje = timezone.localdate()
    limite = hoje + timedelta(days=DIAS_ALERTA_VALIDADE)

    produtos_minimo = (
        _saldo_por_produto_queryset()
        .filter(ativo=True, estoque_minimo__gt=0, saldo_total__lte=F("estoque_minimo"))
        .order_by("nome")
    )
    minimo = [
        {
            "id": str(produto.id),
            "nome": produto.nome,
            "codigo_interno": produto.codigo_interno,
            "tipo_estoque": produto.tipo_estoque,
            "saldo_total": produto.saldo_total,
            "estoque_minimo": produto.estoque_minimo,
            "faltando": max(produto.estoque_minimo - produto.saldo_total, ZERO),
        }
        for produto in produtos_minimo
    ]

    lotes_com_saldo = (
        Lote.objects.select_related("produto")
        .filter(is_deleted=False, quantidade_atual__gt=0)
        .order_by("data_validade", "produto__nome")
    )
    vencidos = [
        _dados_lote(lote)
        for lote in lotes_com_saldo
        if lote.data_validade and lote.data_validade < hoje
    ]
    vencendo = [
        _dados_lote(lote)
        for lote in lotes_com_saldo
        if lote.data_validade and hoje <= lote.data_validade <= limite
    ]

    return {
        "estoque_minimo": minimo,
        "lotes_vencidos": vencidos,
        "lotes_vencendo": vencendo,
        "totais": {
            "estoque_minimo": len(minimo),
            "lotes_vencidos": len(vencidos),
            "lotes_vencendo": len(vencendo),
        },
    }


def resumo_estoque():
    """Indicadores do dashboard de estoque."""
    lotes = list(
        Lote.objects.select_related("produto")
        .filter(is_deleted=False, quantidade_atual__gt=0)
    )

    por_tipo = {
        Produto.TipoEstoque.CLINICO: {"quantidade": ZERO, "valor": ZERO, "lotes": 0},
        Produto.TipoEstoque.COMERCIAL: {"quantidade": ZERO, "valor": ZERO, "lotes": 0},
    }
    for lote in lotes:
        tipo = lote.produto.tipo_estoque
        if tipo not in por_tipo:
            continue
        por_tipo[tipo]["quantidade"] += lote.quantidade_atual or ZERO
        por_tipo[tipo]["valor"] += lote.valor_em_estoque
        por_tipo[tipo]["lotes"] += 1

    alertas = alertas_estoque()
    movimentacoes = (
        MovimentacaoEstoque.objects.select_related(
            "produto", "lote", "fornecedor", "atendimento"
        )
        .all()
        .order_by("-data_hora", "-created_at")[:10]
    )

    return {
        "produtos_ativos": Produto.objects.filter(ativo=True).count(),
        "lotes_com_saldo": len(lotes),
        "por_tipo": {
            tipo: {
                "quantidade": dados["quantidade"],
                "valor": dados["valor"],
                "lotes": dados["lotes"],
            }
            for tipo, dados in por_tipo.items()
        },
        "alertas": alertas["totais"],
        "lotes_vencidos": alertas["lotes_vencidos"][:10],
        "lotes_vencendo": alertas["lotes_vencendo"][:10],
        "estoque_minimo": alertas["estoque_minimo"][:10],
        "movimentacoes_recentes": [
            {
                "id": str(mov.id),
                "tipo": mov.tipo,
                "tipo_display": mov.get_tipo_display(),
                "direcao": mov.direcao,
                "quantidade": mov.quantidade,
                "produto_nome": mov.produto.nome,
                "lote_numero": mov.lote.numero_lote,
                "data_hora": mov.data_hora,
                "motivo": mov.motivo,
            }
            for mov in movimentacoes
        ],
    }
