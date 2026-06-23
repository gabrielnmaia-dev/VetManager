from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, filters
from .models import Tutor
from .serializers import TutorSerializer
 
 
class TutorViewSet(viewsets.ModelViewSet):
    queryset = Tutor.objects.all()
    serializer_class = TutorSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["nome", "telefone", "cpf"]
 
 