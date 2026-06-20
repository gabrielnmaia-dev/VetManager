from rest_framework.routers import DefaultRouter

from .viewsets import TutorViewSet

router = DefaultRouter()

router.register(
    r"tutores",
    TutorViewSet,
    basename="tutor"
)

urlpatterns = router.urls