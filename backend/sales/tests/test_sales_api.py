"""Tests for the sales API: charge, pay, cancel, list and discounts (plan Stage 12.5)."""

import uuid
from datetime import date, datetime, time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from customers.models import Customer
from sales.models import Discount, Mode, Payment, Sale, Service, ServicePrice
from sales.services import (
    DropOffRequest,
    ItemRequest,
    add_payment,
    create_sale,
    open_cash_session,
)

pytestmark = pytest.mark.django_db

URL = "/api/sales/"


def employee(username, branch):
    """A user with the Employee role: charges, discounts and cancels sales."""

    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)

    return client


def charge(client, body, key=None):
    """POST a charge with an Idempotency-Key (a new one unless ``key`` is given)."""

    return client.post(URL, body, format="json", HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()))


def pay(client, sale, body, key=None):
    return client.post(
        f"{URL}{sale.pk}/payments/",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
    )


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
    ServicePrice.objects.create(service=service, mode=Mode.SELF_SERVICE, price=45, branch=branch)
    ServicePrice.objects.create(service=service, mode=Mode.DROP_OFF, price=60, branch=branch)

    return service


@pytest.fixture
def customer(branch):
    return Customer.objects.create(branch=branch, name="Ana López", phone="5512345678")


def self_service_body(wash, **fields):
    """2 washes ($90.00) paid in cash with $100.00."""

    return {
        "mode": Mode.SELF_SERVICE,
        "items": [{"service": wash.pk, "quantity": "2"}],
        "payments": [{"method": "cash", "amount": "90.00", "received": "100.00"}],
        **fields,
    }


def discount(branch, name="10% off", **fields):
    return Discount.objects.create(
        branch=branch,
        name=name,
        kind=Discount.Kind.PERCENTAGE,
        value=10,
        **fields,
    )


def test_charge_a_paid_self_service_sale(client, wash):
    response = charge(client, self_service_body(wash))

    assert response.status_code == 201
    assert (response.data["total"], response.data["status"]) == ("90.00", Sale.Status.PAID)
    assert response.data["payments"][0]["received"] == "100.00"
    assert len(response.data["items"][0]["cycles"]) == 2


def test_charge_a_drop_off_with_a_discount_and_an_advance(client, wash, customer, branch):
    promised_at = timezone.now() + timedelta(days=1)
    body = {
        "mode": Mode.DROP_OFF,
        "customer": customer.pk,
        "items": [{"service": wash.pk, "quantity": "3"}],
        "discounts": [discount(branch).pk],
        "payments": [{"method": "debit_card", "amount": "100.00", "reference": "V-1"}],
        "drop_off": {"promised_at": promised_at.isoformat(), "notes": "Ropa delicada"},
    }

    response = charge(client, body)

    assert response.status_code == 201
    assert response.data["discounts"] == [
        {"discount": Discount.objects.get().pk, "name": "10% off", "amount": "18.00"},
    ]
    assert (response.data["total"], response.data["balance"]) == ("162.00", "62.00")
    assert response.data["drop_off_order"]["notes"] == "Ropa delicada"


def test_charge_without_an_idempotency_key_is_rejected(client, wash):
    response = client.post(URL, self_service_body(wash), format="json")

    assert response.status_code == 400
    assert "idempotency_key" in response.data
    assert not Sale.objects.exists()


def test_a_retried_charge_returns_the_same_sale(client, wash):
    key = uuid.uuid4()
    first = charge(client, self_service_body(wash), key)

    response = charge(client, self_service_body(wash), key)

    assert (response.status_code, response.data["id"]) == (201, first.data["id"])
    assert Sale.objects.count() == 1


def test_a_reused_key_with_other_data_is_a_conflict(client, wash):
    key = uuid.uuid4()
    charge(client, self_service_body(wash), key)

    response = charge(client, self_service_body(wash, payments=[]), key)

    assert response.status_code == 409
    assert Sale.objects.count() == 1


