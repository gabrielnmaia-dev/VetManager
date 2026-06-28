from rest_framework import viewsets, filters
from .models import Prontuario, Vacina
from .serializers import ProntuarioSerializer, VacinaSerializer
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page


class ProntuarioViewSet(viewsets.ModelViewSet):
    queryset = Prontuario.objects.select_related(
        "pet", "veterinario__profissional"
    ).prefetch_related("vacinas").all()
    serializer_class = ProntuarioSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["pet__nome", "diagnostico"]

    def get_queryset(self):
        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs


class VacinaViewSet(viewsets.ModelViewSet):
    queryset = Vacina.objects.select_related("pet").all()
    serializer_class = VacinaSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["nome_vacina", "pet__nome"]

    def get_queryset(self):
        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs
    @method_decorator(cache_page(60 * 5))  # cache de 5 minutos
    def list(self, request, *args, **kwargs):
            return super().list(request, *args, **kwargs)