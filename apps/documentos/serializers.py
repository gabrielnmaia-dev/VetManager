"""Serializers de documentos clínicos."""

from rest_framework import serializers

from apps.base.serializers import AuthoredModelSerializer, usuario_autenticado

from .models import DocumentoClinico
from .services import validar_arquivo


class DocumentoClinicoSerializer(AuthoredModelSerializer):
    """Serializer de leitura/atualização do documento clínico."""

    pet_nome = serializers.CharField(source="pet.nome", read_only=True)
    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    usuario_username = serializers.CharField(
        source="usuario.username", read_only=True
    )

    class Meta:
        model = DocumentoClinico
        fields = [
            "id",
            "pet",
            "pet_nome",
            "prontuario",
            "atendimento",
            "tipo",
            "tipo_display",
            "nome_original",
            "nome_interno",
            "tamanho",
            "mime_type",
            "data_exame",
            "data_envio",
            "descricao",
            "usuario",
            "usuario_username",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [
            "id",
            "nome_original",
            "nome_interno",
            "tamanho",
            "mime_type",
            "data_envio",
            "usuario",
            "criado_em",
            "atualizado_em",
        ]


class DocumentoClinicoCreateSerializer(AuthoredModelSerializer):
    """Serializer para criação de documento clínico com upload de arquivo."""

    arquivo = serializers.FileField(write_only=True)

    class Meta:
        model = DocumentoClinico
        fields = [
            "id",
            "pet",
            "prontuario",
            "atendimento",
            "tipo",
            "arquivo",
            "data_exame",
            "descricao",
        ]
        read_only_fields = ["id"]

    def validate_arquivo(self, arquivo):
        valido, mensagem = validar_arquivo(arquivo)
        if not valido:
            raise serializers.ValidationError(mensagem)
        return arquivo

    def create(self, validated_data):
        arquivo = validated_data.pop("arquivo")
        usuario = usuario_autenticado(self.context)

        instance = DocumentoClinico(**validated_data)
        instance.usuario = usuario
        instance.nome_original = arquivo.name
        instance.salvar_arquivo(arquivo)
        instance.save(user=usuario)
        return instance


# ---------------------------------------------------------------------------
# Documentos veterinários gerados
# ---------------------------------------------------------------------------

from django.utils import timezone
from rest_framework import serializers as drf_serializers

from apps.tutores.models import Tutor

from .models import (
    DocumentoVeterinario,
    ModeloDocumento,
    SituacaoDocumento,
    StatusAssinatura,
    TipoDocumentoVeterinario,
)
from .services import contexto_documento, renderizar_template


class ModeloDocumentoSerializer(AuthoredModelSerializer):
    tipo_display = drf_serializers.CharField(
        source="get_tipo_display", read_only=True
    )

    class Meta:
        model = ModeloDocumento
        fields = [
            "id",
            "tipo",
            "tipo_display",
            "nome",
            "corpo",
            "ativo",
            "versao",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate_corpo(self, value):
        if not (value or "").strip():
            raise drf_serializers.ValidationError("Informe o corpo do modelo.")
        return value


class DocumentoVeterinarioSerializer(AuthoredModelSerializer):
    pet_nome = drf_serializers.CharField(source="pet.nome", read_only=True)
    tutor_nome = drf_serializers.CharField(source="tutor.nome", read_only=True)
    veterinario_nome = drf_serializers.CharField(
        source="veterinario.profissional.nome", read_only=True
    )
    veterinario_crmv = drf_serializers.CharField(
        source="veterinario.crmv", read_only=True
    )
    tipo_display = drf_serializers.CharField(
        source="get_tipo_display", read_only=True
    )
    situacao_display = drf_serializers.CharField(
        source="get_situacao_display", read_only=True
    )
    assinatura_status_display = drf_serializers.CharField(
        source="get_assinatura_status_display", read_only=True
    )
    emitido_por_username = drf_serializers.CharField(
        source="emitido_por.username", read_only=True
    )
    pdf_disponivel = drf_serializers.SerializerMethodField()
    assinatura_aviso = drf_serializers.SerializerMethodField()

    def get_pdf_disponivel(self, obj):
        return bool(obj.pdf_caminho)

    def get_assinatura_aviso(self, obj):
        return (
            "Os campos de assinatura são metadados informativos de um processo "
            "externo. Não representam assinatura digital qualificada nem "
            "atestam validade jurídica."
        )

    class Meta:
        model = DocumentoVeterinario
        fields = [
            "id",
            "tipo",
            "tipo_display",
            "pet",
            "pet_nome",
            "tutor",
            "tutor_nome",
            "prontuario",
            "atendimento",
            "veterinario",
            "veterinario_nome",
            "veterinario_crmv",
            "modelo",
            "titulo",
            "conteudo",
            "identificador",
            "hash_conteudo",
            "situacao",
            "situacao_display",
            "data_emissao",
            "emitido_por",
            "emitido_por_username",
            "pdf_disponivel",
            "pdf_nome_interno",
            "pdf_tamanho",
            "pdf_sha256",
            "versao",
            "documento_anterior",
            "assinatura_status",
            "assinatura_status_display",
            "assinatura_provedor",
            "assinatura_referencia",
            "assinatura_hash",
            "assinado_em",
            "cancelado_em",
            "motivo_cancelamento",
            "assinatura_aviso",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = fields


class DocumentoVeterinarioWriteSerializer(AuthoredModelSerializer):
    """Cria/edita rascunhos. A emissão gera o PDF e congela o conteúdo."""

    tutor = drf_serializers.PrimaryKeyRelatedField(
        queryset=Tutor.objects.all(),
        required=False,
    )
    # O conteúdo pode vir vazio quando um modelo é selecionado; nesse caso é
    # renderizado a partir dos marcadores antes de salvar.
    conteudo = drf_serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = DocumentoVeterinario
        fields = [
            "id",
            "tipo",
            "pet",
            "tutor",
            "prontuario",
            "atendimento",
            "veterinario",
            "modelo",
            "titulo",
            "conteudo",
        ]

    def _resolver_vinculos(self, attrs):
        instance = getattr(self, "instance", None)
        pet = attrs.get("pet") or (instance.pet if instance else None)
        if pet is None:
            raise drf_serializers.ValidationError(
                {"pet": ["Informe o animal."]}
            )

        tutor = attrs.get("tutor")
        if tutor is None:
            tutor = instance.tutor if instance else pet.tutor
        if tutor.pk != pet.tutor_id:
            raise drf_serializers.ValidationError(
                {"tutor": ["O tutor deve ser o tutor atual do animal."]}
            )
        attrs["tutor"] = tutor

        prontuario = attrs.get("prontuario", getattr(instance, "prontuario", None))
        atendimento = attrs.get("atendimento", getattr(instance, "atendimento", None))

        if prontuario is not None and prontuario.pet_id != pet.pk:
            raise drf_serializers.ValidationError(
                {"prontuario": ["O prontuário pertence a outro animal."]}
            )
        if atendimento is not None and atendimento.pet_id != pet.pk:
            raise drf_serializers.ValidationError(
                {"atendimento": ["O atendimento pertence a outro animal."]}
            )
        if (
            prontuario is not None
            and atendimento is not None
            and prontuario.atendimento_id
            and prontuario.atendimento_id != atendimento.pk
        ):
            raise drf_serializers.ValidationError(
                {
                    "atendimento": [
                        "O atendimento não corresponde ao prontuário informado."
                    ]
                }
            )

        veterinario = attrs.get("veterinario", getattr(instance, "veterinario", None))
        if veterinario is None and prontuario is not None:
            veterinario = prontuario.veterinario
            attrs["veterinario"] = veterinario
        if (
            veterinario is not None
            and prontuario is not None
            and prontuario.veterinario_id
            and prontuario.veterinario_id != veterinario.pk
        ):
            raise drf_serializers.ValidationError(
                {
                    "veterinario": [
                        "O profissional deve ser o responsável pelo prontuário."
                    ]
                }
            )

        tipo = attrs.get("tipo") or (instance.tipo if instance else None)
        if (
            tipo != TipoDocumentoVeterinario.DECLARACAO_COMPARECIMENTO
            and veterinario is None
        ):
            raise drf_serializers.ValidationError(
                {
                    "veterinario": [
                        "Informe o profissional responsável pelo documento."
                    ]
                }
            )

        return attrs

    def _resolver_conteudo(self, attrs, instance):
        conteudo = attrs.get("conteudo")
        if conteudo is None and instance is not None:
            conteudo = instance.conteudo
        if not (conteudo or "").strip():
            modelo = attrs.get("modelo", getattr(instance, "modelo", None))
            if modelo is None:
                raise drf_serializers.ValidationError(
                    {"conteudo": ["Informe o conteúdo ou selecione um modelo."]}
                )
            # Monta uma instância temporária para resolver os vínculos.
            temporario = instance or DocumentoVeterinario()
            for campo, valor in attrs.items():
                setattr(temporario, campo, valor)
            conteudo = renderizar_template(
                modelo.corpo, contexto_documento(temporario)
            )
            if not conteudo.strip():
                raise drf_serializers.ValidationError(
                    {"conteudo": ["O modelo selecionado gerou um conteúdo vazio."]}
                )
        attrs["conteudo"] = conteudo
        return attrs

    def validate(self, attrs):
        if self.instance is not None and not self.instance.editavel:
            raise drf_serializers.ValidationError(
                "Documentos emitidos ou cancelados não podem ser alterados. "
                "Crie uma nova versão."
            )
        attrs = self._resolver_vinculos(attrs)
        attrs = self._resolver_conteudo(attrs, self.instance)
        if "titulo" in attrs and not (attrs["titulo"] or "").strip():
            raise drf_serializers.ValidationError(
                {"titulo": ["Informe o título do documento."]}
            )
        return attrs

    def create(self, validated_data):
        from apps.base.serializers import usuario_autenticado

        usuario = usuario_autenticado(self.context)
        instance = DocumentoVeterinario(**validated_data)
        instance.atualizar_hash()
        instance.save(user=usuario)
        return instance

    def update(self, instance, validated_data):
        from apps.base.serializers import usuario_autenticado

        usuario = usuario_autenticado(self.context)
        for campo, valor in validated_data.items():
            setattr(instance, campo, valor)
        instance.atualizar_hash()
        instance.save(user=usuario)
        return instance


class CancelarDocumentoSerializer(drf_serializers.Serializer):
    justificativa = drf_serializers.CharField(
        required=True, allow_blank=False, max_length=2000
    )


class RegistrarAssinaturaSerializer(drf_serializers.Serializer):
    """Metadados de assinatura eletrônica externa.

    Não valida criptograficamente nem confere validade jurídica: apenas
    registra a referência informada pelo profissional/provedor.
    """

    provedor = drf_serializers.CharField(max_length=100)
    referencia = drf_serializers.CharField(max_length=200)
    hash_assinatura = drf_serializers.CharField(
        max_length=64, required=False, allow_blank=True
    )
    assinado_em = drf_serializers.DateTimeField(required=False)
