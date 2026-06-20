from rest_framework.routers import DefaultRouter
from .views import TutorViewSet
 
router = DefaultRouter()
router.register("tutores", TutorViewSet, basename="tutor")
 
urlpatterns = router.urls