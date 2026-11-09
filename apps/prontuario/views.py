from rest_framework import viewsets, filters
from apps.base.views import AuditModelViewSetMixin
from .models import Prontuario, Vacina
from .serializers import ProntuarioSerializer, VacinaSerializer


class ProntuarioViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    queryset = Prontuario.objects.select_related(
        "pet", "veterinario__profissional"
    ).prefetch_related("vacinas").all()
    serializer_class = ProntuarioSerializer
    # Acesso restrito a admin/veterinário (RoleBasedPermission, em base.py).
    role_policy = ("admin", "veterinario")
    filter_backends = [filters.SearchFilter]
    search_fields = ["pet__nome", "diagnostico"]
    audit_entidade = "prontuario"
    audit_exclude = ("observacoes", "prescricao")  # dados sensíveis omitidos do snapshot padrão

    def get_queryset(self):
        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    # Obs.: o cache_page que existia aqui foi removido. Ele devolvia a
    # resposta em cache antes da checagem de grupo (que ficava no
    # get_queryset), vazando prontuários para qualquer usuário logado,
    # e mostrava dados desatualizados por 5 min após criar/editar.


class VacinaViewSet(AuditModelViewSetMixin, viewsets.ModelViewSet):
    queryset = Vacina.objects.select_related("pet").all()
    serializer_class = VacinaSerializer
    # Acesso restrito a admin/veterinário (RoleBasedPermission, em base.py).
    role_policy = ("admin", "veterinario")
    filter_backends = [filters.SearchFilter]
    search_fields = ["nome_vacina", "pet__nome"]
    audit_entidade = "vacina"

    def get_queryset(self):
        qs = super().get_queryset()
        pet_id = self.request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs