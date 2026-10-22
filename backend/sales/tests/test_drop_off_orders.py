"""Tests for drop-off orders: reception, statuses and delivery (plan Stage 8)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from customers.models import Customer
from sales.models import DropOffOrder, Mode, Payment, Sale, Service, ServicePrice
from sales.services import (
    DropOffRequest,
    ItemRequest,
    add_payment,
    advance_drop_off_order,
    cancel_sale,
    create_sale,
    deliver_drop_off_order,
    open_cash_session,
)

pytestmark = pytest.mark.django_db

RECEIVED = DropOffOrder.Status.RECEIVED
IN_PROGRESS = DropOffOrder.Status.IN_PROGRESS
READY = DropOffOrder.Status.READY
DELIVERED = DropOffOrder.Status.DELIVERED


def employee(username, branch):
    """A user with the Employee role: charges sales and manages drop-off orders."""

    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def tomorrow():
    return timezone.now() + timedelta(days=1)


def set_status(order, status):
    """Put the order in a status directly; a delivered one also gets when and who."""

    fields = {"status": status}

    if status == DELIVERED:
        fields |= {"delivered_at": timezone.now(), "delivered_by": order.sale.created_by}

    DropOffOrder.objects.filter(pk=order.pk).update(**fields)
    order.refresh_from_db()


@pytest.fixture
def cashier(branch):
    user = employee("cashier", branch)
    open_cash_session(user, 500)

    return user


@pytest.fixture
def wash(branch):
    service = Service.objects.create(
        name="Wash per load",
        kind="wash",
        machine_kind="washer",
        uses_machine=True,
    )
    ServicePrice.objects.create(service=service, mode=Mode.DROP_OFF, price=60, branch=branch)
    ServicePrice.objects.create(service=service, mode=Mode.SELF_SERVICE, price=45, branch=branch)

    return service


@pytest.fixture
def customer(branch):
    return Customer.objects.create(branch=branch, name="Ana", phone="5512345678")


@pytest.fixture
def sale(cashier, wash, customer):
    """A drop-off sale of 2 washes: $120.00, unpaid."""

    items = [ItemRequest(2, service=wash)]

    return create_sale(cashier, Mode.DROP_OFF, items, customer, DropOffRequest(tomorrow()))


@pytest.fixture
def order(sale):
    return sale.drop_off_order


def test_a_drop_off_sale_receives_its_order(cashier, wash, customer):
    promised_at = tomorrow()
    drop_off = DropOffRequest(promised_at, "  Delicate  ")

    sale = create_sale(cashier, Mode.DROP_OFF, [ItemRequest(2, service=wash)], customer, drop_off)

    order = sale.drop_off_order
    assert order.status == RECEIVED
    assert order.promised_at == promised_at
    assert order.notes == "Delicate"
    assert order.created_by == cashier


def test_a_self_service_sale_has_no_order(cashier, wash):
    create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])

    assert not DropOffOrder.objects.exists()


def test_a_drop_off_sale_needs_a_promised_date(cashier, wash, customer):
    with pytest.raises(ValidationError) as error:
        create_sale(cashier, Mode.DROP_OFF, [ItemRequest(1, service=wash)], customer)

    assert "promised_at" in error.value.message_dict
    assert not Sale.objects.exists()


def test_the_promised_date_cannot_be_in_the_past(cashier, wash, customer):
    drop_off = DropOffRequest(timezone.now() - timedelta(hours=1))

    with pytest.raises(ValidationError) as error:
        create_sale(cashier, Mode.DROP_OFF, [ItemRequest(1, service=wash)], customer, drop_off)

    assert "promised_at" in error.value.message_dict


@pytest.mark.parametrize(("current", "expected"), [(RECEIVED, IN_PROGRESS), (IN_PROGRESS, READY)])
def test_an_order_moves_to_its_next_status(cashier, order, current, expected):
    set_status(order, current)

    advanced = advance_drop_off_order(cashier, order)

    assert advanced.status == expected
    assert advanced.updated_by == cashier


@pytest.mark.parametrize("status", [READY, DELIVERED])
def test_a_ready_or_delivered_order_does_not_move_forward(cashier, order, status):
    set_status(order, status)

    with pytest.raises(ValidationError):
        advance_drop_off_order(cashier, order)


def test_moving_an_order_requires_manage_customers(order, branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        advance_drop_off_order(user, order)

    order.refresh_from_db()
    assert order.status == RECEIVED


def test_an_order_of_another_branch_cannot_be_moved(order):
    other = employee("other", Branch.objects.create(name="Norte", sale_prefix="N"))

    with pytest.raises(PermissionDenied):
        advance_drop_off_order(other, order)


def test_the_order_of_a_cancelled_sale_does_not_change(cashier, sale, order):
    cancel_sale(cashier, sale, "Customer changed their mind")

    with pytest.raises(ValidationError):
        advance_drop_off_order(cashier, order)

    order.refresh_from_db()
    assert order.status == RECEIVED


def test_a_paid_ready_order_is_delivered(cashier, sale, order):
    add_payment(cashier, sale, Payment.Method.CASH, "120.00")
    set_status(order, READY)

    delivered = deliver_drop_off_order(cashier, order)

    assert delivered.status == DELIVERED
    assert delivered.delivered_by == cashier
    assert delivered.delivered_at is not None


@pytest.mark.parametrize("status", [RECEIVED, IN_PROGRESS, DELIVERED])
def test_only_a_ready_order_is_delivered(cashier, sale, order, status):
    add_payment(cashier, sale, Payment.Method.CASH, "120.00")
    set_status(order, status)

    with pytest.raises(ValidationError):
        deliver_drop_off_order(cashier, order)


def test_an_order_with_balance_needs_deliver_with_balance(cashier, sale, order):
    add_payment(cashier, sale, Payment.Method.CASH, "50.00")
    set_status(order, READY)

    with pytest.raises(PermissionDenied):
        deliver_drop_off_order(cashier, order)

    order.refresh_from_db()
    assert order.status == READY


def test_deliver_with_balance_allows_delivering_with_balance(cashier, order):
    cashier.user_permissions.add(Permission.objects.get(codename="deliver_with_balance"))
    user = get_user_model().objects.get(pk=cashier.pk)
    set_status(order, READY)

    delivered = deliver_drop_off_order(user, order)

    assert delivered.status == DELIVERED
    assert delivered.sale.balance == Decimal("120.00")


def test_a_delivered_order_cannot_be_cancelled(cashier, sale, order):
    add_payment(cashier, sale, Payment.Method.CASH, "120.00")
    set_status(order, READY)
    deliver_drop_off_order(cashier, order)

    with pytest.raises(ValidationError):
        cancel_sale(cashier, sale, "Too late")

    sale.refresh_from_db()
    assert sale.status == Sale.Status.PAID


def test_a_full_drop_off_order_from_reception_to_delivery(cashier, wash, customer):
    items = [ItemRequest(2, service=wash)]
    sale = create_sale(cashier, Mode.DROP_OFF, items, customer, DropOffRequest(tomorrow()))
    add_payment(cashier, sale, Payment.Method.CASH, "50.00")
    order = advance_drop_off_order(cashier, sale.drop_off_order)
    order = advance_drop_off_order(cashier, order)
    add_payment(cashier, sale, Payment.Method.DEBIT_CARD, "70.00")

    delivered = deliver_drop_off_order(cashier, order)

    assert delivered.status == DELIVERED
    assert delivered.sale.status == Sale.Status.PAID
    assert delivered.sale.balance == 0


def test_only_the_admin_role_delivers_with_balance():
    admin = Group.objects.get(name=ADMIN_ROLE).permissions
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE).permissions

    assert admin.filter(codename="deliver_with_balance").exists()
    assert not employee_role.filter(codename="deliver_with_balance").exists()


def test_drop_off_orders_admin_lists_orders(admin_client, sale):
    response = admin_client.get(reverse("admin:sales_dropofforder_changelist"))

    assert sale.number in response.content.decode()


def test_drop_off_orders_cannot_be_added_in_admin(admin_client):
    response = admin_client.get(reverse("admin:sales_dropofforder_add"))

    assert response.status_code == 403
