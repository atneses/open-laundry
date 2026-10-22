"""Tests for the requires_perm decorator of the services."""

import pytest
from django.core.exceptions import PermissionDenied

from core.permissions import requires_perm

pytestmark = pytest.mark.django_db

CHARGE = "sales.charge"
CANCEL_SALE = "sales.cancel_sale"


@requires_perm(CHARGE, message="You cannot charge sales.")
def charge(user, amount):
    return amount


@requires_perm(CHARGE, CANCEL_SALE)
def charge_and_cancel(user):
    return "done"


def test_runs_the_service_when_the_user_has_the_permission(staff_with_perms):
    user = staff_with_perms(CHARGE)

    result = charge(user, 10)

    assert result == 10


def test_rejects_with_the_given_message_without_the_permission(staff_with_perms):
    user = staff_with_perms()

    with pytest.raises(PermissionDenied) as error:
        charge(user, 10)

    assert str(error.value) == "You cannot charge sales."


def test_requires_every_permission(staff_with_perms):
    user = staff_with_perms(CHARGE)

    with pytest.raises(PermissionDenied):
        charge_and_cancel(user)


def test_runs_when_the_user_has_every_permission(staff_with_perms):
    user = staff_with_perms(CHARGE, CANCEL_SALE)

    result = charge_and_cancel(user)

    assert result == "done"


def test_lists_the_required_permissions():
    assert charge_and_cancel.required_perms == (CHARGE, CANCEL_SALE)
