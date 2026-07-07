from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from .models import Prontuario, Vacina
from .serializers import ProntuarioSerializer, VacinaSerializer


class ProntuarioViewSet(viewsets.ModelViewSet):
    queryset = Prontuario.objects.select_related(
        "pet", "veterinario__profissional"
    ).prefetch_related("vacinas").all()
    serializer_class = ProntuarioSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["pet__nome", "diagnostico"]

    def get_queryset(self):
        user = self.request.user
        if not user.groups.filter(name__in=['admin', 'veterinario']).exists():
            raise PermissionDenied("Acesso restrito.")

        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    @method_decorator(cache_page(60 * 5))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class VacinaViewSet(viewsets.ModelViewSet):
    queryset = Vacina.objects.select_related("pet").all()
    serializer_class = VacinaSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["nome_vacina", "pet__nome"]

    def get_queryset(self):
        user = self.request.user
        if not user.groups.filter(name__in=['admin', 'veterinario']).exists():
            raise PermissionDenied("Acesso restrito.")

        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    # @method_decorator(cache_page(60 * 5))
    # def list(self, request, *args, **kwargs):
    #     return super().list(request, *args, **kwargs)