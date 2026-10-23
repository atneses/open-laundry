from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from core.validators import validate_code, validate_name


class Machine(BaseModel):
    """A washer or dryer of a branch, such as "Lavadora 3"."""

    class Kind(models.TextChoices):
        WASHER = "washer", _("Washer")
        DRYER = "dryer", _("Dryer")

    class Status(models.TextChoices):
        AVAILABLE = "available", _("Available")
        OUT_OF_SERVICE = "out_of_service", _("Out of service")

    branch = models.ForeignKey(
        "core.Branch",
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        related_name="machines",
    )
    kind = models.CharField(_("kind"), max_length=10, choices=Kind.choices)
    label = models.CharField(
        _("label"),
        max_length=60,
        validators=[validate_name],
        help_text=_('The name shown at the POS, for example "Lavadora 3".'),
    )
    model = models.CharField(_("model"), max_length=60, blank=True, validators=[validate_code])
    serial_number = models.CharField(
        _("serial number"),
        max_length=60,
        blank=True,
        validators=[validate_code],
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )

    class Meta:
        verbose_name = _("machine")
        verbose_name_plural = _("machines")
        ordering = ["label"]
        permissions = [("manage_machines", _("Can add and configure machines"))]
        constraints = [
            models.UniqueConstraint(fields=["branch", "label"], name="unique_machine_label"),
        ]

    def __str__(self):
        return self.label


class MachineCycle(BaseModel):
    """One use of a machine: each load sold of a service that uses a machine."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        REQUESTED = "requested", _("Requested")
        CREDIT_SENT = "credit_sent", _("Credit sent")
        RUNNING = "running", _("Running")
        FINISHED = "finished", _("Finished")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    sale_item = models.ForeignKey(
        "sales.SaleItem",
        verbose_name=_("sale item"),
        on_delete=models.PROTECT,
        related_name="cycles",
    )
    machine = models.ForeignKey(
        Machine,
        verbose_name=_("machine"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cycles",
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    customer_supplies = models.BooleanField(
        _("customer supplies"),
        default=False,
        help_text=_("The customer brought their own detergent and softener."),
    )
    is_manual = models.BooleanField(
        _("manual"),
        default=False,
        help_text=_("Started with the Start button (PUSH mode), without the relay box."),
    )
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("started by"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="started_cycles",
    )
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    class Meta:
        verbose_name = _("machine cycle")
        verbose_name_plural = _("machine cycles")
        ordering = ["-created_at"]
        permissions = [("start_machine", _("Can start machines and record cycles"))]
        constraints = [
            # Once a cycle leaves pending, it has a machine and whoever started it.
            models.CheckConstraint(
                condition=Q(status__in=["pending", "cancelled"])
                | Q(machine__isnull=False, started_by__isnull=False),
                name="started_cycle_has_machine",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["running", "finished"]) | Q(started_at__isnull=False),
                name="running_cycle_has_started_at",
            ),
            models.CheckConstraint(
                condition=~Q(status="finished") | Q(finished_at__isnull=False),
                name="finished_cycle_has_finished_at",
            ),
        ]

    def __str__(self):
        return _("Cycle %(pk)s") % {"pk": self.pk}
