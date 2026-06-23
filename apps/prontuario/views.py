
from rest_framework import viewsets
from .models import Prontuario, Vacina
from .serializers import ProntuarioSerializer, VacinaSerializer


class ProntuarioViewSet(viewsets.ModelViewSet):
    queryset = Prontuario.objects.select_related(
        "pet", "veterinario__profissional"
    ).prefetch_related("vacinas").all()
    serializer_class = ProntuarioSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs


class VacinaViewSet(viewsets.ModelViewSet):
    queryset = Vacina.objects.select_related("pet").all()
    serializer_class = VacinaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs