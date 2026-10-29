from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class VetTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Inclui username e grupos (perfis) no token e na resposta do login."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["username"] = user.get_username()
        token["groups"] = list(user.groups.values_list("name", flat=True))
        token["is_staff"] = user.is_staff
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = {
            "id": self.user.pk,
            "username": self.user.get_username(),
            "groups": list(self.user.groups.values_list("name", flat=True)),
            "is_staff": self.user.is_staff,
        }
        return data


class PerfilSerializer(serializers.ModelSerializer):
    """Dados do próprio usuário logado (GET/PUT/PATCH /api/v1/perfil/).

    Somente nome, sobrenome e e-mail são editáveis. `username`, grupos e
    permissões são somente leitura: quem administra isso é o /admin.
    """

    groups = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="name"
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "groups",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]
        read_only_fields = [
            "id",
            "username",
            "groups",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
        ]


class AlterarSenhaSerializer(serializers.Serializer):
    """Troca de senha do próprio usuário (exige a senha atual).

    A nova senha passa pelos mesmos validadores do Django configurados em
    AUTH_PASSWORD_VALIDATORS (tamanho mínimo, senha comum, etc.).
    """

    senha_atual = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
        error_messages={
            "required": "Informe a senha atual.",
            "blank": "Informe a senha atual.",
        },
    )
    nova_senha = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
        error_messages={
            "required": "Informe a nova senha.",
            "blank": "Informe a nova senha.",
        },
    )
    confirmar_nova_senha = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        style={"input_type": "password"},
        error_messages={
            "required": "Confirme a nova senha.",
            "blank": "Confirme a nova senha.",
        },
    )

    def validate_senha_atual(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Senha atual incorreta.")
        return value

    def validate_nova_senha(self, value):
        user = self.context["request"].user
        try:
            password_validation.validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        if attrs["nova_senha"] == attrs["senha_atual"]:
            raise serializers.ValidationError(
                {"nova_senha": "A nova senha deve ser diferente da senha atual."}
            )
        if attrs["nova_senha"] != attrs["confirmar_nova_senha"]:
            raise serializers.ValidationError(
                {"confirmar_nova_senha": "As senhas não coincidem."}
            )
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["nova_senha"])
        user.save(update_fields=["password"])
        return user


class AlterarSenhaResponseSerializer(serializers.Serializer):
    """Resposta da troca de senha: mensagem + par de tokens novo."""

    detail = serializers.CharField()
    access = serializers.CharField()
    refresh = serializers.CharField()
