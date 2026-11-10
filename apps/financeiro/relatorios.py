"""Consultas agregadas para o dashboard e os relatórios financeiros."""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone

from apps.servicos.models import ServicoRealizado

from .models import (
    Caixa,
    ContaReceber,
    FormaPagamento,
    MovimentacaoCaixa,
    Pagamento,
    ParcelaContaReceber,
)
from .services import ZERO, resumo_caixa


def periodo_padrao(data_inicio=None, data_fim=None):
    hoje = timezone.localdate()
    if data_fim is None:
        data_fim = hoje
    if data_inicio is None:
        data_inicio = data_fim.replace(day=1)
    if data_inicio > data_fim:
        data_inicio, data_fim = data_fim, data_inicio
    return data_inicio, data_fim


def _q_pagamentos_confirmados(data_inicio, data_fim):
    return Q(
        status=Pagamento.Status.CONFIRMADO,
        data_hora__date__gte=data_inicio,
        data_hora__date__lte=data_fim,
    )


def receita_periodo(data_inicio=None, data_fim=None, agrupamento="dia"):
    data_inicio, data_fim = periodo_padrao(data_inicio, data_fim)
    trunc = TruncMonth("data_hora") if agrupamento == "mes" else TruncDay("data_hora")
    linhas = (
        Pagamento.objects.filter(_q_pagamentos_confirmados(data_inicio, data_fim))
        .annotate(periodo=trunc)
        .values("periodo")
        .annotate(total=Sum("valor"), quantidade=Count("id"))
        .order_by("periodo")
    )
    resultado = [
        {
            "periodo": linha["periodo"].date().isoformat(),
            "total": linha["total"] or ZERO,
            "quantidade": linha["quantidade"],
        }
        for linha in linhas
    ]
    total = sum((linha["total"] for linha in resultado), ZERO)
    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "agrupamento": agrupamento,
        "total": total,
        "quantidade": sum(linha["quantidade"] for linha in resultado),
        "linhas": resultado,
    }


def recebimentos_por_forma(data_inicio=None, data_fim=None):
    data_inicio, data_fim = periodo_padrao(data_inicio, data_fim)
    linhas = (
        Pagamento.objects.filter(_q_pagamentos_confirmados(data_inicio, data_fim))
        .values("forma_pagamento", "forma_pagamento__nome", "forma_pagamento__tipo")
        .annotate(total=Sum("valor"), quantidade=Count("id"))
        .order_by("-total")
    )
    resultado = [
        {
            "forma_pagamento": linha["forma_pagamento"],
            "nome": linha["forma_pagamento__nome"],
            "tipo": linha["forma_pagamento__tipo"],
            "total": linha["total"] or ZERO,
            "quantidade": linha["quantidade"],
        }
        for linha in linhas
    ]
    total = sum((linha["total"] for linha in resultado), ZERO)
    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "total": total,
        "linhas": resultado,
    }


def receita_por_servico(data_inicio=None, data_fim=None):
    data_inicio, data_fim = periodo_padrao(data_inicio, data_fim)
    linhas = (
        ServicoRealizado.objects.filter(
            data_hora__date__gte=data_inicio,
            data_hora__date__lte=data_fim,
        )
        .values("servico", "servico__nome", "servico__categoria__nome")
        .annotate(
            total=Sum("valor_total"),
            quantidade=Sum("quantidade"),
            atendimentos=Count("atendimento", distinct=True),
        )
        .order_by("-total")
    )
    resultado = [
        {
            "servico": linha["servico"],
            "nome": linha["servico__nome"],
            "categoria": linha["servico__categoria__nome"],
            "total": linha["total"] or ZERO,
            "quantidade": linha["quantidade"] or ZERO,
            "atendimentos": linha["atendimentos"],
        }
        for linha in linhas
    ]
    total = sum((linha["total"] for linha in resultado), ZERO)
    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "total": total,
        "linhas": resultado,
    }


def contas_pendentes(*, vencimento_ate=None, tutor=None):
    qs = (
        ContaReceber.objects.select_related("tutor", "atendimento")
        .filter(
            status__in=[ContaReceber.Status.ABERTA, ContaReceber.Status.PARCIAL],
            saldo__gt=0,
            is_deleted=False,
        )
        .order_by("vencimento", "created_at")
    )
    if vencimento_ate is not None:
        qs = qs.filter(vencimento__lte=vencimento_ate)
    if tutor is not None:
        qs = qs.filter(tutor=tutor)
    return qs


def inadimplencia(*, tutor=None):
    hoje = timezone.localdate()
    qs = (
        ContaReceber.objects.select_related("tutor", "atendimento")
        .filter(
            status__in=[ContaReceber.Status.ABERTA, ContaReceber.Status.PARCIAL],
            saldo__gt=0,
            vencimento__lt=hoje,
            is_deleted=False,
        )
        .order_by("vencimento", "created_at")
    )
    if tutor is not None:
        qs = qs.filter(tutor=tutor)
    return qs


