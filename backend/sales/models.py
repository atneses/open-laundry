from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.validators import validate_name


class Mode(models.TextChoices):
    """How a service is sold: the customer does it or the laundry does it."""

    SELF_SERVICE = "self_service", _("Self-service")
    DROP_OFF = "drop_off", _("Drop-off")


class Service(models.Model):
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
        _("machine kind"), max_length=10, choices=MachineKind.choices, default=MachineKind.NONE
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


class ServicePrice(models.Model):
    """Price of a service for one mode. Prices are never edited, so they keep the history.

    The last price added is the active one: saving a new price deactivates the previous
    one. An existing price can only be deactivated.
    """

    service = models.ForeignKey(
        Service, verbose_name=_("service"), on_delete=models.CASCADE, related_name="prices"
    )
    mode = models.CharField(_("mode"), max_length=20, choices=Mode.choices)
    program = models.CharField(
        _("program"),
        max_length=60,
        blank=True,
        help_text=_("Leave empty for the general price. Reserved for prices per program."),
    )
    price = models.DecimalField(
        _("price"), max_digits=10, decimal_places=2, validators=[MinValueValidator(0)]
    )
    branch = models.ForeignKey(
        "core.Branch",
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        related_name="service_prices",
    )
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(_("date"), auto_now_add=True)

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
            return super().save(*args, **kwargs)
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
