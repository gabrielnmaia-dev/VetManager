"""Serializers da internação veterinária.

Operações clínicas (admissão, transferência, evolução, cuidado, medicação e
alta) delegam aos serviços transacionais: o serializer apenas valida o
payload e converte a resposta.
"""

from rest_framework import serializers

from apps.atendimentos.models import Atendimento
from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado
from apps.documentos.models import DocumentoClinico
from apps.estoque.models import Lote, Produto
from apps.pets.models import Pet
from apps.prescricao.models import ItemPrescricao, Prescricao
from apps.prontuario.models import Prontuario
from apps.veterinarios.models import Profissional

from . import services
from .models import (
    AdministracaoMedicamentoInternacao,
    CuidadoInternacao,
    EvolucaoInternacao,
    Internacao,
    Leito,
    OcupacaoLeito,
)

CAMPOS_IMUTAVEIS_ATUALIZACAO = {
    "pet",
    "atendimento_origem",
    "prontuario",
    "leito",
    "profissional_responsavel",
    "motivo_internacao",
    "data_hora_entrada",
    "status",
    "chave_idempotencia",
}


class LeitoSerializer(AuthoredModelSerializer):
    """Leito com ocupação calculada a partir das ocupações abertas."""

    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    situacao_display = serializers.CharField(
        source="get_situacao_display", read_only=True
    )
    ocupados = serializers.SerializerMethodField()
    disponivel = serializers.SerializerMethodField()
    situacao_operacional = serializers.SerializerMethodField()
    ocupacao_atual = serializers.SerializerMethodField()

    class Meta:
        model = Leito
        fields = [
            "id",
            "nome",
            "tipo",
            "tipo_display",
            "capacidade",
            "situacao",
            "situacao_display",
            "observacoes",
            "ocupados",
            "disponivel",
            "situacao_operacional",
            "ocupacao_atual",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tipo_display",
            "situacao_display",
            "ocupados",
            "disponivel",
            "situacao_operacional",
            "ocupacao_atual",
            "created_at",
            "updated_at",
        ]

    def _ocupados(self, obj) -> int:
        if hasattr(obj, "ocupados_count"):
            return obj.ocupados_count
        return obj.ocupados

    def get_ocupados(self, obj):
        return self._ocupados(obj)

    def get_disponivel(self, obj):
        return (
            obj.situacao == Leito.Situacao.ATIVO
            and self._ocupados(obj) < max(obj.capacidade or 1, 1)
        )

    def get_situacao_operacional(self, obj):
        if obj.situacao == Leito.Situacao.INATIVO:
            return "inativo"
        if obj.situacao == Leito.Situacao.MANUTENCAO:
            return "manutencao"
        if self._ocupados(obj) >= max(obj.capacidade or 1, 1):
            return "lotado"
        return "disponivel"

    def get_ocupacao_atual(self, obj):
        ocupacoes = getattr(obj, "ocupacoes_abertas_list", None)
        if ocupacoes is None:
            ocupacoes = list(
                obj.ocupacoes.filter(data_saida__isnull=True, is_deleted=False)
                .select_related("internacao__pet", "internacao__profissional_responsavel")
                .order_by("-data_entrada")[:1]
            )
        else:
            ocupacoes = list(ocupacoes)
        if not ocupacoes:
            return None
        ocupacao = ocupacoes[0]
        internacao = ocupacao.internacao
        return {
            "id": str(ocupacao.id),
            "internacao": str(internacao.id),
            "pet": str(internacao.pet_id),
            "pet_nome": internacao.pet.nome,
            "profissional": str(internacao.profissional_responsavel_id),
            "profissional_nome": internacao.profissional_responsavel.nome,
            "data_entrada": ocupacao.data_entrada,
        }

    def validate_capacidade(self, valor):
        if valor is None or valor < 1:
            raise serializers.ValidationError(
                "A capacidade do leito deve ser de pelo menos 1."
            )
        return valor


