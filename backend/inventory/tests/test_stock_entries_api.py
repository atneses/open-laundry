"""Tests for the stock entries API: products, record an entry and history (plan Stage 12.8)."""

import uuid
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from inventory.models import Product, StockMovement
from inventory.services import receive_stock, record_stock_movement

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/inventory/products/"
MOVEMENTS_URL = "/api/inventory/movements/"


@pytest.fixture
def employee(branch):
    """A user with the Employee role, which can record stock entries."""

    user = get_user_model().objects.create_user(
        username="employee",
        first_name="Ana",
        last_name="López",
        branch=branch,
    )
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)

    return client


@pytest.fixture
def client(employee):
    return client_for(employee)


@pytest.fixture
def detergent(branch):
    return Product.objects.create(branch=branch, name="Detergent", unit="ml", stock=1000)


def receive(client, body, key=None):
    """POST a stock entry with an Idempotency-Key (a new one unless ``key`` is given)."""

    return client.post(
        MOVEMENTS_URL,
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
    )


def test_products_include_supplies_not_for_sale(client, branch, detergent):
    other = Branch.objects.create(name="Norte", sale_prefix="N")
    Product.objects.create(branch=other, name="Bleach", unit="ml")

    response = client.get(PRODUCTS_URL)

    assert response.data["results"] == [
        {
            "id": detergent.pk,
            "name": "Detergent",
            "unit": "ml",
            "stock": "1000.000",
            "min_stock": "0.000",
        },
    ]


def test_record_an_entry(client, detergent):
    response = receive(client=client, body={"product": detergent.pk, "quantity": "5000"})

    assert response.status_code == 201
    assert (response.data["quantity"], response.data["unit_cost"]) == ("5000.000", None)
    detergent.refresh_from_db()
    assert detergent.stock == Decimal(6000)


def test_record_an_entry_with_its_unit_cost(client, detergent):
    body = {"product": detergent.pk, "quantity": "5000", "unit_cost": "0.05"}

    response = receive(client=client, body=body)

    assert response.data["unit_cost"] == "0.0500"


def test_a_retried_entry_is_recorded_once(client, detergent):
    key = uuid.uuid4()
    body = {"product": detergent.pk, "quantity": "5000"}
    receive(client=client, body=body, key=key)

    response = receive(client=client, body=body, key=key)

    assert response.status_code == 201
    detergent.refresh_from_db()
    assert detergent.stock == Decimal(6000)
    assert StockMovement.objects.filter(product=detergent).count() == 1


def test_a_key_reused_with_other_data_is_a_conflict(client, detergent):
    key = uuid.uuid4()
    receive(client=client, body={"product": detergent.pk, "quantity": "5000"}, key=key)

    response = receive(client=client, body={"product": detergent.pk, "quantity": "1"}, key=key)

    assert response.status_code == 409


def test_a_key_used_by_another_branch_is_a_conflict(client, detergent):
    other = get_user_model().objects.create_user(
        username="other",
        branch=Branch.objects.create(name="Norte", sale_prefix="N"),
    )
    other.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    bleach = Product.objects.create(branch=other.branch, name="Bleach", unit="ml")
    key = uuid.uuid4()
    receive(client=client_for(other), body={"product": bleach.pk, "quantity": "5"}, key=key)

    response = receive(client=client, body={"product": detergent.pk, "quantity": "5"}, key=key)

    assert response.status_code == 409
    detergent.refresh_from_db()
    assert detergent.stock == Decimal(1000)


def test_an_entry_without_an_idempotency_key_is_rejected(client, detergent):
    response = client.post(
        MOVEMENTS_URL,
        {"product": detergent.pk, "quantity": "5000"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "body",
    [{"quantity": "0"}, {"quantity": "-5"}, {"quantity": "5", "unit_cost": "-1"}],
    ids=["zero", "negative", "negative-cost"],
)
def test_an_invalid_entry_is_rejected(client, detergent, body):
    response = receive(client=client, body={"product": detergent.pk, **body})

    assert response.status_code == 400
    detergent.refresh_from_db()
    assert detergent.stock == Decimal(1000)


def test_a_product_of_another_branch_is_rejected(client):
    other = Branch.objects.create(name="Norte", sale_prefix="N")
    bleach = Product.objects.create(branch=other, name="Bleach", unit="ml")

    response = receive(client=client, body={"product": bleach.pk, "quantity": "5"})

    assert response.status_code == 400
    assert "product" in response.data


def test_the_history_shows_only_entries_newest_first(client, employee, detergent):
    first = receive_stock(user=employee, product=detergent, quantity=Decimal(100))
    record_stock_movement(
        movement=StockMovement(
            product=detergent,
            kind=StockMovement.Kind.ADJUSTMENT,
            quantity=Decimal(-10),
            reason="Spill",
        ),
    )
    second = receive_stock(user=employee, product=detergent, quantity=Decimal(200))

    response = client.get(MOVEMENTS_URL)

    rows = response.data["results"]
    assert [row["id"] for row in rows] == [second.pk, first.pk]
    assert (rows[0]["product_name"], rows[0]["unit"], rows[0]["recorded_by"]) == (
        "Detergent",
        "ml",
        employee.get_display_name(),
    )


def test_the_history_queries_do_not_grow_with_its_rows(
    client,
    employee,
    detergent,
    django_assert_num_queries,
):
    for _ in range(3):
        record_stock_movement(
            movement=StockMovement(
                product=detergent,
                kind=StockMovement.Kind.PURCHASE,
                quantity=Decimal(100),
                created_by=employee,
            ),
        )

    # Permissions, page count and the page itself, however many rows it has.
    with django_assert_num_queries(num=4):
        client.get(MOVEMENTS_URL)


def test_the_history_leaves_out_other_branches(client):
    other = get_user_model().objects.create_user(
        username="other",
        branch=Branch.objects.create(name="Norte", sale_prefix="N"),
    )
    other.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    bleach = Product.objects.create(branch=other.branch, name="Bleach", unit="ml")
    receive_stock(user=other, product=bleach, quantity=Decimal(5))

    response = client.get(MOVEMENTS_URL)

    assert response.data["results"] == []


@pytest.mark.parametrize(
    ("method", "url"),
    [("get", PRODUCTS_URL), ("get", MOVEMENTS_URL), ("post", MOVEMENTS_URL)],
    ids=["products", "history", "record"],
)
def test_stock_entries_require_receive_stock(branch, method, url):
    client = APIClient()
    client.force_authenticate(
        get_user_model().objects.create_user(username="noperm", branch=branch),
    )

    response = getattr(client, method)(url)

    assert response.status_code == 403
