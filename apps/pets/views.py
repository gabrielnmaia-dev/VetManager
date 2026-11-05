from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, filters
from .models import Pet
from .serializers import PetSerializer


class PetViewSet(viewsets.ModelViewSet):
    queryset = Pet.objects.select_related("tutor").all()
    serializer_class = PetSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["nome", "especie", "raca", "tutor__nome"]

    def get_queryset(self):
        qs = super().get_queryset()
        tutor_id = self.request.query_params.get("tutor")
        if tutor_id:
            qs = qs.filter(tutor_id=tutor_id)
        return qs
    
    # @method_decorator(cache_page(60 * 5))  # cache de 5 minutos
    # def list(self, request, *args, **kwargs):
    #         return super().list(request, *args, **kwargs)