def test_a_key_taken_meanwhile_is_a_conflict_and_saves_nothing(client, wash, cashier):
    # Another request saved a sale with the key after this one looked for it.
    key = uuid.uuid4()
    other = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    Sale.objects.filter(pk=other.pk).update(
        branch=Branch.objects.create(name="Norte", sale_prefix="B"),
        idempotency_key=key,
    )

    response = charge(client, self_service_body(wash), key)

    assert response.status_code == 409
    assert Sale.objects.count() == 1


def test_a_discount_that_no_longer_applies_rejects_the_charge(client, wash, branch):
    expired = discount(branch, valid_until=timezone.localdate() - timedelta(days=1))

    response = charge(client, self_service_body(wash, discounts=[expired.pk], payments=[]))

    assert response.status_code == 400
    assert "10% off" in response.data["non_field_errors"][0]
    assert not Sale.objects.exists()


def test_a_charge_with_discounts_needs_the_discount_permission(
    staff_with_perms,
    wash,
    branch,
    cashier,
):
    user = staff_with_perms("sales.charge", username="no-discounts")
    user.branch = branch
    user.save()
    body = self_service_body(wash, discounts=[discount(branch).pk], payments=[])

    response = charge(client_for(user), body)

    assert response.status_code == 403
    assert not Sale.objects.exists()


def test_a_payment_over_the_total_rejects_the_whole_charge(client, wash):
    body = self_service_body(wash, payments=[{"method": "cash", "amount": "95.00"}])

    response = charge(client, body)

    assert response.status_code == 400
    assert not Sale.objects.exists()


def test_charge_without_the_permission_is_forbidden(branch, wash):
    user = get_user_model().objects.create_user("guest", branch=branch)

    response = charge(client_for(user), self_service_body(wash))

    assert response.status_code == 403


@pytest.fixture
def unpaid_sale(cashier, wash):
    """2 self-service washes ($90.00), unpaid."""

    return create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, service=wash)])


def test_pay_the_balance_of_a_sale(client, unpaid_sale):
    response = pay(client, unpaid_sale, {"method": "cash", "amount": "90.00"})

    assert response.status_code == 201
    assert (response.data["balance"], response.data["status"]) == ("0.00", Sale.Status.PAID)


def test_a_retried_payment_is_recorded_once(client, unpaid_sale):
    key = uuid.uuid4()
    pay(client, unpaid_sale, {"method": "cash", "amount": "40.00"}, key)

    response = pay(client, unpaid_sale, {"method": "cash", "amount": "40.00"}, key)

    assert response.status_code == 201
    assert Payment.objects.count() == 1


def test_a_payment_key_used_on_another_sale_is_a_conflict(client, cashier, wash, unpaid_sale):
    key = uuid.uuid4()
    other = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    pay(client, other, {"method": "cash", "amount": "45.00"}, key)

    response = pay(client, unpaid_sale, {"method": "cash", "amount": "45.00"}, key)

    assert response.status_code == 409
    assert not unpaid_sale.payments.exists()


def test_a_payment_without_an_idempotency_key_is_rejected(client, unpaid_sale):
    response = client.post(
        f"{URL}{unpaid_sale.pk}/payments/",
        {"method": "cash", "amount": "90.00"},
        format="json",
    )

    assert response.status_code == 400
    assert not unpaid_sale.payments.exists()


def test_cancel_a_sale_with_a_reason(client, unpaid_sale):
    response = client.post(f"{URL}{unpaid_sale.pk}/cancel/", {"reason": "Wrong service"})

    assert response.status_code == 200
    assert (response.data["status"], response.data["cancel_reason"]) == (
        Sale.Status.CANCELLED,
        "Wrong service",
    )


def test_cancel_without_a_reason_is_rejected(client, unpaid_sale):
    response = client.post(f"{URL}{unpaid_sale.pk}/cancel/", {"reason": ""})

    assert response.status_code == 400


