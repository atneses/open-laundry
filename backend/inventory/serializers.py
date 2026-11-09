from decimal import Decimal
from typing import Any

from rest_framework import serializers

from .models import Product, StockMovement


class ProductSerializer(serializers.ModelSerializer):
    """A product for sale, with its stock so the POS can warn before charging."""

    class Meta:
        model = Product
        fields = ["id", "name", "unit", "sale_price", "stock"]
        read_only_fields = fields


class InventoryProductSerializer(serializers.ModelSerializer):
    """Any product of the branch, to pick the one that arrived."""

    class Meta:
        model = Product
        fields = ["id", "name", "unit", "stock", "min_stock"]
        read_only_fields = fields


class StockEntryCreateSerializer(serializers.Serializer):
    """Supplies that arrived; only products of the user's branch."""

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )
    unit_cost = serializers.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal(0),
        required=False,
        allow_null=True,
        default=None,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")

        if request is not None:
            self.fields["product"].queryset = Product.objects.filter(
                branch_id=request.user.branch_id,
            )


class StockEntrySerializer(serializers.ModelSerializer):
    """A stock entry in the history: what arrived, how much, its cost and who recorded it."""

    product_name = serializers.CharField(source="product.name", read_only=True)
    unit = serializers.ChoiceField(
        source="product.unit",
        choices=Product.Unit.choices,
        read_only=True,
    )
    recorded_by = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "product",
            "product_name",
            "unit",
            "quantity",
            "unit_cost",
            "created_at",
            "recorded_by",
        ]
        read_only_fields = fields

    def get_recorded_by(self, movement: StockMovement) -> str | None:
        if movement.created_by is None:
            return None

        return movement.created_by.get_display_name()
