from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Product(models.Model):
    """A supply (detergent, softener, bags). Its stock only changes through movements."""

    class Unit(models.TextChoices):
        BAG = "bag", _("Bag")
        GRAM = "g", _("Gram")
        LITER = "L", _("Liter")
        MILLILITER = "ml", _("Milliliter")
        PIECE = "piece", _("Piece")
        UNIT = "unit", _("Unit")

    name = models.CharField(_("name"), max_length=120)
    sku = models.CharField(_("SKU"), max_length=60, blank=True)
    unit = models.CharField(_("unit"), max_length=10, choices=Unit.choices)
    cost = models.DecimalField(_("cost per unit"), max_digits=10, decimal_places=4, default=0)
    stock = models.DecimalField(_("stock"), max_digits=12, decimal_places=3, default=0)
    min_stock = models.DecimalField(_("minimum stock"), max_digits=12, decimal_places=3, default=0)
    is_for_sale = models.BooleanField(
        _("for sale"),
        default=False,
        help_text=_("Leave unchecked for supplies used in the loads (detergent, softener)."),
    )
    sale_price = models.DecimalField(
        _("sale price"), max_digits=10, decimal_places=2, null=True, blank=True
    )
    branch = models.ForeignKey(
        "core.Branch", verbose_name=_("branch"), on_delete=models.PROTECT, related_name="products"
    )

    class Meta:
        verbose_name = _("product")
        verbose_name_plural = _("products")
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(is_for_sale=False) | Q(sale_price__isnull=False),
                name="product_for_sale_has_price",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Stock and movements are numbers in the product's unit; changing the unit
        # afterwards would silently change their meaning (5000 ml -> 5000 L).
        if not self._state.adding and self.has_movements():
            saved_unit = Product.objects.values_list("unit", flat=True).get(pk=self.pk)
            if saved_unit != self.unit:
                raise ValidationError(
                    {"unit": _("The unit cannot change once the product has stock movements.")}
                )
        super().save(*args, **kwargs)

    def clean(self):
        if self.is_for_sale and self.sale_price is None:
            raise ValidationError({"sale_price": _("A product for sale needs a sale price.")})

    def has_movements(self):
        return self.pk is not None and self.movements.exists()


class LoadConsumption(models.Model):
    """How much of a product each load of a wash service uses."""

    service = models.ForeignKey(
        "sales.Service",
        verbose_name=_("service"),
        on_delete=models.CASCADE,
        related_name="consumptions",
    )
    product = models.ForeignKey(
        Product, verbose_name=_("product"), on_delete=models.PROTECT, related_name="consumptions"
    )
    quantity = models.DecimalField(
        _("quantity per load"),
        max_digits=12,
        decimal_places=3,
        help_text=_("In the product's unit, for example 150 ml."),
    )

    class Meta:
        verbose_name = _("consumption per load")
        verbose_name_plural = _("consumption per load")
        constraints = [
            models.UniqueConstraint(
                fields=["service", "product"], name="unique_consumption_per_service_product"
            ),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="load_consumption_positive"),
        ]

    def __str__(self):
        return f"{self.service}: {self.quantity} {self.product.unit} {self.product}"

    def clean(self):
        # Only washing uses supplies; drying does not.
        if self.service_id and self.service.kind != "wash":
            raise ValidationError({"service": _("Only wash services consume supplies.")})


class StockMovement(models.Model):
    """A change in a product's stock. Never edited or deleted, so it keeps the history.

    ``quantity`` is signed: positive adds stock, negative removes it.
    """

    class Kind(models.TextChoices):
        PURCHASE = "purchase", _("purchase")
        CONSUMPTION = "consumption", _("consumption")
        SALE = "sale", _("sale")
        ADJUSTMENT = "adjustment", _("adjustment")

    product = models.ForeignKey(
        Product, verbose_name=_("product"), on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField(_("kind"), max_length=20, choices=Kind.choices)
    quantity = models.DecimalField(
        _("quantity"),
        max_digits=12,
        decimal_places=3,
        help_text=_(
            "In the product's unit. Purchases are positive; an adjustment is negative "
            "to remove stock."
        ),
    )
    unit_cost = models.DecimalField(
        _("unit cost"), max_digits=10, decimal_places=4, null=True, blank=True
    )
    reason = models.CharField(
        _("reason"),
        max_length=255,
        blank=True,
        help_text=_("Required for adjustments: why the stock changed (spill, count, error)."),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(_("date"), auto_now_add=True)

    class Meta:
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-created_at"]
        permissions = [
            ("receive_stock", _("Can record stock entries")),
            ("adjust_stock", _("Can adjust stock (losses, corrections)")),
        ]
        constraints = [
            # Purchases add stock, consumption and sales remove it, adjustments go either way.
            models.CheckConstraint(
                condition=Q(kind="purchase", quantity__gt=0)
                | Q(kind__in=["consumption", "sale"], quantity__lt=0)
                | (Q(kind="adjustment") & ~Q(quantity=0)),
                name="stock_movement_quantity_sign_matches_kind",
            ),
            models.CheckConstraint(
                condition=~Q(kind="adjustment") | ~Q(reason=""),
                name="stock_adjustment_has_reason",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.product}"

    def clean(self):
        if self.quantity is None or not self.kind:
            return
        if self.kind == self.Kind.PURCHASE and self.quantity <= 0:
            raise ValidationError({"quantity": _("A purchase must add stock (positive).")})
        if self.kind in (self.Kind.CONSUMPTION, self.Kind.SALE) and self.quantity >= 0:
            raise ValidationError({"quantity": _("This kind of movement removes stock.")})
        if self.kind == self.Kind.ADJUSTMENT and self.quantity == 0:
            raise ValidationError({"quantity": _("An adjustment cannot be zero.")})
        if self.kind == self.Kind.ADJUSTMENT and not self.reason.strip():
            raise ValidationError({"reason": _("An adjustment needs a reason.")})
