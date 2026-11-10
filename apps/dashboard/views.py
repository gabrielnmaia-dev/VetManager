"""KPIs e agregações do painel inicial.

O painel é a primeira tela após o login e concentra indicadores de agenda,
série histórica, distribuição por status/serviço e alertas clínicos. Toda a
agregação é feita no backend (ver ``apps.dashboard.services``) para evitar que
o frontend baixe a lista completa de atendimentos e para respeitar a fronteira
de segurança/permissões.

Endpoints:

* ``GET /api/v1/dashboard/`` — payload completo usado pela tela principal.
* ``GET /api/v1/dashboard/operacional/`` — apenas KPIs operacionais.
* ``GET /api/v1/dashboard/historico/`` — séries e comparações históricas.
* ``GET /api/v1/dashboard/filtros/`` — opções para os filtros do painel.
"""

from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.atendimentos.models import Atendimento
from apps.prontuario.models import Vacina, Vermifugacao

from .services import (
    indicadores_historicos,
    indicadores_operacionais,
    obter_filtros,
    opcoes_filtros,
    serie_semana_principal,
    servicos_principal,
    status_serie_principal,
    variacao_serie_principal,
)

# Limites de itens retornados nas listas do painel.
LIMITE_AGENDA = 20
LIMITE_ALERTAS = 8


def _hora_local(valor):
    """Formata o horário no fuso da aplicação, aceitando datetimes naive."""
    if valor is None:
        return ""
    if timezone.is_aware(valor):
        valor = timezone.localtime(valor)
    return valor.strftime("%H:%M")


def _alertas_clinicos(filtros):
    """Contagens e itens de retornos de vacina/vermifugação atrasados/próximos.

    Só entram retornos com data definida. A janela "próxima" é a mesma usada
    pelos módulos clínicos (``DIAS_ALERTA_RETORNO``), mantendo o painel
    coerente com as telas de vacinação e vermifugação.
    """
    hoje = filtros.hoje
    limite_vacina = hoje + timedelta(days=Vacina.DIAS_ALERTA_RETORNO)
    limite_vermifugo = hoje + timedelta(
        days=Vermifugacao.DIAS_ALERTA_RETORNO
    )

    vacinas = Vacina.objects.filter(data_retorno__isnull=False)
    vermifugacoes = Vermifugacao.objects.filter(data_retorno__isnull=False)
    if filtros.profissional_id:
        vacinas = vacinas.filter(
            veterinario__profissional_id=filtros.profissional_id
        )
        vermifugacoes = vermifugacoes.filter(
            veterinario__profissional_id=filtros.profissional_id
        )

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


def _agenda_do_dia(filtros):
    """Atendimentos de hoje em ordem cronológica, com dados para navegação.

    Respeita os filtros de profissional, tipo e status; o recorte temporal é
    sempre o dia local de hoje (é a agenda do dia, não o período do painel).
    """
    atendimentos = Atendimento.objects.filter(
        data_hora_inicio__date=filtros.hoje
    )
    if filtros.profissional_id:
        atendimentos = atendimentos.filter(
            profissional_id=filtros.profissional_id
        )
    if filtros.tipo_servico:
        atendimentos = atendimentos.filter(tipo_servico=filtros.tipo_servico)
    if filtros.status:
        atendimentos = atendimentos.filter(status=filtros.status)
    atendimentos = atendimentos.select_related(
        "pet__tutor", "profissional"
    ).order_by("data_hora_inicio")[:LIMITE_AGENDA]
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
        filtros = obter_filtros(request.query_params)
        grupos = list(user.groups.values_list("name", flat=True))

        operacional = indicadores_operacionais(filtros)
        historico = indicadores_historicos(filtros)

        data = {
            "usuario": user.username,
            "perfil": grupos[0] if grupos else "sem perfil",
            "gerado_em": timezone.now().isoformat(),
            "filtros": filtros.como_dict(),
            # Chaves mantidas para compatibilidade com a tela e testes antigos.
            "atendimentos_hoje": operacional["atendimentos_hoje"],
            "atendimentos_pendentes": operacional["atendimentos_pendentes"],
            "total_pets": operacional["total_animais"],
            "total_tutores": operacional["total_tutores"],
            "serie_semanal": serie_semana_principal(filtros),
            "variacao_semanal": variacao_serie_principal(filtros),
            "status_semana": status_serie_principal(filtros),
            "servicos": servicos_principal(filtros),
            "servicos_periodo_dias": filtros.dias,
            "alertas": _alertas_clinicos(filtros),
            "agenda_hoje": _agenda_do_dia(filtros),
            # Blocos novos, também expostos em endpoints dedicados.
            "operacional": operacional,
            "historico": historico,
            "comparacao": historico["comparacao"],
        }

        return Response(data)


class DashboardOperacionalView(APIView):
    """Indicadores operacionais isolados, sem depender de paginação."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        filtros = obter_filtros(request.query_params)
        return Response(
            {
                "filtros": filtros.como_dict(),
                "gerado_em": timezone.now().isoformat(),
                **indicadores_operacionais(filtros),
            }
        )


class DashboardHistoricoView(APIView):
    """Séries históricas, distribuição, ranking e comparação entre períodos."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        filtros = obter_filtros(request.query_params)
        return Response(
            {
                "filtros": filtros.como_dict(),
                "gerado_em": timezone.now().isoformat(),
                **indicadores_historicos(filtros),
            }
        )


class DashboardFiltrosView(APIView):
    """Opções de filtro (profissionais, tipos, status e limites de data)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(opcoes_filtros())
