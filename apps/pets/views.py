from rest_framework import viewsets
from .models import Pet
from .serializers import PetSerializer
 
 
class PetViewSet(viewsets.ModelViewSet):
    queryset = Pet.objects.select_related("tutor").all()
    serializer_class = PetSerializer
 
    def get_queryset(self):
        qs = super().get_queryset()
        tutor_id = self.request.query_params.get("tutor")
        if tutor_id:
            qs = qs.filter(tutor_id=tutor_id)
        return qs