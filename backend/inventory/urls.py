from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("products", views.ProductViewSet, basename="product")

urlpatterns = router.urls
