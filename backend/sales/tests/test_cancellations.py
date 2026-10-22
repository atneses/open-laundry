"""Tests for cancelling sales: reason, stock and the cash session totals (plan Stage 7.5)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from inventory.models import Product, StockMovement
from sales.models import Mode, Payment, Sale, Service, ServicePrice
from sales.services import (
    ItemRequest,
    add_payment,
    cancel_sale,
    close_cash_session,
    create_sale,
    open_cash_session,
)

pytestmark = pytest.mark.django_db

REASON = "Charged the wrong service"


def employee(username, branch):
    """A user with the Employee role, which can charge and cancel sales."""

    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


@pytest.fixture
def cashier(branch):
    user = employee("cashier", branch)
    open_cash_session(user, 500)

    return user


@pytest.fixture
def sale(cashier, branch):
    """A self-service sale of 3 washes: $135.00, unpaid."""

    wash = Service.objects.create(
        name="Wash per load",
        kind="wash",
        machine_kind="washer",
        uses_machine=True,
    )
    ServicePrice.objects.create(service=wash, mode=Mode.SELF_SERVICE, price=45, branch=branch)

    return create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(3, service=wash)])


@pytest.fixture
def bag(branch):
    return Product.objects.create(
        branch=branch,
        name="Bag",
        unit="piece",
        is_for_sale=True,
        sale_price=5,
        stock=10,
    )


def test_cancelling_records_who_when_where_and_why(cashier, sale):
    cancelled = cancel_sale(cashier, sale, f"  {REASON}  ")

    assert cancelled.status == Sale.Status.CANCELLED
    assert cancelled.cancelled_by == cashier
    assert cancelled.cancelled_at is not None
    assert cancelled.cancel_cash_session == cashier.cash_sessions.get()
    assert cancelled.cancel_reason == REASON


@pytest.mark.parametrize("reason", ["", "   "])
def test_cancelling_requires_a_reason(cashier, sale, reason):
    with pytest.raises(ValidationError) as error:
        cancel_sale(cashier, sale, reason)

    assert "cancel_reason" in error.value.message_dict
    sale.refresh_from_db()
    assert sale.status == Sale.Status.PENDING


def test_cancelling_requires_the_cancel_sale_permission(sale, branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        cancel_sale(user, sale, REASON)

    sale.refresh_from_db()
    assert sale.status == Sale.Status.PENDING


def test_cancelling_requires_an_open_cash_session(cashier, sale):
    close_cash_session(cashier.cash_sessions.get(), cashier, 500)

    with pytest.raises(ValidationError):
        cancel_sale(cashier, sale, REASON)

    sale.refresh_from_db()
    assert sale.status == Sale.Status.PENDING


def test_a_sale_cannot_be_cancelled_twice(cashier, sale):
    cancel_sale(cashier, sale, REASON)

    with pytest.raises(ValidationError):
        cancel_sale(cashier, sale, "Again")

    sale.refresh_from_db()
    assert sale.cancel_reason == REASON


def test_a_sale_of_another_branch_cannot_be_cancelled(sale):
    other = employee("other", Branch.objects.create(name="Norte", sale_prefix="N"))
    open_cash_session(other, 500)

    with pytest.raises(ValidationError):
        cancel_sale(other, sale, REASON)

    sale.refresh_from_db()
    assert sale.status == Sale.Status.PENDING


def test_cancelled_products_go_back_to_stock(cashier, bag):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, product=bag)])

    cancel_sale(cashier, sale, REASON)

    bag.refresh_from_db()
    assert bag.stock == 10
    movement = StockMovement.objects.get(kind=StockMovement.Kind.SALE_CANCELLATION)
    assert (movement.quantity, movement.sale, movement.created_by) == (2, sale, cashier)


def test_closing_subtracts_the_cash_of_a_sale_cancelled_in_the_session(cashier, sale):
    add_payment(cashier, sale, Payment.Method.CASH, "135.00")
    cancel_sale(cashier, sale, REASON)

    session = close_cash_session(cashier.cash_sessions.get(), cashier, "500.00")

    assert session.expected_cash == Decimal("500.00")
    assert session.sales_count == 0
    assert session.cancellations_count == 1


def test_closing_subtracts_the_card_payments_of_a_cancelled_sale(cashier, sale):
    add_payment(cashier, sale, Payment.Method.DEBIT_CARD, "135.00")
    cancel_sale(cashier, sale, REASON)

    session = close_cash_session(cashier.cash_sessions.get(), cashier, "500.00")

    assert session.card_total == 0


def test_a_sale_cancelled_on_a_later_shift_gives_the_cash_back_there(cashier, sale, branch):
    add_payment(cashier, sale, Payment.Method.CASH, "135.00")
    first = close_cash_session(cashier.cash_sessions.get(), cashier, "635.00")
    later = employee("later", branch)
    later_session = open_cash_session(later, 300)
    cancel_sale(later, sale, REASON)

    session = close_cash_session(later_session, later, "165.00")

    assert session.expected_cash == Decimal("165.00")
    assert session.cancellations_count == 1
    first.refresh_from_db()
    assert first.expected_cash == Decimal("635.00")


@pytest.mark.parametrize("role", [ADMIN_ROLE, EMPLOYEE_ROLE])
def test_roles_get_the_cancel_sale_permission(role):
    group = Group.objects.get(name=role)

    assert group.permissions.filter(codename="cancel_sale").exists()


def test_sale_detail_shows_the_cancellation_in_admin(admin_client, cashier, sale):
    cancel_sale(cashier, sale, REASON)

    response = admin_client.get(reverse("admin:sales_sale_change", args=[sale.pk]))

    assert REASON in response.content.decode()
