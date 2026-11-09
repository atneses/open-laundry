from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from core.permissions import requires_perm

from .models import Product, StockMovement

if TYPE_CHECKING:
    from decimal import Decimal

    from core.models import User

RECEIVE_STOCK = "inventory.receive_stock"


@transaction.atomic
def record_stock_movement(movement: StockMovement) -> StockMovement:
    """Save a new movement and apply its quantity to the product's stock."""

    movement.full_clean()
    movement.save()

    # F() keeps two movements saved at the same time from overwriting each other.
    Product.objects.filter(pk=movement.product_id).update(stock=F("stock") + movement.quantity)

    return movement


@requires_perm(RECEIVE_STOCK, message=_("You cannot record stock entries."))
@transaction.atomic
def receive_stock(
    user: User,
    product: Product,
    quantity: Decimal,
    unit_cost: Decimal | None = None,
) -> StockMovement:
    """Record supplies that arrived: a purchase that adds ``quantity`` to the stock.

    ``quantity`` is in the product's unit. ``unit_cost`` is optional because whoever
    receives the goods may not know their price.
    """

    if product.branch_id != user.branch_id:
        raise PermissionDenied(_("The product belongs to another branch."))

    return record_stock_movement(
        movement=StockMovement(
            product=product,
            kind=StockMovement.Kind.PURCHASE,
            quantity=quantity,
            unit_cost=unit_cost,
            created_by=user,
        ),
    )
