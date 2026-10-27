"""Tests for the customers API: register, edit and search (plan Stage 12.4)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from customers.models import Customer

pytestmark = pytest.mark.django_db

URL = "/api/customers/"


@pytest.fixture
def cashier(branch):
    user = get_user_model().objects.create_user("cashier", branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


@pytest.fixture
def client(cashier):
    api_client = APIClient()
    api_client.force_authenticate(cashier)

    return api_client


@pytest.fixture
def other_branch():
    return Branch.objects.create(name="Norte", sale_prefix="B")


def customer(branch, name="Ana López", phone="5512345678"):
    return Customer.objects.create(branch=branch, name=name, phone=phone)


def test_register_a_customer_in_the_users_branch(client, cashier, branch):
    response = client.post(URL, {"name": "Ana López", "phone": "5512345678"})

    assert response.status_code == 201
    created = Customer.objects.get(pk=response.data["id"])
    assert (created.branch, created.created_by) == (branch, cashier)


def test_register_without_the_permission_is_forbidden(branch):
    api_client = APIClient()
    api_client.force_authenticate(get_user_model().objects.create_user("guest", branch=branch))

    response = api_client.post(URL, {"name": "Ana López", "phone": "5512345678"})

    assert response.status_code == 403


def test_register_a_repeated_phone_is_rejected(client, branch):
    customer(branch)

    response = client.post(URL, {"name": "Otra Ana", "phone": "5512345678"})

    assert response.status_code == 400
    assert "phone" in response.data


def test_the_same_phone_is_allowed_in_another_branch(client, other_branch):
    customer(other_branch)

    response = client.post(URL, {"name": "Ana López", "phone": "5512345678"})

    assert response.status_code == 201


def test_phone_must_have_digits_only(client):
    response = client.post(URL, {"name": "Ana López", "phone": "55 1234-5678"})

    assert response.status_code == 400
    assert "phone" in response.data


def test_register_without_a_branch_is_rejected(staff_with_perms):
    api_client = APIClient()
    api_client.force_authenticate(staff_with_perms("customers.manage_customers"))

    response = api_client.post(URL, {"name": "Ana López", "phone": "5512345678"})

    assert response.status_code == 400
    assert not Customer.objects.exists()


def test_edit_a_customer_keeping_its_phone(client, branch):
    ana = customer(branch)

    response = client.patch(f"{URL}{ana.pk}/", {"name": "Ana María López", "phone": "5512345678"})

    assert response.status_code == 200
    ana.refresh_from_db()
    assert ana.name == "Ana María López"


def test_edit_to_a_phone_another_customer_has_is_rejected(client, branch):
    customer(branch, name="Ana López", phone="5512345678")
    luis = customer(branch, name="Luis Pérez", phone="5587654321")

    response = client.patch(f"{URL}{luis.pk}/", {"phone": "5512345678"})

    assert response.status_code == 400
    assert "phone" in response.data


@pytest.mark.parametrize("search", ["5678", "maría", "María Lóp"])
def test_search_by_part_of_the_phone_or_the_name(client, branch, search):
    wanted = customer(branch, name="María López", phone="5512345678")
    customer(branch, name="Luis Pérez", phone="5587654321")

    response = client.get(URL, {"search": search})

    assert [row["id"] for row in response.data["results"]] == [wanted.pk]


def test_list_only_has_customers_of_the_users_branch(client, branch, other_branch):
    own = customer(branch)
    customer(other_branch)

    response = client.get(URL)

    assert [row["id"] for row in response.data["results"]] == [own.pk]


def test_a_customer_of_another_branch_is_not_found(client, other_branch):
    other = customer(other_branch)

    response = client.get(f"{URL}{other.pk}/")

    assert response.status_code == 404


def test_customers_cannot_be_deleted(client, branch):
    ana = customer(branch)

    response = client.delete(f"{URL}{ana.pk}/")

    assert response.status_code == 405
    assert Customer.objects.filter(pk=ana.pk).exists()