class OcupacaoLeitoSerializer(serializers.ModelSerializer):
    """Histórico de ocupação, somente leitura."""

    leito_nome = serializers.CharField(source="leito.nome", read_only=True)
    leito_tipo = serializers.CharField(source="leito.tipo", read_only=True)
    pet = serializers.UUIDField(source="internacao.pet_id", read_only=True)
    pet_nome = serializers.CharField(source="internacao.pet.nome", read_only=True)
    tutor_nome = serializers.CharField(
        source="internacao.pet.tutor.nome", read_only=True
    )
    ativa = serializers.BooleanField(read_only=True)

    class Meta:
        model = OcupacaoLeito
        fields = [
            "id",
            "internacao",
            "leito",
            "leito_nome",
            "leito_tipo",
            "pet",
            "pet_nome",
            "tutor_nome",
            "data_entrada",
            "data_saida",
            "motivo_saida",
            "ativa",
            "created_at",
        ]
        read_only_fields = fields


class EvolucaoInternacaoSerializer(AuthoredModelSerializer):
    """Evolução clínica imutável; a criação passa pelo serviço."""

    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    profissional_crmv = serializers.CharField(
        source="profissional.crmv", read_only=True
    )
    pet_nome = serializers.CharField(
        source="internacao.pet.nome", read_only=True
    )

    class Meta:
        model = EvolucaoInternacao
        fields = [
            "id",
            "internacao",
            "pet_nome",
            "profissional",
            "profissional_nome",
            "profissional_crmv",
            "data_hora",
            "evolucao_clinica",
            "observacoes",
            "intercorrencias",
            "peso",
            "temperatura",
            "frequencia_cardiaca",
            "frequencia_respiratoria",
            "pressao_arterial",
            "saturacao",
            "glicemia",
            "escore_corporal",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "pet_nome",
            "profissional_nome",
            "profissional_crmv",
            "created_at",
            "created_by",
        ]

    def validate_saturacao(self, valor):
        if valor is not None and not 0 <= valor <= 100:
            raise serializers.ValidationError(
                "A saturação deve estar entre 0 e 100."
            )
        return valor

    def create(self, validated_data):
        return services.registrar_evolucao(
            usuario=usuario_autenticado(self.context), **validated_data
        )


class CuidadoInternacaoSerializer(AuthoredModelSerializer):
    """Registro de cuidado/rotina de enfermagem."""

    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    pet_nome = serializers.CharField(
        source="internacao.pet.nome", read_only=True
    )

    class Meta:
        model = CuidadoInternacao
        fields = [
            "id",
            "internacao",
            "pet_nome",
            "tipo",
            "tipo_display",
            "descricao",
            "profissional",
            "profissional_nome",
            "data_hora",
            "observacoes",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "pet_nome",
            "tipo_display",
            "profissional_nome",
            "created_at",
            "created_by",
        ]

    def create(self, validated_data):
        return services.registrar_cuidado(
            usuario=usuario_autenticado(self.context), **validated_data
        )


