from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register(prefix="cash-sessions", viewset=views.CashSessionViewSet, basename="cash-session")
router.register(prefix="services", viewset=views.ServiceViewSet, basename="service")
router.register(prefix="sales", viewset=views.SaleViewSet, basename="sale")
router.register(prefix="discounts", viewset=views.DiscountViewSet, basename="discount")
router.register(
    prefix="drop-off-orders",
    viewset=views.DropOffOrderViewSet,
    basename="drop-off-order",
)

urlpatterns = router.urls
