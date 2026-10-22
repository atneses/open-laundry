from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from core.validators import validate_name


class Mode(models.TextChoices):
    """How a service is sold: the customer does it or the laundry does it."""

    SELF_SERVICE = "self_service", _("Self-service")
    DROP_OFF = "drop_off", _("Drop-off")


class Service(BaseModel):
    """Something the laundry sells, such as "Wash per load" or "Sneaker wash"."""

    class Kind(models.TextChoices):
        WASH = "wash", _("Wash")
        DRY = "dry", _("Dry")
        OTHER = "other", _("Other")

    class Unit(models.TextChoices):
        LOAD = "load", _("Load")
        PIECE = "piece", _("Piece")
        PAIR = "pair", _("Pair")

    class MachineKind(models.TextChoices):
        WASHER = "washer", _("Washer")
        DRYER = "dryer", _("Dryer")
        NONE = "none", _("None")

    name = models.CharField(_("name"), max_length=120, validators=[validate_name])
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices)
    unit = models.CharField(_("unit"), max_length=10, choices=Unit.choices, default=Unit.LOAD)
    machine_kind = models.CharField(
        _("machine kind"),
        max_length=10,
        choices=MachineKind.choices,
        default=MachineKind.NONE,
    )
    uses_machine = models.BooleanField(
        _("uses a machine"),
        default=False,
        help_text=_("Each unit sold starts a machine cycle."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("service")
        verbose_name_plural = _("services")
        ordering = ["name"]
        permissions = [
            (
                "manage_catalog",
                _("Can manage services, prices, products and consumption per load"),
            ),
        ]
        constraints = [
            # A service uses a machine exactly when it says which kind of machine.
            models.CheckConstraint(
                condition=Q(uses_machine=True, machine_kind__in=["washer", "dryer"])
                | Q(uses_machine=False, machine_kind="none"),
                name="service_uses_machine_matches_machine_kind",
            ),
        ]

    def __str__(self):
        return self.name


class ServicePrice(BaseModel):
    """Price of a service for one mode. Prices are never edited, so they keep the history.

    The last price added is the active one: saving a new price deactivates the previous
    one. An existing price can only be deactivated.
    """

    service = models.ForeignKey(
        Service,
        verbose_name=_("service"),
        on_delete=models.CASCADE,
        related_name="prices",
    )
    mode = models.CharField(_("mode"), max_length=20, choices=Mode.choices)
    program = models.CharField(
        _("program"),
        max_length=60,
        blank=True,
        help_text=_("Leave empty for the general price. Reserved for prices per program."),
    )
    price = models.DecimalField(
        _("price"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    branch = models.ForeignKey(
        "core.Branch",
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        related_name="service_prices",
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("service price")
        verbose_name_plural = _("service prices")
        ordering = ["service", "mode", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "mode", "program", "branch"],
                condition=Q(is_active=True),
                name="one_active_price_per_service_mode",
            ),
            models.CheckConstraint(condition=Q(price__gte=0), name="service_price_not_negative"),
        ]

    def __str__(self):
        return f"{self.get_mode_display()}: {self.price}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            self._check_only_deactivated()
            super().save(*args, **kwargs)
            return

        with transaction.atomic():
            ServicePrice.objects.filter(
                service=self.service_id,
                mode=self.mode,
                program=self.program,
                branch=self.branch_id,
                is_active=True,
            ).update(is_active=False)
            self.is_active = True
            super().save(*args, **kwargs)

    def _check_only_deactivated(self):
        """Reject any change to a saved price other than deactivating it."""

        original = ServicePrice.objects.get(pk=self.pk)

        # to_python compares "45.00" and Decimal("45.00") as equal.
        fields = [
            self._meta.get_field(name)
            for name in ("service", "mode", "program", "price", "branch")
        ]
        edited = any(
            f.to_python(f.value_from_object(original)) != f.to_python(f.value_from_object(self))
            for f in fields
        )
        reactivated = self.is_active and not original.is_active

        if edited or reactivated:
            raise ValidationError(_("A price cannot be edited; add a new price instead."))


class CashSession(BaseModel):
    """A cash register shift: opened with a float and closed with the cash count.

    Only one session can be open per branch. The totals are filled when it closes.
    """

    branch = models.ForeignKey(
        "core.Branch",
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        related_name="cash_sessions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        on_delete=models.PROTECT,
        related_name="cash_sessions",
    )
    opened_at = models.DateTimeField(_("opened at"), auto_now_add=True)
    closed_at = models.DateTimeField(_("closed at"), null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("closed by"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="closed_cash_sessions",
        help_text=_("Who closed it; another user when a forgotten session is closed."),
    )
    opening_float = models.DecimalField(
        _("opening float"),
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    expected_cash = models.DecimalField(
        _("expected cash"),
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    counted_cash = models.DecimalField(
        _("counted cash"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    difference = models.DecimalField(
        _("difference"),
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Counted minus expected: negative is missing cash, positive is extra."),
    )
    card_total = models.DecimalField(_("card total"), max_digits=10, decimal_places=2, default=0)
    sales_count = models.PositiveIntegerField(_("sales"), default=0)
    cancellations_count = models.PositiveIntegerField(_("cancellations"), default=0)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("cash session")
        verbose_name_plural = _("cash sessions")
        ordering = ["-opened_at"]
        permissions = [
            ("operate_cash_session", _("Can open and close their own cash session")),
            ("view_all_cash_sessions", _("Can view the cash sessions of every shift")),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["branch"],
                condition=Q(closed_at__isnull=True),
                name="one_open_cash_session_per_branch",
            ),
            models.CheckConstraint(
                condition=Q(opening_float__gte=0),
                name="cash_session_float_not_negative",
            ),
            # A cash count that does not match must be explained.
            models.CheckConstraint(
                condition=Q(difference__isnull=True) | Q(difference=0) | ~Q(notes=""),
                name="cash_session_difference_has_notes",
            ),
        ]

    def __str__(self):
        return f"{self.user} · {self.opened_at:%Y-%m-%d %H:%M}"


class Sale(BaseModel):
    """A sale charged at the counter. ``created_by`` is the cashier who charged it.

    Sales are never deleted; they are cancelled (Stage 7.5).
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PARTIALLY_PAID = "partially_paid", _("Partially paid")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")

    number = models.CharField(_("number"), max_length=20)
    branch = models.ForeignKey(
        "core.Branch",
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        related_name="sales",
    )
    cash_session = models.ForeignKey(
        CashSession,
        verbose_name=_("cash session"),
        on_delete=models.PROTECT,
        related_name="sales",
    )
    customer = models.ForeignKey(
        "customers.Customer",
        verbose_name=_("customer"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
    )
    mode = models.CharField(_("mode"), max_length=20, choices=Mode.choices)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    subtotal = models.DecimalField(_("subtotal"), max_digits=10, decimal_places=2)
    discount_total = models.DecimalField(_("discount"), max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(_("total"), max_digits=10, decimal_places=2)
    balance = models.DecimalField(_("balance"), max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = _("sale")
        verbose_name_plural = _("sales")
        ordering = ["-created_at"]
        permissions = [
            ("charge", _("Can charge sales and print receipts")),
        ]
        constraints = [
            models.UniqueConstraint(fields=["branch", "number"], name="unique_sale_number"),
            models.CheckConstraint(
                condition=~Q(mode="drop_off") | Q(customer__isnull=False),
                name="drop_off_sale_has_customer",
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0, discount_total__gte=0, total__gte=0, balance__gte=0),
                name="sale_amounts_not_negative",
            ),
        ]

    def __str__(self):
        return self.number


class SaleItem(BaseModel):
    """A line of a sale: a service or a product, with the price it was charged at."""

    sale = models.ForeignKey(
        Sale,
        verbose_name=_("sale"),
        on_delete=models.PROTECT,
        related_name="items",
    )
    service = models.ForeignKey(
        Service,
        verbose_name=_("service"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_items",
    )
    product = models.ForeignKey(
        "inventory.Product",
        verbose_name=_("product"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_items",
    )
    quantity = models.DecimalField(_("quantity"), max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(
        _("unit price"),
        max_digits=10,
        decimal_places=2,
        help_text=_("Copied from the catalog when charging; later price changes do not alter it."),
    )
    amount = models.DecimalField(_("amount"), max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = _("sale item")
        verbose_name_plural = _("sale items")
        constraints = [
            # A line is either a service or a product.
            models.CheckConstraint(
                condition=Q(service__isnull=False, product__isnull=True)
                | Q(service__isnull=True, product__isnull=False),
                name="sale_item_service_or_product",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="sale_item_quantity_positive",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.service or self.product}"


class Payment(BaseModel):
    """A payment towards a sale; a sale can have several (an advance and the rest).

    ``cash_session`` is the session open when it was received, which may differ from the
    sale's when a drop-off pays its balance on a later shift. Payments are never deleted.
    """

    class Method(models.TextChoices):
        CASH = "cash", _("Cash")
        CREDIT_CARD = "credit_card", _("Credit card")
        DEBIT_CARD = "debit_card", _("Debit card")

    sale = models.ForeignKey(
        Sale,
        verbose_name=_("sale"),
        on_delete=models.PROTECT,
        related_name="payments",
    )
    cash_session = models.ForeignKey(
        CashSession,
        verbose_name=_("cash session"),
        on_delete=models.PROTECT,
        related_name="payments",
    )
    method = models.CharField(_("method"), max_length=20, choices=Method.choices)
    amount = models.DecimalField(_("amount"), max_digits=10, decimal_places=2)
    reference = models.CharField(
        _("reference"),
        max_length=100,
        blank=True,
        help_text=_("Card voucher reference."),
    )

    class Meta:
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.get_method_display()} {self.amount}"
