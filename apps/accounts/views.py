from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .throttles import LoginRateThrottle, TokenRefreshRateThrottle


class VetTokenObtainPairView(TokenObtainPairView):
    """Login JWT com rate limit por IP (escopo "login")."""

    throttle_classes = [LoginRateThrottle]


class VetTokenRefreshView(TokenRefreshView):
    """Refresh JWT com rate limit por IP (escopo "token_refresh")."""

    throttle_classes = [TokenRefreshRateThrottle]
