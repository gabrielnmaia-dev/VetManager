from rest_framework import viewsets, filters

from .models import Tutor
from .serializers import (
    TutorComPetsSerializer,
    TutorCreateSerializer,
    TutorSerializer,
)


class TutorViewSet(viewsets.ModelViewSet):
    queryset = Tutor.objects.prefetch_related("pets").all()
    serializer_class = TutorSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["nome", "telefone", "cpf"]

    def get_serializer_class(self):
        # Busca rápida: list/retrieve devolvem o tutor já com os pets.
        if self.action in ("list", "retrieve"):
            return TutorComPetsSerializer
        # POST aceita o payload legado e o novo com "pets" aninhado.
        if self.action == "create":
            return TutorCreateSerializer
        # PUT/PATCH/DELETE seguem com o serializer original (sem cascata).
        return super().get_serializer_class()
