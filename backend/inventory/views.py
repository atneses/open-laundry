from rest_framework import viewsets

from core.api import HasPermission
from sales.services import create_sale

from .models import Product
from .serializers import ProductSerializer


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """Products for sale in the user's branch. Read only: they are edited in the admin."""

    serializer_class = ProductSerializer
    permission_classes = [HasPermission(*create_sale.required_perms)]

    def get_queryset(self):
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()

        return Product.objects.filter(
            branch_id=self.request.user.branch_id,
            is_for_sale=True,
        ).order_by("name")
