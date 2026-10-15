from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


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
