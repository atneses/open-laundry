"""Tests for the services API: the catalog the POS charges from (plan Stage 12.3)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from sales.models import Mode, Service, ServicePrice

pytestmark = pytest.mark.django_db

URL = "/api/services/"


@pytest.fixture
def client(branch):
    user = get_user_model().objects.create_user("cashier", branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    api_client = APIClient()
    api_client.force_authenticate(user)

    return api_client


def service(name, branch, *, is_active=True, **prices):
    """A service with a price for each mode given, e.g. ``drop_off=60``."""

    created = Service.objects.create(name=name, kind="other", is_active=is_active)

    for mode, price in prices.items():
        ServicePrice.objects.create(service=created, mode=mode, price=price, branch=branch)

    return created


def test_services_list_their_price_for_each_mode(client, branch):
    wash = service("Wash per load", branch, self_service=45, drop_off=60)
    ironing = service("Ironing", branch, drop_off=30)

    response = client.get(URL)

    assert [(row["id"], row["prices"]) for row in response.json()["results"]] == [
        (ironing.pk, [{"mode": "drop_off", "price": "30.00"}]),
        (
            wash.pk,
            [
                {"mode": "drop_off", "price": "60.00"},
                {"mode": "self_service", "price": "45.00"},
            ],
        ),
    ]


def test_inactive_services_and_services_without_a_price_are_left_out(client, branch):
    service("Retired", branch, is_active=False, self_service=45)
    service("Not priced yet", branch)

    response = client.get(URL)

    assert response.data["results"] == []


def test_services_whose_prices_were_all_deactivated_are_left_out(client, branch):
    wash = service("Wash per load", branch, self_service=45, drop_off=60)

    for price in wash.prices.all():
        price.is_active = False
        price.save()

    response = client.get(URL)

    assert response.data["results"] == []


def test_a_new_price_from_the_admin_is_returned(client, branch):
    wash = service("Wash per load", branch, self_service=45)
    ServicePrice.objects.create(service=wash, mode=Mode.SELF_SERVICE, price=50, branch=branch)

    response = client.get(URL)

    assert response.json()["results"][0]["prices"] == [{"mode": "self_service", "price": "50.00"}]


def test_prices_of_another_branch_are_left_out(client):
    service("Wash per load", Branch.objects.create(name="Norte", sale_prefix="B"), self_service=45)

    response = client.get(URL)

    assert response.data["results"] == []


def test_services_without_the_permission_are_forbidden(branch):
    api_client = APIClient()
    api_client.force_authenticate(get_user_model().objects.create_user("guest", branch=branch))

    response = api_client.get(URL)

    assert response.status_code == 403
