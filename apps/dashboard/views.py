"""KPIs e agregações do painel inicial.

O painel é a primeira tela após o login e concentra indicadores de agenda,
série histórica, distribuição por status/serviço e alertas clínicos. Toda a
agregação é feita no backend para evitar que o frontend baixe a lista completa
de atendimentos e para respeitar a fronteira de segurança/permissões.
"""

from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.atendimentos.models import Atendimento
from apps.pets.models import Pet
from apps.prontuario.models import Vacina, Vermifugacao
from apps.tutores.models import Tutor

# Janela da série histórica e da comparação "7 dias anteriores".
DIAS_SERIE = 7
# Janela usada no ranking de serviços (evita distorção de dias isolados).
DIAS_SERVICOS = 30
# Limites de itens retornados nas listas do painel.
LIMITE_AGENDA = 20
LIMITE_ALERTAS = 8

DIAS_SEMANA_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _hora_local(valor):
    """Formata o horário no fuso da aplicação, aceitando datetimes naive."""
    if valor is None:
        return ""
    if timezone.is_aware(valor):
        valor = timezone.localtime(valor)
    return valor.strftime("%H:%M")


def _variacao_percentual(atual, anterior):
    """Variação percentual inteira; ``None`` quando não há base de comparação."""
    if not anterior:
        return None
    return round(((atual - anterior) / anterior) * 100)


def _serie_semanal(hoje):
    """Totais por dia dos últimos 7 dias, incluindo dias sem atendimento."""
    inicio = hoje - timedelta(days=DIAS_SERIE - 1)
    agregados = (
        Atendimento.objects.filter(data_hora_inicio__date__gte=inicio)
        .annotate(dia=TruncDate("data_hora_inicio"))
        .values("dia")
        .annotate(
            total=Count("id"),
            realizados=Count(
                "id", filter=Q(status=Atendimento.Status.REALIZADO)
            ),
            pendentes=Count(
                "id",
                filter=Q(
                    status__in=[
                        Atendimento.Status.AGENDADO,
                        Atendimento.Status.CONFIRMADO,
                    ]
                ),
            ),
        )
    )
    por_dia = {item["dia"]: item for item in agregados}

    serie = []
    for indice in range(DIAS_SERIE):
        dia = inicio + timedelta(days=indice)
        dados = por_dia.get(dia, {})
        serie.append(
            {
                "iso": dia.isoformat(),
                "label": DIAS_SEMANA_CURTOS[dia.weekday()],
                "data": dia.strftime("%d/%m"),
                "hoje": dia == hoje,
                "total": dados.get("total", 0),
                "realizados": dados.get("realizados", 0),
                "pendentes": dados.get("pendentes", 0),
            }
        )
    return serie


def _status_semana(hoje):
    """Contagem por status na mesma janela da série semanal."""
    inicio = hoje - timedelta(days=DIAS_SERIE - 1)
    contagem = {
        item["status"]: item["total"]
        for item in Atendimento.objects.filter(
            data_hora_inicio__date__gte=inicio
        )
        .values("status")
        .annotate(total=Count("id"))
    }
    return [
        {
            "status": valor,
            "label": rotulo,
            "total": contagem.get(valor, 0),
        }
        for valor, rotulo in Atendimento.Status.choices
    ]


def _servicos_mais_procurados(hoje):
    """Top 5 tipos de serviço nos últimos 30 dias."""
    inicio = hoje - timedelta(days=DIAS_SERVICOS - 1)
    rotulos = dict(Atendimento.TipoServico.choices)
    agregados = (
        Atendimento.objects.filter(data_hora_inicio__date__gte=inicio)
        .values("tipo_servico")
        .annotate(total=Count("id"))
        .order_by("-total", "tipo_servico")[:5]
    )
    return [
        {
            "tipo_servico": item["tipo_servico"],
            "nome": rotulos.get(item["tipo_servico"], item["tipo_servico"]),
            "total": item["total"],
        }
        for item in agregados
    ]


