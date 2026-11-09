from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from core.api import IDEMPOTENCY_KEY, HasPermission, run_once
from sales.services import create_sale

from .models import Product, StockMovement
from .serializers import (
    InventoryProductSerializer,
    ProductSerializer,
    StockEntryCreateSerializer,
    StockEntrySerializer,
)
from .services import receive_stock

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from rest_framework.request import Request


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


class InventoryProductViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Every product of the user's branch, also supplies not for sale, to record entries."""

    serializer_class = InventoryProductSerializer
    permission_classes = [HasPermission(*receive_stock.required_perms)]

    def get_queryset(self) -> QuerySet[Product]:
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()

        return Product.objects.filter(branch_id=self.request.user.branch_id).order_by("name")


class StockEntryViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Stock entries of the user's branch: record supplies that arrived and see the history.

    Consumption, sales and adjustments are seen in the admin.
    """

    serializer_class = StockEntrySerializer
    permission_classes = [HasPermission(*receive_stock.required_perms)]

    def get_queryset(self) -> QuerySet[StockMovement]:
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return StockMovement.objects.none()

        return (
            StockMovement.objects.filter(
                product__branch_id=self.request.user.branch_id,
                kind=StockMovement.Kind.PURCHASE,
            )
            .select_related("product", "created_by")
            .order_by("-created_at", "-pk")
        )

    @extend_schema(
        request=StockEntryCreateSerializer,
        responses={201: StockEntrySerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def create(self, request: Request) -> Response:
        """Record supplies that arrived; a retry with the same Idempotency-Key repeats nothing."""

        data = StockEntryCreateSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        data.is_valid(raise_exception=True)
        movement = run_once(
            request=request,
            previous_results=StockMovement.objects.filter(
                product__branch_id=request.user.branch_id,
            ),
            create=lambda: receive_stock(
                user=request.user,
                product=data.validated_data["product"],
                quantity=data.validated_data["quantity"],
                unit_cost=data.validated_data["unit_cost"],
            ),
        )
        movement = self.get_queryset().get(pk=movement.pk)

        return Response(StockEntrySerializer(movement).data, status=status.HTTP_201_CREATED)
