from django.contrib.auth.models import AbstractUser, Permission
from django.db import models
from django.utils.translation import gettext_lazy as _

from .validators import validate_name, validate_person_name, validate_phone


class Branch(models.Model):
    """A laundry location. There is only one today, but most data hangs from it."""

    name = models.CharField(_("name"), max_length=120, validators=[validate_name])
    address = models.CharField(_("address"), max_length=255, blank=True)
    phone = models.CharField(_("phone"), max_length=20, blank=True, validators=[validate_phone])

    class Meta:
        verbose_name = _("branch")
        verbose_name_plural = _("branches")

    def __str__(self):
        return self.name


class User(AbstractUser):
    """System user (admin or employee).

    Defined from the very first migration because Django does not allow swapping
    the user model easily afterwards. The role is the user's group (see core.roles).
    """

    branch = models.ForeignKey(
        Branch,
        verbose_name=_("branch"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    # Redefined only to add the validator; same as AbstractUser otherwise.
    first_name = models.CharField(
        _("first name"), max_length=150, blank=True, validators=[validate_person_name]
    )
    last_name = models.CharField(
        _("last name"), max_length=150, blank=True, validators=[validate_person_name]
    )

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        permissions = [
            ("manage_users", _("Can manage users, roles and permissions")),
        ]


class PermissionLog(models.Model):
    """Audit trail of extra permissions granted to or revoked from a user."""

    class Action(models.TextChoices):
        GRANTED = "granted", _("Granted")
        REVOKED = "revoked", _("Revoked")

    user = models.ForeignKey(
        User,
        verbose_name=_("user"),
        on_delete=models.PROTECT,
        related_name="permission_logs",
    )
    permission = models.ForeignKey(
        Permission,
        verbose_name=_("permission"),
        on_delete=models.PROTECT,
        related_name="+",
    )
    action = models.CharField(_("action"), max_length=10, choices=Action.choices)
    performed_by = models.ForeignKey(
        User,
        verbose_name=_("performed by"),
        on_delete=models.PROTECT,
        null=True,
        related_name="+",
    )
    created_at = models.DateTimeField(_("date"), auto_now_add=True)

    class Meta:
        verbose_name = _("permission log entry")
        verbose_name_plural = _("permission log")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} {self.permission.codename} → {self.user}"
