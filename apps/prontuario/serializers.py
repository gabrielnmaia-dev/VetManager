from django.utils import timezone
from rest_framework import serializers

from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from .models import Prontuario, Vacina


class VacinaSerializer(AuthoredModelSerializer):
    """Vacina com dados de aplicação e situação calculada.

    Os campos de situação nunca são aceitos na escrita: são derivados da data
    de retorno e do dia atual.
    """

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    veterinario_nome = serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    veterinario_crmv = serializers.CharField(
        source="veterinario.crmv", read_only=True
    )
    via_aplicacao_display = serializers.CharField(
        source="get_via_aplicacao_display", read_only=True
    )
    situacao = serializers.CharField(read_only=True)
    situacao_display = serializers.SerializerMethodField()
    dias_para_retorno = serializers.IntegerField(read_only=True)

    def get_situacao_display(self, obj):
        return obj.Situacao(obj.situacao).label

    def validate(self, attrs):
        instance = self.instance
        pet = attrs.get("pet") or (instance.pet if instance else None)
        data_aplicacao = attrs.get("data_aplicacao") or (
            instance.data_aplicacao if instance else None
        )
        if "data_retorno" in attrs:
            data_retorno = attrs["data_retorno"]
        else:
            data_retorno = instance.data_retorno if instance else None
        if "veterinario" in attrs:
            veterinario = attrs["veterinario"]
        else:
            veterinario = instance.veterinario if instance else None
        if "prontuario" in attrs:
            prontuario = attrs["prontuario"]
        else:
            prontuario = instance.prontuario if instance else None

        erros = {}
        if data_aplicacao and data_aplicacao > timezone.localdate():
            erros["data_aplicacao"] = [
                "A data de aplicação não pode ser futura."
            ]
        if data_retorno and data_aplicacao and data_retorno < data_aplicacao:
            erros["data_retorno"] = [
                "A data de retorno não pode ser anterior à aplicação."
            ]
        if (
            veterinario is not None
            and veterinario.profissional.cargo != "Veterinário"
        ):
            erros["veterinario"] = [
                "Somente profissionais com cargo 'Veterinário' podem "
                "responder pela aplicação."
            ]
        if prontuario is not None and pet is not None and prontuario.pet_id != pet.id:
            erros["prontuario"] = [
                "O prontuário selecionado pertence a outro animal."
            ]
        if erros:
            raise serializers.ValidationError(erros)
        return attrs

    class Meta:
        model = Vacina
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor_nome",
            "prontuario",
            "veterinario",
            "veterinario_nome",
            "veterinario_crmv",
            "nome_vacina",
            "data_aplicacao",
            "data_retorno",
            "lote",
            "fabricante",
            "via_aplicacao",
            "via_aplicacao_display",
            "dose",
            "observacoes",
            "situacao",
            "situacao_display",
            "dias_para_retorno",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "criado_em",
            "atualizado_em",
            "situacao",
            "situacao_display",
            "dias_para_retorno",
        ]


class ProntuarioSerializer(AuthoredModelSerializer):
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    veterinario_nome = serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    vacinas = VacinaSerializer(many=True, read_only=True)

    def validate_veterinario(self, valor):
        """O veterinário do prontuário deve ser um Profissional com cargo
        'Veterinário', não qualquer profissional (tosador, banhista, etc.)."""
        if valor is not None and valor.profissional.cargo != "Veterinário":
            raise serializers.ValidationError(
                "Somente profissionais com cargo 'Veterinário' podem assinar prontuários."
            )
        return valor

    class Meta:
        model = Prontuario
        fields = [
            "id",
            "atendimento",
            "pet",
            "pet_nome",
            "veterinario",
            "veterinario_nome",
            "data_consulta",
            "data_nascimento",
            "idade",
            "peso",
            "temperatura",
            "diagnostico",
            "observacoes",
            "prescricao",
            "retorno_recomendado",
            "vacinas",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]