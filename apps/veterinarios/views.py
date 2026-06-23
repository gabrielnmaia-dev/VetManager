from rest_framework import viewsets, filters
from .models import Profissional
from .serializers import ProfissionalSerializer
# Create your views here.


class ProfissionalViewSet(viewsets.ModelViewSet):
    queryset = Profissional.objects.select_related("veterinario").all()
    serializer_class = ProfissionalSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["nome", "cargo"]
