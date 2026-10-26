"""Tests for payments: balance, status and the cash session totals (plan Stage 7.2)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
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

CASH = Payment.Method.CASH
CREDIT_CARD = Payment.Method.CREDIT_CARD
DEBIT_CARD = Payment.Method.DEBIT_CARD


def employee(username, branch):
    """A user with the Employee role, which can charge sales."""

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


def test_a_partial_payment_leaves_the_sale_partially_paid(cashier, sale):
    add_payment(cashier, sale, CASH, "100.00")

    sale.refresh_from_db()
    assert sale.status == Sale.Status.PARTIALLY_PAID
    assert sale.balance == Decimal("35.00")


def test_two_partial_payments_leave_the_sale_paid(cashier, sale):
    add_payment(cashier, sale, CASH, "100.00")

    add_payment(cashier, sale, DEBIT_CARD, "35.00", "VOUCHER-1")

    sale.refresh_from_db()
    assert sale.status == Sale.Status.PAID
    assert sale.balance == 0


def test_payment_is_recorded_in_the_open_cash_session(cashier, sale):
    payment = add_payment(cashier, sale, CREDIT_CARD, "135.00", " VOUCHER-1 ")

    assert payment.cash_session == cashier.cash_sessions.get()
    assert payment.created_by == cashier
    assert payment.reference == "VOUCHER-1"


def test_payment_cannot_be_more_than_the_balance(cashier, sale):
    with pytest.raises(ValidationError) as error:
        add_payment(cashier, sale, CASH, "135.01")

    assert "amount" in error.value.message_dict
    sale.refresh_from_db()
    assert sale.balance == Decimal("135.00")
    assert not Payment.objects.exists()


def test_a_paid_sale_cannot_be_paid_again(cashier, sale):
    add_payment(cashier, sale, CASH, "135.00")

    with pytest.raises(ValidationError):
        add_payment(cashier, sale, CASH, "1.00")

    assert Payment.objects.count() == 1


@pytest.mark.parametrize("amount", ["0", "-10"])
def test_payment_amount_must_be_greater_than_zero(cashier, sale, amount):
    with pytest.raises(ValidationError) as error:
        add_payment(cashier, sale, CASH, amount)

    assert "amount" in error.value.message_dict


def test_payment_method_must_be_valid(cashier, sale):
    with pytest.raises(ValidationError) as error:
        add_payment(cashier, sale, "coins", "10.00")

    assert "method" in error.value.message_dict


def test_cash_payment_records_the_cash_received(cashier, sale):
    payment = add_payment(cashier, sale, CASH, "135.00", received="200.00")

    payment.refresh_from_db()
    assert payment.received == Decimal("200.00")


def test_card_payment_cannot_record_cash_received(cashier, sale):
    with pytest.raises(ValidationError) as error:
        add_payment(cashier, sale, DEBIT_CARD, "135.00", "VOUCHER-1", received="200.00")

    assert "received" in error.value.message_dict
    assert not Payment.objects.exists()


def test_cash_received_cannot_be_less_than_the_amount(cashier, sale):
    with pytest.raises(ValidationError) as error:
        add_payment(cashier, sale, CASH, "135.00", received="100.00")

    assert "received" in error.value.message_dict
    assert not Payment.objects.exists()


def test_a_cancelled_sale_cannot_be_paid(cashier, sale):
    cancel_sale(cashier, sale, "Wrong service")

    with pytest.raises(ValidationError):
        add_payment(cashier, sale, CASH, "10.00")

    assert not Payment.objects.exists()


def test_a_sale_of_another_branch_cannot_be_paid(sale):
    other_branch = Branch.objects.create(name="Norte", sale_prefix="N")
    other = employee("other", other_branch)
    open_cash_session(other, 500)

    with pytest.raises(PermissionDenied):
        add_payment(other, sale, CASH, "10.00")

    assert not Payment.objects.exists()


def test_paying_requires_the_charge_permission(sale, branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        add_payment(user, sale, CASH, "10.00")

    assert not Payment.objects.exists()


def test_paying_requires_an_open_cash_session(cashier, sale):
    close_cash_session(cashier.cash_sessions.get(), cashier, 500)

    with pytest.raises(ValidationError):
        add_payment(cashier, sale, CASH, "10.00")

    assert not Payment.objects.exists()


def test_closing_adds_up_the_cash_and_card_payments(cashier, sale):
    add_payment(cashier, sale, CASH, "60.00")
    add_payment(cashier, sale, CREDIT_CARD, "50.00", "VOUCHER-1")
    add_payment(cashier, sale, DEBIT_CARD, "25.00", "VOUCHER-2")

    session = close_cash_session(cashier.cash_sessions.get(), cashier, "560.00")

    assert session.expected_cash == Decimal("560.00")
    assert session.card_total == Decimal("75.00")
    assert session.sales_count == 1
    assert session.difference == 0


def test_a_balance_paid_on_a_later_shift_counts_in_that_shift(cashier, sale, branch):
    add_payment(cashier, sale, CASH, "100.00")
    close_cash_session(cashier.cash_sessions.get(), cashier, "600.00")
    later = employee("later", branch)
    later_session = open_cash_session(later, 300)
    add_payment(later, sale, CASH, "35.00")

    session = close_cash_session(later_session, later, "335.00")

    assert session.expected_cash == Decimal("335.00")
    assert session.sales_count == 0


def test_admin_role_gets_the_payment_permissions():
    group = Group.objects.get(name=ADMIN_ROLE)

    assert group.permissions.filter(codename="view_payment").exists()


def test_sale_detail_shows_its_payments_in_admin(admin_client, cashier, sale):
    add_payment(cashier, sale, DEBIT_CARD, "135.00", "VOUCHER-1")

    response = admin_client.get(reverse("admin:sales_sale_change", args=[sale.pk]))

    assert "VOUCHER-1" in response.content.decode()
