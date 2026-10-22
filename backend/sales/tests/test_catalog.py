"""Tests for services and prices (plan Stage 4)."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from sales.models import Mode, Service, ServicePrice

pytestmark = pytest.mark.django_db


@pytest.fixture
def wash():
    return Service.objects.create(
        name="Wash per load", kind="wash", machine_kind="washer", uses_machine=True
    )


def service_form(branch, new_prices, existing=()):
    """POST data for the service admin form: existing prices first, then the new ones."""

    data = {
        "name": "Wash per load",
        "kind": "wash",
        "unit": "load",
        "machine_kind": "washer",
        "uses_machine": "on",
        "is_active": "on",
        "prices-TOTAL_FORMS": str(len(existing) + len(new_prices)),
        "prices-INITIAL_FORMS": str(len(existing)),
        "prices-MIN_NUM_FORMS": "0",
        "prices-MAX_NUM_FORMS": "1000",
    }

    for i, price in enumerate(existing):
        data |= {f"prices-{i}-id": price.pk, f"prices-{i}-service": price.service_id}

    for i, (mode, price) in enumerate(new_prices, start=len(existing)):
        data |= {
            f"prices-{i}-mode": mode,
            f"prices-{i}-program": "",
            f"prices-{i}-price": price,
            f"prices-{i}-branch": branch.pk,
        }

    return data


def add_price(service, mode, price, branch):
    return ServicePrice.objects.create(service=service, mode=mode, price=price, branch=branch)


def active_prices(service):
    return {p.mode: p.price for p in service.prices.filter(is_active=True)}


def test_admin_creates_a_service_with_both_prices(admin_client, branch):
    data = service_form(branch, [("self_service", "45.00"), ("drop_off", "60.00")])

    response = admin_client.post(reverse("admin:sales_service_add"), data)

    assert response.status_code == 302, response.content
    service = Service.objects.get(name="Wash per load")
    assert active_prices(service) == {
        Mode.SELF_SERVICE: Decimal("45.00"),
        Mode.DROP_OFF: Decimal("60.00"),
    }


def test_new_price_from_the_admin_replaces_the_active_one(admin_client, branch, wash):
    old = add_price(wash, Mode.SELF_SERVICE, "45.00", branch)
    data = service_form(branch, [("self_service", "50.00")], existing=[old])

    response = admin_client.post(reverse("admin:sales_service_change", args=[wash.pk]), data)

    assert response.status_code == 302, response.content
    old.refresh_from_db()
    assert not old.is_active
    assert old.price == Decimal("45.00")  # kept as history
    assert active_prices(wash) == {Mode.SELF_SERVICE: Decimal("50.00")}


def test_existing_prices_cannot_be_edited_in_the_admin(admin_client, branch, wash):
    old = add_price(wash, Mode.SELF_SERVICE, "45.00", branch)
    data = service_form(branch, [], existing=[old])
    data["prices-0-price"] = "99.00"

    admin_client.post(reverse("admin:sales_service_change", args=[wash.pk]), data)

    old.refresh_from_db()
    assert old.price == Decimal("45.00")
    assert old.is_active


def test_last_price_added_is_the_active_one_per_mode(branch, wash):
    add_price(wash, Mode.SELF_SERVICE, "45.00", branch)
    add_price(wash, Mode.DROP_OFF, "60.00", branch)

    add_price(wash, Mode.SELF_SERVICE, "50.00", branch)

    assert active_prices(wash) == {
        Mode.SELF_SERVICE: Decimal("50.00"),
        Mode.DROP_OFF: Decimal("60.00"),
    }
    assert wash.prices.count() == 3


def test_a_saved_price_cannot_be_edited(branch, wash):
    price = add_price(wash, Mode.SELF_SERVICE, "45.00", branch)
    price.price = "99.00"

    with pytest.raises(ValidationError):
        price.save()

    price.refresh_from_db()
    assert price.price == Decimal("45.00")


def test_a_price_can_be_deactivated(branch, wash):
    price = add_price(wash, Mode.SELF_SERVICE, "45.00", branch)
    price.is_active = False

    price.save()

    price.refresh_from_db()
    assert not price.is_active


def test_a_deactivated_price_cannot_be_reactivated(branch, wash):
    price = add_price(wash, Mode.SELF_SERVICE, "45.00", branch)
    price.is_active = False
    price.save()
    price.is_active = True

    with pytest.raises(ValidationError):
        price.save()


def test_uses_machine_must_match_machine_kind():
    with pytest.raises(IntegrityError):
        Service.objects.create(name="Wash", kind="wash", machine_kind="none", uses_machine=True)


def test_database_allows_one_active_price_per_service_and_mode(branch, wash):
    # bulk_create skips save(), so the database constraint is the last guard.
    fields = {"service": wash, "mode": Mode.DROP_OFF, "branch": branch}

    with pytest.raises(IntegrityError):
        ServicePrice.objects.bulk_create(
            [ServicePrice(price="60.00", **fields), ServicePrice(price="65.00", **fields)]
        )


def test_catalog_admin_rejects_django_model_permission(client, staff_with_perms):
    # Django's own model permission is not enough: the MVP permission is required.
    client.force_login(staff_with_perms("sales.change_service"))

    response = client.get(reverse("admin:sales_service_changelist"))

    assert response.status_code == 403


def test_catalog_admin_allows_manage_catalog(client, staff_with_perms):
    client.force_login(staff_with_perms("sales.manage_catalog"))

    response = client.get(reverse("admin:sales_service_changelist"))

    assert response.status_code == 200


def test_sidebar_shows_catalog_with_manage_catalog(client, staff_with_perms):
    client.force_login(staff_with_perms("sales.manage_catalog"))

    content = client.get(reverse("admin:index")).content.decode()

    assert reverse("admin:sales_service_changelist") in content
    assert reverse("admin:core_user_changelist") not in content
