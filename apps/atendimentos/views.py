from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Atendimento
from .serializers import (
    AtendimentoRapidoResponseSerializer,
    AtendimentoRapidoSerializer,
    AtendimentoSerializer,
)


class AtendimentoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = Atendimento.objects.select_related(
        "pet", "pet__tutor", "profissional"
    ).all()
    serializer_class = AtendimentoSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = [
        "pet__nome",
        "pet__tutor__nome",
        "profissional__nome",
        "nome_profissional",
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        pet_id = params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)

        profissional_id = params.get("profissional")
        if profissional_id:
            qs = qs.filter(profissional_id=profissional_id)

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

    def get_serializer_class(self):
        # Ação de atendimento rápido tem payload e resposta próprios.
        if self.action == "rapido":
            return AtendimentoRapidoSerializer
        return super().get_serializer_class()

    @extend_schema(
        operation_id="atendimento_rapido_create",
        summary="Criar atendimento rápido (tutor + pet em uma chamada)",
        description=(
            "Cria um atendimento em uma única requisição. Informe `tutor_id`/"
            "`pet_id` para usar registros já existentes ou `tutor`/`pet` para "
            "cadastrá-los em cascata — nunca os dois ao mesmo tempo. O pet "
            "existente precisa pertencer ao tutor informado. Para o "
            "profissional, envie `profissional_id` (preferencial) ou, por "
            "compatibilidade, `nome_profissional` — pelo menos um dos dois. "
            "O mesmo profissional não pode ter dois atendimentos sobrepostos "
            "(cancelados são ignorados). Tudo é criado em uma única transação "
            "(rollback em caso de falha)."
        ),
        request=AtendimentoRapidoSerializer,
        responses={201: AtendimentoRapidoResponseSerializer},
        examples=[
            OpenApiExample(
                "Tutor e pet existentes",
                summary="Só ids: nada é cadastrado",
                value={
                    "tutor_id": "3f1d2c9a-1c7b-4a2e-9a10-5f2b8d7c6e41",
                    "pet_id": "b51f3f9e-9a5a-4f8f-8c8e-6c1d0a9b2c73",
                    "profissional_id": "7a2c1e5f-0b8d-4c3a-9f21-8e6d5b4a3c2d",
                    "tipo_servico": "consulta",
                    "data_hora_inicio": "2026-10-20T09:00:00Z",
                    "duracao_minutos": 30,
                    "queixa": "Vômitos desde ontem",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Tutor existente e pet novo",
                summary="Cascata só no pet",
                value={
                    "tutor_id": "3f1d2c9a-1c7b-4a2e-9a10-5f2b8d7c6e41",
                    "pet": {
                        "nome": "Mel",
                        "especie": "Cão",
                        "raca": "SRD",
                        "sexo": "F",
                    },
                    "profissional_id": "7a2c1e5f-0b8d-4c3a-9f21-8e6d5b4a3c2d",
                    "tipo_servico": "vacina",
                    "data_hora_inicio": "2026-10-20T10:00:00Z",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Tutor e pet novos",
                summary="Cascata completa",
                value={
                    "tutor": {"nome": "Joana Reis", "telefone": "11 91111-1111"},
                    "pet": {"nome": "Rex", "especie": "Cão", "raca": "Labrador"},
                    "profissional_id": "7a2c1e5f-0b8d-4c3a-9f21-8e6d5b4a3c2d",
                    "tipo_servico": "retorno",
                    "data_hora_inicio": "2026-10-21T14:30:00Z",
                    "queixa": "Retorno pós-cirurgia",
                    "duracao_minutos": 20,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Atendimento criado (201)",
                summary="Resposta com tutor e pet em resumo",
                response_only=True,
                value={
                    "id": "8b1b1e2a-3f4c-4d5e-9a6b-0c1d2e3f4a5b",
                    "pet": {
                        "id": "b51f3f9e-9a5a-4f8f-8c8e-6c1d0a9b2c73",
                        "nome": "Rex",
                        "especie": "Cão",
                        "raca": "Labrador",
                    },
                    "pet_nome": "Rex",
                    "tutor": {
                        "id": "3f1d2c9a-1c7b-4a2e-9a10-5f2b8d7c6e41",
                        "nome": "Joana Reis",
                        "telefone": "11 91111-1111",
                        "cpf": "123.456.789-00",
                    },
                    "tutor_nome": "Joana Reis",
                    "profissional_id": "7a2c1e5f-0b8d-4c3a-9f21-8e6d5b4a3c2d",
                    "profissional": {
                        "id": "7a2c1e5f-0b8d-4c3a-9f21-8e6d5b4a3c2d",
                        "nome": "Dr. Paulo Lima",
                        "cargo": "Veterinário",
                    },
                    "nome_profissional": "Dr. Paulo Lima",
                    "tipo_servico": "retorno",
                    "tipo_servico_display": "Retorno",
                    "queixa": "Retorno pós-cirurgia",
                    "data_hora_inicio": "2026-10-21T14:30:00Z",
                    "duracao_minutos": 20,
                    "status": "agendado",
                    "observacoes": "",
                    "criado_em": "2026-10-15T12:00:00Z",
                    "atualizado_em": "2026-10-15T12:00:00Z",
                },
            ),
        ],
    )
    @action(detail=False, methods=["post"], url_path="rapido")
    def rapido(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        atendimento = serializer.save()
        return Response(
            AtendimentoRapidoResponseSerializer(atendimento).data,
            status=status.HTTP_201_CREATED,
        )

    # @method_decorator(cache_page(60 * 5))  # cache de 5 minutos
    # def list(self, request, *args, **kwargs):
    #         return super().list(request, *args, **kwargs)