def fluxo_caixa(data_inicio=None, data_fim=None):
    data_inicio, data_fim = periodo_padrao(data_inicio, data_fim)
    movimentos = (
        MovimentacaoCaixa.objects.filter(
            data_hora__date__gte=data_inicio,
            data_hora__date__lte=data_fim,
            is_deleted=False,
        )
        .annotate(dia=TruncDay("data_hora"))
        .values("dia")
        .annotate(
            entradas=Sum("valor", filter=Q(tipo=MovimentacaoCaixa.Tipo.ENTRADA)),
            saidas=Sum("valor", filter=Q(tipo=MovimentacaoCaixa.Tipo.SAIDA)),
            ajustes=Sum("valor", filter=Q(tipo=MovimentacaoCaixa.Tipo.AJUSTE)),
        )
        .order_by("dia")
    )
    linhas = []
    total_entradas = ZERO
    total_saidas = ZERO
    total_ajustes = ZERO
    for movimento in movimentos:
        entradas = movimento["entradas"] or ZERO
        saidas = movimento["saidas"] or ZERO
        ajustes = movimento["ajustes"] or ZERO
        total_entradas += entradas
        total_saidas += saidas
        total_ajustes += ajustes
        linhas.append(
            {
                "data": movimento["dia"].date().isoformat(),
                "entradas": entradas,
                "saidas": saidas,
                "ajustes": ajustes,
                "saldo_dia": entradas - saidas + ajustes,
            }
        )
    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "entradas": total_entradas,
        "saidas": total_saidas,
        "ajustes": total_ajustes,
        "saldo": total_entradas - total_saidas + total_ajustes,
        "linhas": linhas,
    }


def dashboard_financeiro():
    hoje = timezone.localdate()
    inicio_mes = hoje.replace(day=1)
    contas_abertas = ContaReceber.objects.filter(
        status__in=[ContaReceber.Status.ABERTA, ContaReceber.Status.PARCIAL],
        saldo__gt=0,
        is_deleted=False,
    )
    vencidas = contas_abertas.filter(vencimento__lt=hoje)
    recebido_mes = Pagamento.objects.filter(
        _q_pagamentos_confirmados(inicio_mes, hoje)
    ).aggregate(total=Sum("valor"), quantidade=Count("id"))
    recebido_hoje = Pagamento.objects.filter(
        status=Pagamento.Status.CONFIRMADO, data_hora__date=hoje
    ).aggregate(total=Sum("valor"), quantidade=Count("id"))
    caixa = (
        Caixa.objects.filter(status=Caixa.Status.ABERTO, is_deleted=False)
        .order_by("-data_abertura")
        .first()
    )
    resumo = resumo_caixa(caixa) if caixa is not None else None
    formas = recebimentos_por_forma(inicio_mes, hoje)["linhas"]
    pendentes_count = contas_abertas.count()
    vencidas_count = vencidas.count()
    return {
        "hoje": hoje,
        "contas_abertas": {
            "quantidade": pendentes_count,
            "saldo": contas_abertas.aggregate(total=Sum("saldo"))["total"] or ZERO,
        },
        "inadimplencia": {
            "quantidade": vencidas_count,
            "saldo": vencidas.aggregate(total=Sum("saldo"))["total"] or ZERO,
            "percentual": (
                round(vencidas_count / pendentes_count * 100, 2)
                if pendentes_count
                else 0
            ),
        },
        "recebido_mes": {
            "total": recebido_mes["total"] or ZERO,
            "quantidade": recebido_mes["quantidade"] or 0,
        },
        "recebido_hoje": {
            "total": recebido_hoje["total"] or ZERO,
            "quantidade": recebido_hoje["quantidade"] or 0,
        },
        "caixa_aberto": (
            {
                "id": str(caixa.pk),
                "descricao": caixa.descricao,
                "data_abertura": caixa.data_abertura,
                **resumo,
            }
            if caixa is not None
            else None
        ),
        "formas_recebimento_mes": formas,
    }


def parcelas_vencidas():
    return ParcelaContaReceber.objects.filter(
        status__in=[
            ParcelaContaReceber.Status.ABERTA,
            ParcelaContaReceber.Status.PARCIAL,
        ],
        saldo__gt=0,
        vencimento__lt=timezone.localdate(),
        is_deleted=False,
    ).order_by("vencimento", "numero")


def resumo_por_dia(data_inicio=None, data_fim=None):
    """Atalho usado por testes/consumidores que precisam de série diária."""
    return receita_periodo(data_inicio, data_fim, agrupamento="dia")


def proximo_vencimento(data_base=None, dias=30):
    data_base = data_base or timezone.localdate()
    return data_base + timedelta(days=dias)


def formas_ativas():
    return FormaPagamento.objects.filter(ativo=True, is_deleted=False).order_by("nome")


def contas_do_tutor(tutor):
    return ContaReceber.objects.filter(tutor=tutor, is_deleted=False).order_by(
        "-data_emissao"
    )


def total_em_aberto():
    return (
        ContaReceber.objects.filter(
            status__in=[ContaReceber.Status.ABERTA, ContaReceber.Status.PARCIAL],
            saldo__gt=0,
            is_deleted=False,
        ).aggregate(total=Sum("saldo"))["total"]
        or ZERO
    )


def data_iso(valor):
    return valor.isoformat() if isinstance(valor, date) else valor


def decimal_str(valor):
    if valor is None:
        return None
    return str(Decimal(valor).quantize(Decimal("0.01")))
