from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Mode(models.TextChoices):
    """How a service is sold: the customer does it or the laundry does it."""

    SELF_SERVICE = "self_service", _("self-service")
    DROP_OFF = "drop_off", _("drop-off")


class Service(models.Model):
    """Something the laundry sells, such as "Wash per load" or "Sneaker wash"."""

    class Kind(models.TextChoices):
        WASH = "wash", _("wash")
        DRY = "dry", _("dry")
        OTHER = "other", _("other")

    class Unit(models.TextChoices):
        LOAD = "load", _("load")
        PIECE = "piece", _("piece")
        PAIR = "pair", _("pair")

    class MachineKind(models.TextChoices):
        WASHER = "washer", _("washer")
        DRYER = "dryer", _("dryer")
        NONE = "none", _("none")

    name = models.CharField(_("name"), max_length=120)
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
    """Price of a service for one mode, valid from a date on."""

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
    price = models.DecimalField(_("price"), max_digits=10, decimal_places=2)
    valid_from = models.DateField(_("valid from"), default=timezone.localdate)
    branch = models.ForeignKey(
        "core.Branch",
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        related_name="service_prices",
    )

    class Meta:
        verbose_name = _("service price")
        verbose_name_plural = _("service prices")
        ordering = ["service", "mode", "-valid_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "mode", "program", "branch", "valid_from"],
                name="unique_service_price_per_day",
            ),
            models.CheckConstraint(condition=Q(price__gte=0), name="service_price_not_negative"),
        ]

    def __str__(self):
        return f"{self.service} · {self.get_mode_display()}: {self.price}"
