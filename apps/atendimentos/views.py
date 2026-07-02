from rest_framework import viewsets, filters
from .models import Atendimento
from .serializers import AtendimentoSerializer
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page


class AtendimentoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Atendimento.objects.select_related("pet", "pet__tutor").all()
    serializer_class = AtendimentoSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["pet__nome", "pet__tutor__nome", "nome_profissional"]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        pet_id = params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)

        status_param = params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        data_inicio = params.get("data_inicio")
        data_fim = params.get("data_fim")
        if data_inicio:
            qs = qs.filter(data_hora_inicio__date__gte=data_inicio)
        if data_fim:
            qs = qs.filter(data_hora_inicio__date__lte=data_fim)

        return qs

    @method_decorator(cache_page(60 * 5))  # cache de 5 minutos
    def list(self, request, *args, **kwargs):
            return super().list(request, *args, **kwargs)