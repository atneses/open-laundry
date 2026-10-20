from core.forms import InputFilterModelForm

from .models import LoadConsumption, Product, StockMovement


class ProductForm(InputFilterModelForm):
    input_filters = {
        "name": "name",
        "sku": "code",
        "cost": "decimal",
        "min_stock": "decimal",
        "sale_price": "decimal",
    }

    class Meta:
        model = Product
        fields = [
            "name",
            "sku",
            "unit",
            "cost",
            "min_stock",
            "is_for_sale",
            "sale_price",
            "branch",
        ]


class LoadConsumptionForm(InputFilterModelForm):
    input_filters = {"quantity": "decimal"}

    class Meta:
        model = LoadConsumption
        fields = ["service", "product", "quantity"]


class StockMovementForm(InputFilterModelForm):
    # Adjustments remove stock with a negative quantity.
    input_filters = {"quantity": "signed-decimal", "unit_cost": "decimal"}

    class Meta:
        model = StockMovement
        fields = ["product", "kind", "quantity", "unit_cost", "reason"]