def test_cancel_without_the_permission_is_forbidden(staff_with_perms, unpaid_sale, branch):
    user = staff_with_perms("sales.charge", username="no-cancel")
    user.branch = branch
    user.save()

    response = client_for(user).post(f"{URL}{unpaid_sale.pk}/cancel/", {"reason": "Wrong"})

    assert response.status_code == 403


@pytest.fixture
def listed_sales(cashier, wash, customer):
    """A paid self-service sale, a drop-off with balance and a cancelled one with balance."""

    paid = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    add_payment(cashier, paid, Payment.Method.CASH, "45.00")
    with_balance = create_sale(
        cashier,
        Mode.DROP_OFF,
        [ItemRequest(1, service=wash)],
        customer=customer,
        drop_off=DropOffRequest(timezone.now() + timedelta(days=1)),
    )
    cancelled = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    Sale.objects.filter(pk=cancelled.pk).update(
        status=Sale.Status.CANCELLED,
        cancelled_at=timezone.now(),
        cancelled_by=cashier,
        cancel_cash_session=cancelled.cash_session,
        cancel_reason="Wrong service",
        created_at=timezone.make_aware(datetime.combine(date(2026, 3, 1), time(12))),
    )

    return {"paid": paid, "with_balance": with_balance, "cancelled": cancelled}


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"status": Sale.Status.PAID}, {"paid"}),
        ({"mode": Mode.DROP_OFF}, {"with_balance"}),
        ({"has_balance": "true"}, {"with_balance"}),
        ({"has_balance": "false"}, {"paid", "cancelled"}),
        ({"search": "Ana"}, {"with_balance"}),
        ({"date_from": "2026-03-01", "date_to": "2026-03-01"}, {"cancelled"}),
    ],
    ids=["status", "mode", "has-balance", "no-balance", "search-customer", "date-range"],
)
def test_list_filters(client, listed_sales, filters, expected):
    response = client.get(URL, filters)

    assert {row["id"] for row in response.data["results"]} == {
        listed_sales[name].pk for name in expected
    }


def test_list_search_by_sale_number(client, listed_sales):
    number = listed_sales["paid"].number

    response = client.get(URL, {"search": number})

    assert [row["number"] for row in response.data["results"]] == [number]


def test_list_with_an_invalid_filter_is_rejected(client):
    response = client.get(URL, {"status": "lost"})

    assert response.status_code == 400


def test_a_sale_of_another_branch_is_not_found(client, unpaid_sale):
    Sale.objects.filter(pk=unpaid_sale.pk).update(
        branch=Branch.objects.create(name="Norte", sale_prefix="B"),
    )

    response = client.get(f"{URL}{unpaid_sale.pk}/")

    assert response.status_code == 404


def test_cart_discounts_for_the_mode_and_services(client, wash, branch):
    whole_sale = discount(branch, name="Whole sale")
    on_wash = discount(branch, name="On washes", scope=Discount.Scope.SERVICE)
    on_wash.services.set([wash])
    discount(branch, name="Drop-off only", mode=Mode.DROP_OFF)
    ironing = Service.objects.create(name="Ironing", kind="other")
    discount(branch, name="On ironing", scope=Discount.Scope.SERVICE).services.set([ironing])

    response = client.get("/api/discounts/", {"mode": Mode.SELF_SERVICE, "services": [wash.pk]})

    assert {row["id"] for row in response.data["results"]} == {whole_sale.pk, on_wash.pk}


def test_cart_discounts_need_the_mode(client):
    response = client.get("/api/discounts/")

    assert response.status_code == 400
    assert "mode" in response.data


def test_cart_discounts_need_the_discount_permission(staff_with_perms):
    user = staff_with_perms("sales.charge", username="no-discounts")

    response = client_for(user).get("/api/discounts/", {"mode": Mode.SELF_SERVICE})

    assert response.status_code == 403
