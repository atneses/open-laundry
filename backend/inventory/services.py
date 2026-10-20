from django.db import transaction
from django.db.models import F

from .models import Product, StockMovement


@transaction.atomic
def record_stock_movement(movement: StockMovement) -> StockMovement:
    """Save a new movement and apply its quantity to the product's stock."""
    movement.full_clean()
    movement.save()
    # F() keeps two movements saved at the same time from overwriting each other.
    Product.objects.filter(pk=movement.product_id).update(stock=F("stock") + movement.quantity)
    return movement
