from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register(prefix="machines", viewset=views.MachineViewSet, basename="machine")
router.register(
    prefix="machine-cycles",
    viewset=views.MachineCycleViewSet,
    basename="machine-cycle",
)

urlpatterns = router.urls