def _alertas_clinicos(hoje):
    """Contagens e itens de retornos de vacina/vermifugação atrasados/próximos.

    Só entram retornos com data definida. A janela "próxima" é a mesma usada
    pelos módulos clínicos (``DIAS_ALERTA_RETORNO``), mantendo o painel
    coerente com as telas de vacinação e vermifugação.
    """
    limite_vacina = hoje + timedelta(days=Vacina.DIAS_ALERTA_RETORNO)
    limite_vermifugo = hoje + timedelta(
        days=Vermifugacao.DIAS_ALERTA_RETORNO
    )

    vacinas = Vacina.objects.filter(data_retorno__isnull=False)
    vermifugacoes = Vermifugacao.objects.filter(data_retorno__isnull=False)

    contagens = {
        "vacinas": {
            "atrasadas": vacinas.filter(data_retorno__lt=hoje).count(),
            "proximas": vacinas.filter(
                data_retorno__gte=hoje, data_retorno__lte=limite_vacina
            ).count(),
        },
        "vermifugacoes": {
            "atrasadas": vermifugacoes.filter(
                data_retorno__lt=hoje
            ).count(),
            "proximas": vermifugacoes.filter(
                data_retorno__gte=hoje, data_retorno__lte=limite_vermifugo
            ).count(),
        },
    }

    itens = []
    for vacina in (
        vacinas.filter(data_retorno__lte=limite_vacina)
        .select_related("pet__tutor")
        .order_by("data_retorno")[:LIMITE_ALERTAS]
    ):
        itens.append(
            {
                "tipo": "vacina",
                "id": vacina.id,
                "pet_id": str(vacina.pet_id),
                "pet": vacina.pet.nome,
                "tutor": vacina.pet.tutor.nome,
                "descricao": vacina.nome_vacina,
                "data_retorno": vacina.data_retorno.isoformat(),
                "dias_para_retorno": (
                    vacina.data_retorno - hoje
                ).days,
                "situacao": vacina.situacao,
            }
        )
    for vermifugacao in (
        vermifugacoes.filter(data_retorno__lte=limite_vermifugo)
        .select_related("pet__tutor")
        .order_by("data_retorno")[:LIMITE_ALERTAS]
    ):
        itens.append(
            {
                "tipo": "vermifugacao",
                "id": vermifugacao.id,
                "pet_id": str(vermifugacao.pet_id),
                "pet": vermifugacao.pet.nome,
                "tutor": vermifugacao.pet.tutor.nome,
                "descricao": vermifugacao.produto,
                "data_retorno": vermifugacao.data_retorno.isoformat(),
                "dias_para_retorno": (
                    vermifugacao.data_retorno - hoje
                ).days,
                "situacao": vermifugacao.situacao,
            }
        )

    itens.sort(key=lambda item: item["data_retorno"])
    contagens["itens"] = itens[:LIMITE_ALERTAS]
    return contagens


def _agenda_do_dia(hoje):
    """Atendimentos de hoje em ordem cronológica, com dados para navegação."""
    atendimentos = (
        Atendimento.objects.filter(data_hora_inicio__date=hoje)
        .select_related("pet__tutor", "profissional")
        .order_by("data_hora_inicio")[:LIMITE_AGENDA]
    )
    agenda = []
    for atendimento in atendimentos:
        profissional = atendimento.profissional
        agenda.append(
            {
                "id": str(atendimento.id),
                "hora": _hora_local(atendimento.data_hora_inicio),
                "pet_id": str(atendimento.pet_id),
                "pet": atendimento.pet.nome,
                "tutor": atendimento.pet.tutor.nome,
                "tipo_servico": atendimento.tipo_servico,
                "tipo_servico_display": atendimento.get_tipo_servico_display(),
                "status": atendimento.status,
                "status_display": atendimento.get_status_display(),
                "profissional": (
                    profissional.nome
                    if profissional
                    else atendimento.nome_profissional
                ),
            }
        )
    return agenda


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        user = request.user
        hoje = timezone.localdate()

        grupos = list(user.groups.values_list("name", flat=True))

        serie = _serie_semanal(hoje)
        inicio_atual = hoje - timedelta(days=DIAS_SERIE - 1)
        inicio_anterior = inicio_atual - timedelta(days=DIAS_SERIE)
        total_atual = sum(dia["total"] for dia in serie)
        total_anterior = Atendimento.objects.filter(
            data_hora_inicio__date__gte=inicio_anterior,
            data_hora_inicio__date__lt=inicio_atual,
        ).count()

        data = {
            "usuario": user.username,
            "perfil": grupos[0] if grupos else "sem perfil",
            "atendimentos_hoje": Atendimento.objects.filter(
                data_hora_inicio__date=hoje
            ).count(),
            "atendimentos_pendentes": Atendimento.objects.filter(
                status=Atendimento.Status.AGENDADO
            ).count(),
            "total_pets": Pet.objects.count(),
            "total_tutores": Tutor.objects.count(),
            "serie_semanal": serie,
            "variacao_semanal": _variacao_percentual(
                total_atual, total_anterior
            ),
            "status_semana": _status_semana(hoje),
            "servicos": _servicos_mais_procurados(hoje),
            "servicos_periodo_dias": DIAS_SERVICOS,
            "alertas": _alertas_clinicos(hoje),
            "agenda_hoje": _agenda_do_dia(hoje),
        }

        return Response(data)
