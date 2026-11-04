"""Tests for the drop-off orders API: list, advance and deliver (plan Stage 12.6)."""

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from customers.models import Customer
from sales.models import DropOffOrder, Mode, Payment, Sale, Service, ServicePrice
from sales.services import (
    DropOffRequest,
    ItemRequest,
    add_payment,
    cancel_sale,
    create_sale,
    open_cash_session,
)

pytestmark = pytest.mark.django_db

URL = "/api/drop-off-orders/"
RECEIVED = DropOffOrder.Status.RECEIVED
IN_PROGRESS = DropOffOrder.Status.IN_PROGRESS
READY = DropOffOrder.Status.READY
DELIVERED = DropOffOrder.Status.DELIVERED


def employee(username, branch):
    """A user with the Employee role: manages drop-off orders, without deliver_with_balance."""

    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)

    return client


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
def client(cashier):
    return client_for(cashier)


@pytest.fixture
def wash(branch):
    service = Service.objects.create(
        name="Wash per load",
        kind="wash",
        machine_kind="washer",
        uses_machine=True,
    )
    ServicePrice.objects.create(service=service, mode=Mode.DROP_OFF, price=60, branch=branch)

    return service


@pytest.fixture
def customer(branch):
    return Customer.objects.create(branch=branch, name="Ana López", phone="5512345678")


@pytest.fixture
def new_order(cashier, wash, customer):
    """Build the order of a $60.00 unpaid drop-off sale, promised ``days`` from now."""

    def make(days=1, who=customer):
        sale = create_sale(
            user=cashier,
            mode=Mode.DROP_OFF,
            items=[ItemRequest(1, service=wash)],
            customer=who,
            drop_off=DropOffRequest(timezone.now() + timedelta(days=days)),
        )

        return sale.drop_off_order

    return make


@pytest.fixture
def order(new_order):
    return new_order()


@pytest.fixture
def orders(cashier, branch, new_order):
    """A received, a ready and a delivered order, and one of a cancelled sale."""

    received = new_order(days=3)
    ready = new_order(days=1)
    set_status(ready, READY)
    delivered = new_order(days=2)
    set_status(delivered, DELIVERED)
    beto = Customer.objects.create(branch=branch, name="Beto Ruiz", phone="5587654321")
    cancelled = new_order(days=4, who=beto)
    cancel_sale(cashier, cancelled.sale, "Customer changed their mind")

    return {"received": received, "ready": ready, "delivered": delivered, "cancelled": cancelled}


def advance(client, order, status):
    return client.post(f"{URL}{order.pk}/advance/", {"status": status}, format="json")


def deliver(client, order):
    return client.post(f"{URL}{order.pk}/deliver/")


def test_the_list_shows_pending_orders_by_promised_date(client, orders):
    response = client.get(URL)

    assert [row["id"] for row in response.data["results"]] == [
        orders["ready"].pk,
        orders["received"].pk,
    ]
    row = response.data["results"][0]
    assert (row["number"], row["customer"]["name"], row["balance"], row["sale_status"]) == (
        orders["ready"].sale.number,
        "Ana López",
        "60.00",
        Sale.Status.PENDING,
    )


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"status": "delivered"}, {"delivered"}),
        ({"status": "received"}, {"received", "cancelled"}),
        ({"search": "Beto"}, {"cancelled"}),
        ({"search": "Ana"}, {"received", "ready", "delivered"}),
    ],
    ids=["delivered", "received-with-cancelled", "search-cancelled", "search-all-statuses"],
)
def test_list_filters(client, orders, filters, expected):
    response = client.get(URL, filters)

    assert {row["id"] for row in response.data["results"]} == {
        orders[name].pk for name in expected
    }


def test_a_searched_cancelled_order_shows_its_sale_status(client, orders):
    response = client.get(URL, {"search": "Beto"})

    assert response.data["results"][0]["sale_status"] == Sale.Status.CANCELLED


def test_a_blank_search_shows_pending_orders(client, orders):
    response = client.get(URL, {"search": " "})

    assert {row["id"] for row in response.data["results"]} == {
        orders["ready"].pk,
        orders["received"].pk,
    }


def test_list_with_an_invalid_status_is_rejected(client):
    response = client.get(URL, {"status": "lost"})

    assert response.status_code == 400


def test_advance_an_order(client, order):
    response = advance(client, order, IN_PROGRESS)

    assert (response.status_code, response.data["status"]) == (200, IN_PROGRESS)


def test_a_repeated_advance_changes_nothing(client, order):
    advance(client, order, IN_PROGRESS)

    response = advance(client, order, IN_PROGRESS)

    assert (response.status_code, response.data["status"]) == (200, IN_PROGRESS)


@pytest.mark.parametrize(
    ("current", "to_status"),
    [(RECEIVED, READY), (IN_PROGRESS, RECEIVED), (READY, DELIVERED)],
)
def test_advance_to_a_status_that_is_not_next_is_rejected(client, order, current, to_status):
    set_status(order, current)

    response = advance(client, order, to_status)

    assert response.status_code == 400
    order.refresh_from_db()
    assert order.status == current


def test_deliver_a_paid_ready_order(client, cashier, order):
    add_payment(cashier, order.sale, Payment.Method.CASH, "60.00")
    set_status(order, READY)

    response = deliver(client, order)

    assert (response.status_code, response.data["status"]) == (200, DELIVERED)


def test_a_repeated_deliver_changes_nothing(client, order):
    set_status(order, DELIVERED)

    response = deliver(client, order)

    assert (response.status_code, response.data["status"]) == (200, DELIVERED)


def test_deliver_with_balance_without_permission_is_forbidden(client, order):
    set_status(order, READY)

    response = deliver(client, order)

    assert response.status_code == 403
    order.refresh_from_db()
    assert order.status == READY


def test_the_order_of_a_cancelled_sale_cannot_advance(client, orders):
    response = advance(client, orders["cancelled"], IN_PROGRESS)

    assert response.status_code == 400


def test_the_order_of_a_cancelled_sale_cannot_be_delivered(client, orders):
    set_status(orders["cancelled"], READY)

    response = deliver(client, orders["cancelled"])

    assert response.status_code == 400


def test_orders_require_manage_customers(branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    response = client_for(user).get(URL)

    assert response.status_code == 403


def test_an_order_of_another_branch_is_not_found(order):
    other = employee("other", Branch.objects.create(name="Norte", sale_prefix="N"))

    response = client_for(other).get(f"{URL}{order.pk}/")

    assert response.status_code == 404


def test_a_user_without_branch_gets_an_empty_list(order):
    response = client_for(employee("nobranch", None)).get(URL)

    assert (response.status_code, response.data["results"]) == (200, [])


def test_a_full_drop_off_order_through_the_api(client, wash, customer):
    body = {
        "mode": Mode.DROP_OFF,
        "customer": customer.pk,
        "items": [{"service": wash.pk, "quantity": "1"}],
        "drop_off": {"promised_at": (timezone.now() + timedelta(days=1)).isoformat()},
    }
    sale = client.post(
        "/api/sales/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    ).data
    order = DropOffOrder.objects.get(sale_id=sale["id"])
    advance(client, order, IN_PROGRESS)
    advance(client, order, READY)
    client.post(
        f"/api/sales/{sale['id']}/payments/",
        {"method": "cash", "amount": "60.00"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )

    response = deliver(client, order)

    assert (response.status_code, response.data["status"], response.data["balance"]) == (
        200,
        DELIVERED,
        "0.00",
    )
