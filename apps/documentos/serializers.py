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
