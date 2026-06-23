from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from apps.atendimentos.models import Atendimento
from apps.pets.models import Pet
from apps.tutores.models import Tutor
from django.utils import timezone


class DashboardView(APIView):

    @extend_schema(responses={200: dict})
    def get(self, request):
        hoje = timezone.now().date()
        return Response({
            "atendimentos_hoje": Atendimento.objects.filter(
                data_hora_inicio__date=hoje
            ).count(),
            "atendimentos_pendentes": Atendimento.objects.filter(
                status="agendado"
            ).count(),
            "total_pets": Pet.objects.count(),
            "total_tutores": Tutor.objects.count(),
        })