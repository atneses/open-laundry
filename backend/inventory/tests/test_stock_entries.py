"""Tests for recording stock entries with the receive_stock service (plan Stage 12.8)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from inventory.models import Product, StockMovement
from inventory.services import receive_stock

pytestmark = pytest.mark.django_db


@pytest.fixture
def employee(branch):
    """A user with the Employee role, which can record stock entries."""

    user = get_user_model().objects.create_user(username="employee", branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


@pytest.fixture
def detergent(branch):
    return Product.objects.create(branch=branch, name="Detergent", unit="ml", stock=1000)


def test_receiving_stock_adds_a_purchase_to_the_stock(employee, detergent):
    movement = receive_stock(user=employee, product=detergent, quantity=Decimal(5000))

    detergent.refresh_from_db()
    assert detergent.stock == Decimal(6000)
    assert (movement.kind, movement.unit_cost, movement.created_by) == (
        StockMovement.Kind.PURCHASE,
        None,
        employee,
    )


def test_receiving_stock_keeps_the_unit_cost(employee, detergent):
    movement = receive_stock(
        user=employee,
        product=detergent,
        quantity=Decimal(5000),
        unit_cost=Decimal("0.05"),
    )

    assert movement.unit_cost == Decimal("0.05")


def test_receiving_stock_requires_receive_stock(branch, detergent):
    user = get_user_model().objects.create_user(username="noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        receive_stock(user=user, product=detergent, quantity=Decimal(5000))


def test_a_product_of_another_branch_cannot_be_received(detergent):
    other = get_user_model().objects.create_user(
        username="other",
        branch=Branch.objects.create(name="Norte", sale_prefix="N"),
    )
    other.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    with pytest.raises(PermissionDenied):
        receive_stock(user=other, product=detergent, quantity=Decimal(5000))


def test_receiving_zero_is_rejected(employee, detergent):
    with pytest.raises(ValidationError):
        receive_stock(user=employee, product=detergent, quantity=Decimal(0))

    detergent.refresh_from_db()
    assert detergent.stock == Decimal(1000)
