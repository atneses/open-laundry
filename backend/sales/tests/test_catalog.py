"""Tests for services and prices (plan Stage 4)."""

from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.urls import reverse

from sales.models import Mode, Service, ServicePrice

pytestmark = pytest.mark.django_db


@pytest.fixture
def wash():
    return Service.objects.create(
        name="Wash per load", kind="wash", machine_kind="washer", uses_machine=True
    )


def service_form(branch, prices, **overrides):
    """POST data for the service admin form with its inline prices."""
    data = {
        "name": "Wash per load",
        "kind": "wash",
        "unit": "load",
        "machine_kind": "washer",
        "uses_machine": "on",
        "is_active": "on",
        "prices-TOTAL_FORMS": str(len(prices)),
        "prices-INITIAL_FORMS": "0",
        "prices-MIN_NUM_FORMS": "0",
        "prices-MAX_NUM_FORMS": "1000",
    }
    for i, (mode, price) in enumerate(prices):
        data |= {
            f"prices-{i}-mode": mode,
            f"prices-{i}-program": "",
            f"prices-{i}-price": price,
            f"prices-{i}-valid_from": "2026-10-19",
            f"prices-{i}-branch": branch.pk,
        }
    return data | overrides


def test_admin_creates_a_service_with_both_prices(admin_client, branch):
    data = service_form(branch, [("self_service", "45.00"), ("drop_off", "60.00")])
    response = admin_client.post(reverse("admin:sales_service_add"), data)
    assert response.status_code == 302, response.content

    service = Service.objects.get(name="Wash per load")
    prices = {p.mode: p.price for p in service.prices.all()}
    assert prices == {Mode.SELF_SERVICE: Decimal("45.00"), Mode.DROP_OFF: Decimal("60.00")}


def test_price_can_be_changed_from_the_admin(admin_client, branch, wash):
    price = ServicePrice.objects.create(
        service=wash, mode=Mode.SELF_SERVICE, price="45.00", valid_from="2026-10-19", branch=branch
    )
    data = service_form(branch, [("self_service", "50.00")])
    data |= {"prices-INITIAL_FORMS": "1", "prices-0-id": price.pk, "prices-0-service": wash.pk}

    response = admin_client.post(reverse("admin:sales_service_change", args=[wash.pk]), data)
    assert response.status_code == 302, response.content

    price.refresh_from_db()
    assert price.price == Decimal("50.00")


def test_uses_machine_must_match_machine_kind():
    with pytest.raises(IntegrityError):
        Service.objects.create(name="Wash", kind="wash", machine_kind="none", uses_machine=True)


def test_one_price_per_service_mode_and_day(branch, wash):
    fields = {"service": wash, "mode": Mode.DROP_OFF, "valid_from": "2026-10-19", "branch": branch}
    ServicePrice.objects.create(price="60.00", **fields)
    with pytest.raises(IntegrityError):
        ServicePrice.objects.create(price="65.00", **fields)


def test_catalog_admin_requires_manage_catalog(client, staff_with_perms):
    url = reverse("admin:sales_service_changelist")
    # Django's own model permission is not enough: the MVP permission is required.
    client.force_login(staff_with_perms("sales.change_service", username="clerk"))
    assert client.get(url).status_code == 403

    client.force_login(staff_with_perms("sales.manage_catalog", username="manager"))
    assert client.get(url).status_code == 200


def test_sidebar_shows_catalog_with_manage_catalog(client, staff_with_perms):
    client.force_login(staff_with_perms("sales.manage_catalog"))
    content = client.get(reverse("admin:index")).content.decode()
    assert reverse("admin:sales_service_changelist") in content
    assert reverse("admin:core_user_changelist") not in content