class AdministracaoMedicamentoInternacaoSerializer(
    AuthoredModelSerializer
):
    """Medicação administrada, com baixa/estorno de estoque rastreáveis."""

    item_prescricao = serializers.PrimaryKeyRelatedField(
        queryset=ItemPrescricao.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    produto = serializers.PrimaryKeyRelatedField(
        queryset=Produto.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    lote = serializers.PrimaryKeyRelatedField(
        queryset=Lote.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    profissional = serializers.PrimaryKeyRelatedField(
        queryset=Profissional.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    chave_idempotencia = serializers.CharField(
        max_length=100, required=False, allow_blank=True, write_only=True
    )

    prescricao = serializers.PrimaryKeyRelatedField(read_only=True)
    pet = serializers.PrimaryKeyRelatedField(read_only=True)
    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_codigo = serializers.CharField(
        source="produto.codigo_interno", read_only=True
    )
    unidade_dispensacao = serializers.CharField(
        source="produto.unidade_dispensacao", read_only=True
    )
    lote_numero = serializers.CharField(source="lote.numero_lote", read_only=True)
    lote_validade = serializers.DateField(
        source="lote.data_validade", read_only=True
    )
    profissional_nome = serializers.CharField(
        source="profissional.nome", read_only=True
    )
    via_display = serializers.CharField(source="get_via_display", read_only=True)
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    cancelada_por_username = serializers.SerializerMethodField()
    movimentacao_dados = serializers.SerializerMethodField()
    estorno_dados = serializers.SerializerMethodField()

    class Meta:
        model = AdministracaoMedicamentoInternacao
        fields = [
            "id",
            "internacao",
            "pet",
            "pet_nome",
            "item_prescricao",
            "prescricao",
            "produto",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
            "lote",
            "lote_numero",
            "lote_validade",
            "profissional",
            "profissional_nome",
            "quantidade",
            "dose",
            "via",
            "via_display",
            "data_hora",
            "observacoes",
            "status",
            "status_display",
            "movimentacao",
            "movimentacao_dados",
            "estorno_movimentacao",
            "estorno_dados",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "cancelada_por_username",
            "chave_idempotencia",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "pet",
            "pet_nome",
            "prescricao",
            "produto_nome",
            "produto_codigo",
            "unidade_dispensacao",
            "lote_numero",
            "lote_validade",
            "profissional_nome",
            "via_display",
            "status",
            "status_display",
            "movimentacao",
            "movimentacao_dados",
            "estorno_movimentacao",
            "estorno_dados",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "cancelada_por_username",
            "created_at",
            "updated_at",
        ]

    def get_cancelada_por_username(self, obj):
        return obj.cancelada_por.username if obj.cancelada_por else ""

    def _dados_movimentacao(self, movimentacao):
        if movimentacao is None:
            return None
        return {
            "id": str(movimentacao.id),
            "tipo": movimentacao.tipo,
            "tipo_display": movimentacao.get_tipo_display(),
            "quantidade": str(movimentacao.quantidade),
            "saldo_anterior": str(movimentacao.saldo_anterior),
            "saldo_posterior": str(movimentacao.saldo_posterior),
            "motivo": movimentacao.motivo,
            "data_hora": movimentacao.data_hora,
        }

    def get_movimentacao_dados(self, obj):
        return self._dados_movimentacao(obj.movimentacao)

    def get_estorno_dados(self, obj):
        return self._dados_movimentacao(obj.estorno_movimentacao)

    def validate_quantidade(self, valor):
        if valor is None or valor <= 0:
            raise serializers.ValidationError(
                "Informe uma quantidade maior que zero."
            )
        return valor

    def create(self, validated_data):
        administracao, criada = services.registrar_administracao(
            usuario=usuario_autenticado(self.context), **validated_data
        )
        administracao.criada_agora = criada
        return administracao


class InternacaoSerializer(AuthoredModelSerializer):
    """Admissão com dados de ocupação e resumo do episódio."""

    pet = serializers.PrimaryKeyRelatedField(
        queryset=Pet.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    atendimento_origem = serializers.PrimaryKeyRelatedField(
        queryset=Atendimento.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    leito = serializers.PrimaryKeyRelatedField(
        queryset=Leito.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    profissional_responsavel = serializers.PrimaryKeyRelatedField(
        queryset=Profissional.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    prontuario = serializers.PrimaryKeyRelatedField(
        queryset=Prontuario.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )
    chave_idempotencia = serializers.CharField(
        max_length=100, required=False, allow_blank=True, write_only=True
    )
    prescricoes = serializers.PrimaryKeyRelatedField(
        many=True, read_only=True
    )
    documentos = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    tutor_telefone = serializers.CharField(
        source="pet.tutor.telefone", read_only=True
    )
    leito_nome = serializers.CharField(source="leito.nome", read_only=True)
    leito_tipo = serializers.CharField(source="leito.tipo", read_only=True)
    leito_tipo_display = serializers.CharField(
        source="leito.get_tipo_display", read_only=True
    )
    profissional_nome = serializers.CharField(
        source="profissional_responsavel.nome", read_only=True
    )
    profissional_crmv = serializers.CharField(
        source="profissional_responsavel.crmv", read_only=True
    )
    profissional_alta_nome = serializers.CharField(
        source="profissional_alta.nome", read_only=True
    )
    estado_clinico_display = serializers.CharField(
        source="get_estado_clinico_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    ativa = serializers.BooleanField(read_only=True)
    dias_internado = serializers.SerializerMethodField()
    evolucoes_count = serializers.SerializerMethodField()
    cuidados_count = serializers.SerializerMethodField()
    administracoes_count = serializers.SerializerMethodField()
    ultima_evolucao = serializers.SerializerMethodField()

    class Meta:
        model = Internacao
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor_nome",
            "tutor_telefone",
            "atendimento_origem",
            "prontuario",
            "leito",
            "leito_nome",
            "leito_tipo",
            "leito_tipo_display",
            "profissional_responsavel",
            "profissional_nome",
            "profissional_crmv",
            "motivo_internacao",
            "data_hora_entrada",
            "diagnostico_inicial",
            "estado_clinico",
            "estado_clinico_display",
            "observacoes",
            "status",
            "status_display",
            "ativa",
            "data_hora_alta",
            "profissional_alta",
            "profissional_alta_nome",
            "condicao_alta",
            "orientacoes_tutor",
            "resumo_internacao",
            "prescricoes",
            "documentos",
            "dias_internado",
            "evolucoes_count",
            "cuidados_count",
            "administracoes_count",
            "ultima_evolucao",
            "chave_idempotencia",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "pet_nome",
            "tutor_nome",
            "tutor_telefone",
            "leito_nome",
            "leito_tipo",
            "leito_tipo_display",
            "profissional_nome",
            "profissional_crmv",
            "estado_clinico_display",
            "status",
            "status_display",
            "ativa",
            "data_hora_alta",
            "profissional_alta",
            "profissional_alta_nome",
            "condicao_alta",
            "orientacoes_tutor",
            "resumo_internacao",
            "prescricoes",
            "documentos",
            "dias_internado",
            "evolucoes_count",
            "cuidados_count",
            "administracoes_count",
            "ultima_evolucao",
            "created_at",
            "updated_at",
        ]

    def _count(self, obj, attr: str) -> int:
        valor = getattr(obj, f"{attr}_count", None)
        if valor is not None:
            return valor
        return getattr(obj, attr).count()

    def get_dias_internado(self, obj):
        from django.utils import timezone

        fim = obj.data_hora_alta or timezone.now()
        return max((fim - obj.data_hora_entrada).days, 0)

    def get_evolucoes_count(self, obj):
        return self._count(obj, "evolucoes")

    def get_cuidados_count(self, obj):
        return self._count(obj, "cuidados")

    def get_administracoes_count(self, obj):
        return self._count(obj, "administracoes")

    def get_ultima_evolucao(self, obj):
        if hasattr(obj, "ultima_evolucao_anotada"):
            return obj.ultima_evolucao_anotada
        evoluções = getattr(obj, "ultimas_evolucoes", None)
        if evoluções is not None:
            return evoluções[0].data_hora if evoluções else None
        ultima = obj.evolucoes.order_by("-data_hora").first()
        return ultima.data_hora if ultima else None

    def validate(self, attrs):
        if self.instance is None:
            if (
                not attrs.get("pet")
                and not attrs.get("atendimento_origem")
                and not attrs.get("prontuario")
            ):
                raise serializers.ValidationError(
                    {"pet": ["Informe o animal ou vincule um atendimento/prontuário."]}
                )
            if not attrs.get("leito"):
                raise serializers.ValidationError(
                    {"leito": ["Informe o leito da internação."]}
                )
            if not attrs.get("profissional_responsavel"):
                raise serializers.ValidationError(
                    {
                        "profissional_responsavel": [
                            "Informe o profissional responsável."
                        ]
                    }
                )
            if not (attrs.get("motivo_internacao") or "").strip():
                raise serializers.ValidationError(
                    {"motivo_internacao": ["Informe o motivo da internação."]}
                )
            return attrs

        alterados = CAMPOS_IMUTAVEIS_ATUALIZACAO.intersection(attrs)
        if alterados:
            raise serializers.ValidationError(
                {
                    campo: [
                        "Este campo não pode ser alterado diretamente; use a "
                        "transferência ou a alta."
                    ]
                    for campo in sorted(alterados)
                }
            )
        return attrs

    def create(self, validated_data):
        internacao, criada = services.admitir_paciente(
            usuario=usuario_autenticado(self.context), **validated_data
        )
        internacao.criada_agora = criada
        return internacao


class InternacaoResumoSerializer(serializers.ModelSerializer):
    """Versão enxuta para listas e para a central de internação."""

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = serializers.CharField(source="pet.tutor.nome", read_only=True)
    leito_nome = serializers.CharField(source="leito.nome", read_only=True)
    profissional_nome = serializers.CharField(
        source="profissional_responsavel.nome", read_only=True
    )
    estado_clinico_display = serializers.CharField(
        source="get_estado_clinico_display", read_only=True
    )

    class Meta:
        model = Internacao
        fields = [
            "id",
            "pet",
            "pet_nome",
            "tutor_nome",
            "leito",
            "leito_nome",
            "profissional_responsavel",
            "profissional_nome",
            "data_hora_entrada",
            "estado_clinico",
            "estado_clinico_display",
            "status",
            "data_hora_alta",
        ]


class PrescricaoPendenteSerializer(serializers.ModelSerializer):
    """Prescrição ativa de paciente internado, com itens e saldo pendente."""

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    veterinario_nome = serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    itens = serializers.SerializerMethodField()

    class Meta:
        model = Prescricao
        fields = [
            "id",
            "pet",
            "pet_nome",
            "veterinario_nome",
            "data_prescricao",
            "itens",
        ]

    def get_itens(self, obj):
        administracoes = getattr(obj, "administracoes_periodo", None)
        if administracoes is None:
            administracoes = obj.administracoes_internacao.all()
        totais = {}
        for administracao in administracoes:
            if (
                administracao.status
                != AdministracaoMedicamentoInternacao.Status.ATIVA
            ):
                continue
            chave = administracao.item_prescricao_id
            totais[chave] = totais.get(chave, 0) + (
                administracao.quantidade or 0
            )
        itens = []
        for item in obj.itens.all():
            administrado = totais.get(item.id, 0)
            pendente = (item.quantidade_prescrita or 0) - administrado
            itens.append(
                {
                    "id": str(item.id),
                    "produto": str(item.produto_id),
                    "produto_nome": item.produto.nome,
                    "produto_codigo": item.produto.codigo_interno,
                    "unidade_dispensacao": item.produto.unidade_dispensacao,
                    "dose": item.dose,
                    "via": item.via,
                    "via_display": item.get_via_display(),
                    "frequencia": item.frequencia,
                    "duracao": item.duracao,
                    "quantidade_prescrita": str(item.quantidade_prescrita or 0),
                    "quantidade_administrada": str(administrado),
                    "quantidade_pendente": str(max(pendente, 0)),
                }
            )
        return itens


class TransferenciaInternacaoSerializer(serializers.Serializer):
    """Payload da transferência de leito."""

    novo_leito = serializers.PrimaryKeyRelatedField(
        queryset=Leito.objects.filter(is_deleted=False)
    )
    motivo = serializers.CharField(
        required=False, allow_blank=True, max_length=120
    )
    data_hora = serializers.DateTimeField(required=False, allow_null=True)


class AltaInternacaoSerializer(serializers.Serializer):
    """Payload da alta, com prescrições e documentos do mesmo animal."""

    profissional_alta = serializers.PrimaryKeyRelatedField(
        queryset=Profissional.objects.filter(is_deleted=False)
    )
    data_hora_alta = serializers.DateTimeField(required=False, allow_null=True)
    condicao_alta = serializers.CharField(required=False, allow_blank=True)
    orientacoes_tutor = serializers.CharField(required=False, allow_blank=True)
    resumo_internacao = serializers.CharField(required=False, allow_blank=True)
    prescricoes = serializers.PrimaryKeyRelatedField(
        queryset=Prescricao.objects.filter(is_deleted=False),
        many=True,
        required=False,
    )
    documentos = serializers.PrimaryKeyRelatedField(
        queryset=DocumentoClinico.objects.filter(is_deleted=False),
        many=True,
        required=False,
    )
