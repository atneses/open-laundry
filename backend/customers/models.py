import re

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel
from core.validators import validate_person_name, validate_phone


class Customer(BaseModel):
    """A laundry customer, found at the counter by phone number."""

    branch = models.ForeignKey(
        "core.Branch",
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        related_name="customers",
    )
    name = models.CharField(_("name"), max_length=120, validators=[validate_person_name])
    phone = models.CharField(
        _("phone"),
        max_length=20,
        help_text=_("Digits only."),
        validators=[validate_phone],
    )
    email = models.EmailField(_("email"), blank=True)
    address = models.CharField(_("address"), max_length=255, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("customer")
        verbose_name_plural = _("customers")
        ordering = ["name"]
        permissions = [
            ("manage_customers", _("Can register customers and manage drop-off orders")),
        ]
        constraints = [
            models.UniqueConstraint(fields=["branch", "phone"], name="unique_phone_per_branch"),
            models.CheckConstraint(
                condition=Q(phone__regex=r"^[0-9]+$"),
                name="customer_phone_digits_only",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})"

    def save(self, *args, **kwargs):
        # "55 1234-5678" and "5512345678" are the same phone; keep one format so the
        # unique constraint catches duplicates.
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    def clean(self):
        self.phone = normalize_phone(self.phone)


def normalize_phone(phone: str) -> str:
    """Keep only the digits of a phone number."""

    return re.sub(r"\D", "", phone or "")
