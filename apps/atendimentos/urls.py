from rest_framework.routers import DefaultRouter
from .views import AtendimentoViewSet
 
router = DefaultRouter()
router.register("atendimentos", AtendimentoViewSet, basename="atendimento")
 
urlpatterns = router.urls