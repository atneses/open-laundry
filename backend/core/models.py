from django.contrib.auth.models import AbstractUser
from django.db import models


class Branch(models.Model):
    """A laundry location. There is only one today, but most data hangs from it."""

    name = models.CharField("nombre", max_length=120)
    address = models.CharField("dirección", max_length=255, blank=True)
    phone = models.CharField("teléfono", max_length=20, blank=True)

    class Meta:
        verbose_name = "sucursal"
        verbose_name_plural = "sucursales"

    def __str__(self):
        return self.name


class User(AbstractUser):
    """System user (admin or employee).

    Defined from the very first migration because Django does not allow swapping
    the user model easily afterwards. Roles and permissions arrive in Stage 2.
    """

    branch = models.ForeignKey(
        Branch,
        verbose_name="sucursal",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
