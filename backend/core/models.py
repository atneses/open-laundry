from django.conf import settings
from django.contrib.auth.models import AbstractUser, Permission
from django.db import models
from django.utils.translation import gettext_lazy as _

from .middleware import get_current_user
from .validators import validate_code, validate_name, validate_person_name, validate_phone


class BaseModel(models.Model):
    """Base for every model: when and by whom each record was created and last changed.

    The user comes from the current request (core.middleware.CurrentUserMiddleware);
    outside a request (console, seed, migrations) it stays as given. ``bulk_create``
    and ``QuerySet.update`` skip ``save``, so they must set these fields themselves.
    """

    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("updated by"),
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        user = get_current_user()

        if user is not None:
            if self._state.adding and self.created_by_id is None:
                self.created_by = user

            self.updated_by = user

        if self._state.adding and self.updated_by_id is None:
            self.updated_by_id = self.created_by_id

        super().save(*args, **kwargs)


class Branch(BaseModel):
    """A laundry location. There is only one today, but most data hangs from it."""

    name = models.CharField(_("name"), max_length=120, validators=[validate_name])
    address = models.CharField(_("address"), max_length=255, blank=True)
    phone = models.CharField(_("phone"), max_length=20, blank=True, validators=[validate_phone])
    sale_prefix = models.CharField(
        _("sale number prefix"),
        max_length=5,
        default="A",
        validators=[validate_code],
        help_text=_("Starts every sale number of the branch, e.g. A-000123."),
    )
    # Last sale number given; only changed by sales.services.next_sale_number.
    last_sale_number = models.PositiveIntegerField(
        _("last sale number"), default=0, editable=False
    )

    class Meta:
        verbose_name = _("branch")
        verbose_name_plural = _("branches")

    def __str__(self):
        return self.name


class User(AbstractUser, BaseModel):
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

    def __str__(self):
        return self.get_username()


class PermissionLog(BaseModel):
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

    class Meta:
        verbose_name = _("permission log entry")
        verbose_name_plural = _("permission log")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} {self.permission.codename} → {self.user}"
