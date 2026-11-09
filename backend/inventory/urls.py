from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register(prefix="products", viewset=views.ProductViewSet, basename="product")
router.register(
    prefix="inventory/products",
    viewset=views.InventoryProductViewSet,
    basename="inventory-product",
)
router.register(
    prefix="inventory/movements",
    viewset=views.StockEntryViewSet,
    basename="stock-entry",
)

urlpatterns = router.urls
