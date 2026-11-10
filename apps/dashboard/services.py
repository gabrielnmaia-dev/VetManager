"""Agregações server-side do painel gerencial.

Todas as métricas são calculadas no banco (``Count``/``Sum``/``Trunc*``) a
partir de filtros explícitos, nunca a partir da lista paginada de atendimentos.
Os endpoints do dashboard compartilham este módulo para que a tela principal e
as rotas específicas de indicadores apresentem exatamente os mesmos números.

Convenções importantes:

* Datas de calendário usam ``timezone.localdate()`` e os limites de consulta
  são convertidos para *datetimes* aware no fuso da aplicação. Assim um
  atendimento às 23h30 em America/Fortaleza pertence ao dia local correto,
  mesmo sendo armazenado em UTC.
* ``atendimentos_pendentes`` considera AGENDADO + CONFIRMADO a partir de hoje
  (inclusive), não apenas os criados com status AGENDADO.
* ``cancelamentos`` e ``faltas`` respeitam o período selecionado e os demais
  filtros (profissional, tipo de serviço e status).
* Indicadores clínicos (retornos e vacinas) refletem a situação *atual*;
  aceitam o filtro de profissional, mas não o período de atendimentos.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError

from apps.atendimentos.models import Atendimento
from apps.pets.models import Pet
from apps.prontuario.models import Prontuario, Vacina, Vermifugacao
from apps.tutores.models import Tutor
from apps.veterinarios.models import (
    BloqueioAgenda,
    HorarioTrabalho,
    Profissional,
)

# Status que ainda ocupam a agenda e aguardam execução.
STATUS_PENDENTES = (
    Atendimento.Status.AGENDADO,
    Atendimento.Status.CONFIRMADO,
)
# Status que representam tempo efetivamente reservado na agenda.
STATUS_OCUPAM_AGENDA = (
    Atendimento.Status.AGENDADO,
    Atendimento.Status.CONFIRMADO,
    Atendimento.Status.REALIZADO,
)

DIAS_SERIE = 7
DIAS_SERVICOS = 30
DIAS_HISTORICO_PADRAO = 90
SEMANAS_HISTORICO = 12
MESES_HISTORICO = 12
LIMITE_PERIODO_DIAS = 366
LIMITE_SERVICOS = 5
LIMITE_SERVICOS_HISTORICO = 8

# Jornada usada quando o profissional não possui HorarioTrabalho cadastrado.
# Mantém a ocupação utilizável em bases antigas sem inventar disponibilidade
# nos fins de semana.
JORNADA_PADRAO_INICIO = time(8, 0)
JORNADA_PADRAO_FIM = time(18, 0)

DIAS_SEMANA_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES_CURTOS = [
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
]


# ---------------------------------------------------------------------------
# Datas e filtros
# ---------------------------------------------------------------------------
def _inicio_dia(dia: date) -> datetime:
    """Meia-noite local do dia informado, como datetime aware."""
    return timezone.make_aware(datetime.combine(dia, time.min))


def _fim_dia_exclusivo(dia: date) -> datetime:
    """Meia-noite local do dia seguinte (limite exclusivo)."""
    return _inicio_dia(dia + timedelta(days=1))


def _parse_data(valor: str, campo: str) -> date:
    try:
        data = parse_date(valor)
    except ValueError:
        data = None
    if data is None:
        raise ValidationError(
            {campo: ["Informe uma data válida no formato AAAA-MM-DD."]}
        )
    return data


def _dias_entre(inicio: date, fim: date):
    dia = inicio
    while dia <= fim:
        yield dia
        dia += timedelta(days=1)


def _segunda(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def _primeiro_dia_mes(dia: date) -> date:
    return dia.replace(day=1)


def _mes_menos(dia: date, meses: int) -> date:
    total = dia.year * 12 + (dia.month - 1) - meses
    ano, mes = divmod(total, 12)
    return date(ano, mes + 1, 1)


def _como_date(valor) -> date:
    """Normaliza o retorno de ``Trunc*`` entre SQLite e PostgreSQL."""
    if isinstance(valor, datetime):
        return timezone.localtime(valor).date() if timezone.is_aware(valor) else valor.date()
    if isinstance(valor, date):
        return valor
    return parse_date(str(valor))


def _label_semana(inicio: date, fim: date) -> str:
    return f"{inicio.strftime('%d/%m')} – {fim.strftime('%d/%m')}"


def _label_mes(dia: date) -> str:
    return f"{MESES_CURTOS[dia.month - 1]}/{str(dia.year)[2:]}"


@dataclass(frozen=True)
class FiltrosDashboard:
    """Filtros normalizados e validados da requisição."""

    data_inicio: date
    data_fim: date
    hoje: date
    personalizado: bool
    profissional_id: str | None = None
    profissional_nome: str | None = None
    tipo_servico: str | None = None
    status: str | None = None

    @property
    def dias(self) -> int:
        return (self.data_fim - self.data_inicio).days + 1

    @property
    def inicio_dt(self) -> datetime:
        return _inicio_dia(self.data_inicio)

    @property
    def fim_dt(self) -> datetime:
        """Limite exclusivo do período."""
        return _fim_dia_exclusivo(self.data_fim)

    def como_dict(self) -> dict:
        return {
            "data_inicio": self.data_inicio.isoformat(),
            "data_fim": self.data_fim.isoformat(),
            "profissional": self.profissional_id,
            "profissional_nome": self.profissional_nome,
            "tipo_servico": self.tipo_servico,
            "status": self.status,
            "dias": self.dias,
            "personalizado": self.personalizado,
        }


def obter_filtros(params) -> FiltrosDashboard:
    """Interpreta e valida ``data_inicio``/``data_fim`` e filtros de catálogo."""
    hoje = timezone.localdate()
    bruto_inicio = (params.get("data_inicio") or "").strip()
    bruto_fim = (params.get("data_fim") or "").strip()
    personalizado = bool(bruto_inicio or bruto_fim)

    data_inicio = _parse_data(bruto_inicio, "data_inicio") if bruto_inicio else None
    data_fim = _parse_data(bruto_fim, "data_fim") if bruto_fim else None

    if data_inicio is None and data_fim is None:
        data_fim = hoje
        data_inicio = hoje - timedelta(days=DIAS_SERVICOS - 1)
    elif data_inicio is None:
        data_inicio = data_fim - timedelta(days=DIAS_SERVICOS - 1)
    elif data_fim is None:
        data_fim = hoje

    if data_inicio > data_fim:
        raise ValidationError(
            {"data_fim": ["A data final não pode ser anterior à data inicial."]}
        )
    if (data_fim - data_inicio).days + 1 > LIMITE_PERIODO_DIAS:
        raise ValidationError(
            {
                "data_fim": [
                    f"O período máximo permitido é de {LIMITE_PERIODO_DIAS} dias."
                ]
            }
        )

    profissional_id = (params.get("profissional") or "").strip() or None
    profissional_nome = None
    if profissional_id:
        try:
            uuid.UUID(str(profissional_id))
        except (TypeError, ValueError):
            raise ValidationError(
                {"profissional": ["Identificador de profissional inválido."]}
            )
        profissional = Profissional.objects.filter(pk=profissional_id).first()
        if profissional is None:
            raise ValidationError(
                {"profissional": ["Profissional não encontrado."]}
            )
        profissional_id = str(profissional.pk)
        profissional_nome = profissional.nome

    tipo_servico = (params.get("tipo_servico") or "").strip() or None
    if tipo_servico and tipo_servico not in dict(
        Atendimento.TipoServico.choices
    ):
        raise ValidationError(
            {"tipo_servico": ["Tipo de atendimento inválido."]}
        )

    status = (params.get("status") or "").strip() or None
    if status and status not in dict(Atendimento.Status.choices):
        raise ValidationError({"status": ["Status de atendimento inválido."]})

    return FiltrosDashboard(
        data_inicio=data_inicio,
        data_fim=data_fim,
        hoje=hoje,
        personalizado=personalizado,
        profissional_id=profissional_id,
        profissional_nome=profissional_nome,
        tipo_servico=tipo_servico,
        status=status,
    )


def _aplicar_filtros_catalogo(queryset, filtros: FiltrosDashboard, incluir_status=True):
    if filtros.profissional_id:
        queryset = queryset.filter(profissional_id=filtros.profissional_id)
    if filtros.tipo_servico:
        queryset = queryset.filter(tipo_servico=filtros.tipo_servico)
    if incluir_status and filtros.status:
        queryset = queryset.filter(status=filtros.status)
    return queryset


def _atendimentos_no_periodo(
    filtros: FiltrosDashboard, incluir_status=True, usar_data=True
):
    queryset = Atendimento.objects.all()
    if usar_data:
        queryset = queryset.filter(
            data_hora_inicio__gte=filtros.inicio_dt,
            data_hora_inicio__lt=filtros.fim_dt,
        )
    return _aplicar_filtros_catalogo(
        queryset, filtros, incluir_status=incluir_status
    )


# ---------------------------------------------------------------------------
# KPIs operacionais
# ---------------------------------------------------------------------------
def _contagem_retornos(filtros: FiltrosDashboard) -> dict:
    """Retornos clínicos pendentes e vacinas próximas do vencimento."""
    hoje = filtros.hoje
    # Prontuários não têm constante própria; usa-se a mesma janela clínica das
    # vacinas para retornos recomendados.
    limite_prontuario = hoje + timedelta(days=Vacina.DIAS_ALERTA_RETORNO)
    limite_vacina = hoje + timedelta(days=Vacina.DIAS_ALERTA_RETORNO)
    limite_vermifugo = hoje + timedelta(
        days=Vermifugacao.DIAS_ALERTA_RETORNO
    )

    prontuarios = Prontuario.objects.filter(retorno_recomendado__isnull=False)
    vacinas = Vacina.objects.filter(data_retorno__isnull=False)
    vermifugacoes = Vermifugacao.objects.filter(data_retorno__isnull=False)

    if filtros.profissional_id:
        prontuarios = prontuarios.filter(
            veterinario__profissional_id=filtros.profissional_id
        )
        vacinas = vacinas.filter(
            veterinario__profissional_id=filtros.profissional_id
        )
        vermifugacoes = vermifugacoes.filter(
            veterinario__profissional_id=filtros.profissional_id
        )

    return {
        "prontuarios": {
            "atrasados": prontuarios.filter(
                retorno_recomendado__date__lt=hoje
            ).count(),
            "proximos": prontuarios.filter(
                retorno_recomendado__date__gte=hoje,
                retorno_recomendado__date__lte=limite_prontuario,
            ).count(),
        },
        "vacinas": {
            "atrasadas": vacinas.filter(data_retorno__lt=hoje).count(),
            "proximas": vacinas.filter(
                data_retorno__gte=hoje, data_retorno__lte=limite_vacina
            ).count(),
        },
        "vermifugacoes": {
            "atrasadas": vermifugacoes.filter(data_retorno__lt=hoje).count(),
            "proximas": vermifugacoes.filter(
                data_retorno__gte=hoje, data_retorno__lte=limite_vermifugo
            ).count(),
        },
    }


def _atendimentos_por_profissional(base) -> list:
    """Distribuição de atendimentos por profissional, incluindo o campo legado."""
    linhas = (
        base.values(
            "profissional_id", "profissional__nome", "nome_profissional"
        )
        .annotate(
            total=Count("id"),
            realizados=Count(
                "id", filter=Q(status=Atendimento.Status.REALIZADO)
            ),
            cancelados=Count(
                "id", filter=Q(status=Atendimento.Status.CANCELADO)
            ),
            faltas=Count("id", filter=Q(status=Atendimento.Status.FALTOU)),
            pendentes=Count("id", filter=Q(status__in=STATUS_PENDENTES)),
            minutos=Sum("duracao_minutos"),
        )
        .order_by("-total", "profissional__nome", "nome_profissional")
    )

    agrupado: dict[str, dict] = {}
    total_geral = 0
    for linha in linhas:
        profissional_id = linha["profissional_id"]
        nome = (
            linha["profissional__nome"]
            or linha["nome_profissional"]
            or "Sem profissional"
        )
        chave = str(profissional_id) if profissional_id else f"legado:{nome}"
        item = agrupado.setdefault(
            chave,
            {
                "id": str(profissional_id) if profissional_id else None,
                "nome": nome,
                "total": 0,
                "realizados": 0,
                "cancelados": 0,
                "faltas": 0,
                "pendentes": 0,
                "minutos": 0,
            },
        )
        item["total"] += linha["total"]
        item["realizados"] += linha["realizados"]
        item["cancelados"] += linha["cancelados"]
        item["faltas"] += linha["faltas"]
        item["pendentes"] += linha["pendentes"]
        item["minutos"] += linha["minutos"] or 0
        total_geral += linha["total"]

    resultado = list(agrupado.values())
    for item in resultado:
        item["percentual"] = (
            round(item["total"] / total_geral * 100, 1)
            if total_geral
            else 0
        )
    resultado.sort(key=lambda item: (-item["total"], item["nome"]))
    return resultado


def _bloqueios_carregados(filtros: FiltrosDashboard) -> tuple[dict, list]:
    """Bloqueios ativos do período separados por profissional e globais."""
    por_profissional: dict[str, list] = {}
    globais: list = []
    consulta = BloqueioAgenda.objects.filter(
        ativo=True,
        data_inicio__lt=filtros.fim_dt,
        data_fim__gt=filtros.inicio_dt,
    )
    for bloqueio in consulta:
        intervalo = (bloqueio.data_inicio, bloqueio.data_fim)
        if bloqueio.profissional_id:
            por_profissional.setdefault(
                str(bloqueio.profissional_id), []
            ).append(intervalo)
        else:
            # Sem profissional o bloqueio vale para toda a clínica (feriado),
            # inclusive quando restrito a uma sala: a capacidade é calculada
            # por profissional, então o bloqueio é descontado de todos.
            globais.append(intervalo)
    return por_profissional, globais


def _minutos_bloqueados(
    intervalos: list, dia: date, inicio_min: int, fim_min: int
) -> int:
    """Minutos bloqueados dentro de uma janela do dia (união dos intervalos)."""
    inicio_janela = _inicio_dia(dia) + timedelta(minutes=inicio_min)
    fim_janela = _inicio_dia(dia) + timedelta(minutes=fim_min)
    recortes = []
    for inicio, fim in intervalos:
        recorte_inicio = max(inicio, inicio_janela)
        recorte_fim = min(fim, fim_janela)
        if recorte_fim > recorte_inicio:
            recortes.append((recorte_inicio, recorte_fim))
    if not recortes:
        return 0
    recortes.sort()
    total = 0
    cursor_inicio, cursor_fim = recortes[0]
    for inicio, fim in recortes[1:]:
        if inicio <= cursor_fim:
            cursor_fim = max(cursor_fim, fim)
        else:
            total += int((cursor_fim - cursor_inicio).total_seconds() // 60)
            cursor_inicio, cursor_fim = inicio, fim
    total += int((cursor_fim - cursor_inicio).total_seconds() // 60)
    return total


def _ocupacao_agenda(filtros: FiltrosDashboard) -> dict:
    """Ocupação da agenda no período selecionado.

    A capacidade vem dos ``HorarioTrabalho`` ativos; quando o profissional não
    tem jornada cadastrada, usa-se 8h–18h de segunda a sexta. Bloqueios
    globais (sem profissional) e do próprio profissional são descontados.
    Cancelamentos e faltas não ocupam a agenda.
    """
    profissionais = Profissional.objects.filter(ativo=True)
    if filtros.profissional_id:
        profissionais = profissionais.filter(pk=filtros.profissional_id)
    profissionais = list(profissionais)

    horarios: dict[tuple[str, int], list] = {}
    for horario in HorarioTrabalho.objects.filter(
        profissional__in=profissionais, ativo=True
    ):
        horarios.setdefault(
            (str(horario.profissional_id), horario.dia_semana), []
        ).append((horario.hora_inicio, horario.hora_fim))

    bloqueios_prof, bloqueios_globais = _bloqueios_carregados(filtros)

    capacidade = 0
    dias_com_capacidade = 0
    usou_padrao = False
    for dia in _dias_entre(filtros.data_inicio, filtros.data_fim):
        capacidade_dia = 0
        for profissional in profissionais:
            janelas = horarios.get(
                (str(profissional.pk), dia.weekday()), []
            )
            if janelas:
                pass
            elif dia.weekday() < 5:
                janelas = [(JORNADA_PADRAO_INICIO, JORNADA_PADRAO_FIM)]
                usou_padrao = True
            else:
                janelas = []

            bloqueios = bloqueios_prof.get(str(profissional.pk), []) + bloqueios_globais
            for inicio, fim in janelas:
                inicio_min = inicio.hour * 60 + inicio.minute
                fim_min = fim.hour * 60 + fim.minute
                total_janela = max(0, fim_min - inicio_min)
                bloqueado = _minutos_bloqueados(
                    bloqueios, dia, inicio_min, fim_min
                )
                capacidade_dia += max(0, total_janela - bloqueado)
        if capacidade_dia:
            dias_com_capacidade += 1
        capacidade += capacidade_dia

    agenda = _atendimentos_no_periodo(filtros, usar_data=True).filter(
        status__in=STATUS_OCUPAM_AGENDA
    )
    agregados = agenda.aggregate(
        ocupado=Sum("duracao_minutos"),
        realizados=Sum(
            "duracao_minutos",
            filter=Q(status=Atendimento.Status.REALIZADO),
        ),
    )
    ocupado = agregados["ocupado"] or 0
    realizados = agregados["realizados"] or 0

    if capacidade:
        percentual = round(ocupado / capacidade * 100, 1)
        origem = "misto" if usou_padrao else "horarios"
    else:
        percentual = None
        origem = "sem_capacidade"

    return {
        "percentual": percentual,
        "ocupado_minutos": ocupado,
        "realizados_minutos": realizados,
        "capacidade_minutos": capacidade,
        "dias": filtros.dias,
        "dias_com_capacidade": dias_com_capacidade,
        "profissionais_considerados": len(profissionais),
        "origem_capacidade": origem,
    }


def indicadores_operacionais(filtros: FiltrosDashboard) -> dict:
    """KPIs operacionais do período selecionado."""
    base = _atendimentos_no_periodo(filtros)
    totais = base.aggregate(
        total=Count("id"),
        realizados=Count(
            "id", filter=Q(status=Atendimento.Status.REALIZADO)
        ),
        cancelados=Count(
            "id", filter=Q(status=Atendimento.Status.CANCELADO)
        ),
        faltas=Count("id", filter=Q(status=Atendimento.Status.FALTOU)),
        pendentes=Count("id", filter=Q(status__in=STATUS_PENDENTES)),
    )

    hoje = filtros.hoje
    hoje_inicio = _inicio_dia(hoje)
    hoje_fim = _fim_dia_exclusivo(hoje)

    hoje_qs = _aplicar_filtros_catalogo(
        Atendimento.objects.filter(
            data_hora_inicio__gte=hoje_inicio,
            data_hora_inicio__lt=hoje_fim,
        ),
        filtros,
    )
    atendimentos_hoje = hoje_qs.aggregate(total=Count("id"))["total"]

    backlog = Atendimento.objects.filter(data_hora_inicio__gte=hoje_inicio)
    backlog = _aplicar_filtros_catalogo(backlog, filtros)
    pendentes = backlog.filter(status__in=STATUS_PENDENTES).count()
    pendentes_hoje = backlog.filter(
        status__in=STATUS_PENDENTES,
        data_hora_inicio__lt=hoje_fim,
    ).count()

    retornos = _contagem_retornos(filtros)
    retornos_pendentes = (
        retornos["prontuarios"]["atrasados"]
        + retornos["prontuarios"]["proximos"]
        + retornos["vacinas"]["atrasadas"]
        + retornos["vacinas"]["proximas"]
        + retornos["vermifugacoes"]["atrasadas"]
        + retornos["vermifugacoes"]["proximas"]
    )

    novos_pacientes = Pet.objects.filter(
        criado_em__gte=filtros.inicio_dt,
        criado_em__lt=filtros.fim_dt,
    ).count()

    return {
        "total_tutores": Tutor.objects.count(),
        "total_animais": Pet.objects.count(),
        "novos_pacientes": novos_pacientes,
        "atendimentos_hoje": atendimentos_hoje,
        "atendimentos_periodo": totais["total"],
        "atendimentos_pendentes": pendentes,
        "atendimentos_pendentes_hoje": pendentes_hoje,
        "atendimentos_pendentes_periodo": totais["pendentes"],
        "cancelamentos": totais["cancelados"],
        "faltas": totais["faltas"],
        "realizados": totais["realizados"],
        "retornos_pendentes": retornos_pendentes,
        "retornos_pendentes_detalhe": retornos,
        "vacinas_proximas_vencimento": retornos["vacinas"]["proximas"],
        "atendimentos_por_profissional": _atendimentos_por_profissional(base),
        "ocupacao_agenda": _ocupacao_agenda(filtros),
    }


# ---------------------------------------------------------------------------
# Indicadores históricos
# ---------------------------------------------------------------------------
def _serie_por_dia(
    inicio: date,
    fim: date,
    filtros: FiltrosDashboard,
    incluir_status=True,
) -> list:
    """Totais diários preenchendo dias sem atendimento."""
    base = Atendimento.objects.filter(
        data_hora_inicio__gte=_inicio_dia(inicio),
        data_hora_inicio__lt=_fim_dia_exclusivo(fim),
    )
    base = _aplicar_filtros_catalogo(
        base, filtros, incluir_status=incluir_status
    )
    agregados = (
        base.annotate(dia=TruncDate("data_hora_inicio"))
        .values("dia")
        .annotate(
            total=Count("id"),
            realizados=Count(
                "id", filter=Q(status=Atendimento.Status.REALIZADO)
            ),
            pendentes=Count("id", filter=Q(status__in=STATUS_PENDENTES)),
            cancelados=Count(
                "id", filter=Q(status=Atendimento.Status.CANCELADO)
            ),
            faltas=Count("id", filter=Q(status=Atendimento.Status.FALTOU)),
        )
    )
    por_dia = {_como_date(item["dia"]): item for item in agregados}

    serie = []
    for dia in _dias_entre(inicio, fim):
        dados = por_dia.get(dia, {})
        serie.append(
            {
                "iso": dia.isoformat(),
                "label": DIAS_SEMANA_CURTOS[dia.weekday()],
                "data": dia.strftime("%d/%m"),
                "hoje": dia == filtros.hoje,
                "total": dados.get("total", 0),
                "realizados": dados.get("realizados", 0),
                "pendentes": dados.get("pendentes", 0),
                "cancelados": dados.get("cancelados", 0),
                "faltas": dados.get("faltas", 0),
            }
        )
    return serie


def _serie_por_semana(
    inicio: date, fim: date, filtros: FiltrosDashboard
) -> list:
    """Totais por semana (segunda a domingo) dentro da janela informada."""
    base = Atendimento.objects.filter(
        data_hora_inicio__gte=_inicio_dia(inicio),
        data_hora_inicio__lt=_fim_dia_exclusivo(fim),
    )
    base = _aplicar_filtros_catalogo(base, filtros)
    agregados = (
        base.annotate(semana=TruncWeek("data_hora_inicio"))
        .values("semana")
        .annotate(
            total=Count("id"),
            realizados=Count(
                "id", filter=Q(status=Atendimento.Status.REALIZADO)
            ),
            pendentes=Count("id", filter=Q(status__in=STATUS_PENDENTES)),
            cancelados=Count(
                "id", filter=Q(status=Atendimento.Status.CANCELADO)
            ),
            faltas=Count("id", filter=Q(status=Atendimento.Status.FALTOU)),
        )
    )
    por_semana = {}
    for item in agregados:
        por_semana[_como_date(item["semana"])] = item

    serie = []
    cursor = _segunda(inicio)
    while cursor <= fim:
        dados = por_semana.get(cursor, {})
        fim_semana = min(cursor + timedelta(days=6), fim)
        serie.append(
            {
                "inicio": cursor.isoformat(),
                "fim": fim_semana.isoformat(),
                "label": _label_semana(cursor, fim_semana),
                "total": dados.get("total", 0),
                "realizados": dados.get("realizados", 0),
                "pendentes": dados.get("pendentes", 0),
                "cancelados": dados.get("cancelados", 0),
                "faltas": dados.get("faltas", 0),
            }
        )
        cursor += timedelta(days=7)
    return serie


def _serie_por_mes(
    inicio: date, fim: date, filtros: FiltrosDashboard
) -> list:
    """Totais por mês dentro da janela informada."""
    base = Atendimento.objects.filter(
        data_hora_inicio__gte=_inicio_dia(inicio),
        data_hora_inicio__lt=_fim_dia_exclusivo(fim),
    )
    base = _aplicar_filtros_catalogo(base, filtros)
    agregados = (
        base.annotate(mes=TruncMonth("data_hora_inicio"))
        .values("mes")
        .annotate(
            total=Count("id"),
            realizados=Count(
                "id", filter=Q(status=Atendimento.Status.REALIZADO)
            ),
            pendentes=Count("id", filter=Q(status__in=STATUS_PENDENTES)),
            cancelados=Count(
                "id", filter=Q(status=Atendimento.Status.CANCELADO)
            ),
            faltas=Count("id", filter=Q(status=Atendimento.Status.FALTOU)),
        )
    )
    por_mes = {}
    for item in agregados:
        por_mes[_como_date(item["mes"])] = item

    serie = []
    cursor = _primeiro_dia_mes(inicio)
    while cursor <= fim:
        dados = por_mes.get(cursor, {})
        ultimo_dia = min(
            date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1]),
            fim,
        )
        serie.append(
            {
                "mes": f"{cursor.year:04d}-{cursor.month:02d}",
                "inicio": cursor.isoformat(),
                "fim": ultimo_dia.isoformat(),
                "label": _label_mes(cursor),
                "total": dados.get("total", 0),
                "realizados": dados.get("realizados", 0),
                "pendentes": dados.get("pendentes", 0),
                "cancelados": dados.get("cancelados", 0),
                "faltas": dados.get("faltas", 0),
            }
        )
        cursor = _mes_menos(cursor, -1)
    return serie


def _distribuicao_status(filtros: FiltrosDashboard, base) -> list:
    contagem = {
        item["status"]: item["total"]
        for item in base.values("status").annotate(total=Count("id"))
    }
    return [
        {"status": valor, "label": rotulo, "total": contagem.get(valor, 0)}
        for valor, rotulo in Atendimento.Status.choices
    ]


def _servicos(base, limite=LIMITE_SERVICOS) -> list:
    rotulos = dict(Atendimento.TipoServico.choices)
    agregados = (
        base.values("tipo_servico")
        .annotate(total=Count("id"))
        .order_by("-total", "tipo_servico")[:limite]
    )
    return [
        {
            "tipo_servico": item["tipo_servico"],
            "nome": rotulos.get(item["tipo_servico"], item["tipo_servico"]),
            "total": item["total"],
        }
        for item in agregados
    ]


def _comparacao_periodos(filtros: FiltrosDashboard) -> dict:
    dias = filtros.dias
    anterior_fim = filtros.data_inicio - timedelta(days=1)
    anterior_inicio = anterior_fim - timedelta(days=dias - 1)

    def resumo(inicio: date, fim: date) -> dict:
        base = Atendimento.objects.filter(
            data_hora_inicio__gte=_inicio_dia(inicio),
            data_hora_inicio__lt=_fim_dia_exclusivo(fim),
        )
        base = _aplicar_filtros_catalogo(base, filtros)
        totais = base.aggregate(
            total=Count("id"),
            realizados=Count(
                "id", filter=Q(status=Atendimento.Status.REALIZADO)
            ),
            cancelados=Count(
                "id", filter=Q(status=Atendimento.Status.CANCELADO)
            ),
            faltas=Count("id", filter=Q(status=Atendimento.Status.FALTOU)),
        )
        return {
            "data_inicio": inicio.isoformat(),
            "data_fim": fim.isoformat(),
            **totais,
        }

    atual = resumo(filtros.data_inicio, filtros.data_fim)
    anterior = resumo(anterior_inicio, anterior_fim)
    variacao_absoluta = atual["total"] - anterior["total"]
    variacao_percentual = (
        round(variacao_absoluta / anterior["total"] * 100)
        if anterior["total"]
        else None
    )
    return {
        "periodo_atual": atual,
        "periodo_anterior": anterior,
        "variacao_absoluta": variacao_absoluta,
        "variacao_percentual": variacao_percentual,
    }


def indicadores_historicos(filtros: FiltrosDashboard) -> dict:
    """Séries semanais/mensais, evolução, distribuição, serviços e comparação."""
    if filtros.personalizado:
        inicio_hist = filtros.data_inicio
        fim_hist = filtros.data_fim
        # Em período explícito as séries são recortadas exatamente no filtro;
        # a primeira semana/mês pode ser parcial.
        inicio_semanas = inicio_hist
        inicio_meses = inicio_hist
    else:
        fim_hist = filtros.data_fim
        inicio_hist = fim_hist - timedelta(days=DIAS_HISTORICO_PADRAO - 1)
        inicio_semanas = _segunda(fim_hist) - timedelta(weeks=SEMANAS_HISTORICO - 1)
        inicio_meses = _mes_menos(_primeiro_dia_mes(fim_hist), MESES_HISTORICO - 1)

    base_hist = Atendimento.objects.filter(
        data_hora_inicio__gte=_inicio_dia(inicio_hist),
        data_hora_inicio__lt=_fim_dia_exclusivo(fim_hist),
    )
    base_hist = _aplicar_filtros_catalogo(base_hist, filtros)

    por_dia = _serie_por_dia(inicio_hist, fim_hist, filtros)
    return {
        "periodo": {
            "data_inicio": inicio_hist.isoformat(),
            "data_fim": fim_hist.isoformat(),
            "dias": (fim_hist - inicio_hist).days + 1,
        },
        "por_semana": _serie_por_semana(
            inicio_semanas, fim_hist, filtros
        ),
        "por_mes": _serie_por_mes(inicio_meses, fim_hist, filtros),
        "por_dia": por_dia,
        "evolucao": por_dia,
        "distribuicao_status": _distribuicao_status(filtros, base_hist),
        "servicos": _servicos(base_hist, LIMITE_SERVICOS_HISTORICO),
        "total_periodo": base_hist.aggregate(total=Count("id"))["total"],
        "comparacao": _comparacao_periodos(filtros),
    }


# ---------------------------------------------------------------------------
# Payload principal e opções de filtro
# ---------------------------------------------------------------------------
def serie_semana_principal(filtros: FiltrosDashboard) -> list:
    if filtros.personalizado:
        inicio = max(
            filtros.data_inicio,
            filtros.data_fim - timedelta(days=DIAS_SERIE - 1),
        )
    else:
        inicio = filtros.data_fim - timedelta(days=DIAS_SERIE - 1)
    return _serie_por_dia(inicio, filtros.data_fim, filtros)


def variacao_serie_principal(filtros: FiltrosDashboard) -> int | None:
    """Variação do recorte da série (7 dias) contra o recorte anterior."""
    serie = serie_semana_principal(filtros)
    if not serie:
        return None
    inicio = date.fromisoformat(serie[0]["iso"])
    dias = len(serie)
    anterior_fim = inicio - timedelta(days=1)
    anterior_inicio = anterior_fim - timedelta(days=dias - 1)

    def total(inicio_dia: date, fim_dia: date) -> int:
        base = Atendimento.objects.filter(
            data_hora_inicio__gte=_inicio_dia(inicio_dia),
            data_hora_inicio__lt=_fim_dia_exclusivo(fim_dia),
        )
        base = _aplicar_filtros_catalogo(base, filtros)
        return base.aggregate(total=Count("id"))["total"]

    atual = total(inicio, filtros.data_fim)
    anterior = total(anterior_inicio, anterior_fim)
    if not anterior:
        return None
    return round((atual - anterior) / anterior * 100)


def status_serie_principal(filtros: FiltrosDashboard) -> list:
    serie = serie_semana_principal(filtros)
    inicio = date.fromisoformat(serie[0]["iso"])
    base = Atendimento.objects.filter(
        data_hora_inicio__gte=_inicio_dia(inicio),
        data_hora_inicio__lt=_fim_dia_exclusivo(filtros.data_fim),
    )
    base = _aplicar_filtros_catalogo(base, filtros)
    return _distribuicao_status(filtros, base)


def servicos_principal(filtros: FiltrosDashboard) -> list:
    return _servicos(_atendimentos_no_periodo(filtros), LIMITE_SERVICOS)


def opcoes_filtros() -> dict:
    from django.db.models import Max, Min

    limites = Atendimento.objects.aggregate(
        primeira=Min("data_hora_inicio"),
        ultima=Max("data_hora_inicio"),
    )
    hoje = timezone.localdate()

    def iso_local(valor):
        if valor is None:
            return None
        return timezone.localtime(valor).date().isoformat()

    return {
        "profissionais": [
            {
                "id": str(profissional.pk),
                "nome": profissional.nome,
                "cargo": profissional.cargo,
            }
            for profissional in Profissional.objects.filter(ativo=True)
        ],
        "tipos_servico": [
            {"value": valor, "label": rotulo}
            for valor, rotulo in Atendimento.TipoServico.choices
        ],
        "status": [
            {"value": valor, "label": rotulo}
            for valor, rotulo in Atendimento.Status.choices
        ],
        "periodo_padrao": {
            "data_inicio": (
                hoje - timedelta(days=DIAS_SERVICOS - 1)
            ).isoformat(),
            "data_fim": hoje.isoformat(),
        },
        "limites": {
            "primeira_data": iso_local(limites["primeira"]),
            "ultima_data": iso_local(limites["ultima"]),
        },
        "hoje": hoje.isoformat(),
    }
