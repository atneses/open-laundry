"""Tests for products, consumption per load and stock movements (plan Stage 4)."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.roles import EMPLOYEE_ROLE
from inventory.models import LoadConsumption, Product, StockMovement
from inventory.services import record_stock_movement
from sales.models import Service

pytestmark = pytest.mark.django_db


@pytest.fixture
def detergent(branch):
    return Product.objects.create(name="Detergent", unit="ml", min_stock=1000, branch=branch)


def record(product, kind, quantity, user, reason=""):
    return record_stock_movement(
        StockMovement(product=product, kind=kind, quantity=quantity, user=user, reason=reason)
    )


def test_purchase_of_5_liters_raises_stock_by_5000_ml(detergent, admin_user):
    record(detergent, "purchase", 5000, admin_user)
    detergent.refresh_from_db()
    assert detergent.stock == Decimal("5000")


def test_movements_add_up(detergent, admin_user):
    record(detergent, "purchase", 5000, admin_user)
    record(detergent, "adjustment", -300, admin_user, reason="Spilled")
    detergent.refresh_from_db()
    assert detergent.stock == Decimal("4700")
    assert detergent.movements.count() == 2


@pytest.mark.parametrize(
    ("kind", "quantity"),
    [("purchase", -10), ("consumption", 150), ("sale", 1), ("adjustment", 0)],
)
def test_quantity_sign_must_match_kind(detergent, admin_user, kind, quantity):
    with pytest.raises(ValidationError):
        record(detergent, kind, quantity, admin_user)
    detergent.refresh_from_db()
    assert detergent.stock == 0
    assert not detergent.movements.exists()


def test_adjustment_needs_a_reason(detergent, admin_user):
    with pytest.raises(ValidationError):
        record(detergent, "adjustment", -300, admin_user, reason="  ")
    detergent.refresh_from_db()
    assert detergent.stock == 0


def test_unit_cannot_change_once_there_are_movements(detergent, admin_user):
    detergent.unit = "L"
    detergent.save()  # no movements yet: allowed

    record(detergent, "purchase", 5, admin_user)
    detergent.unit = "ml"
    with pytest.raises(ValidationError):
        detergent.save()
    detergent.refresh_from_db()
    assert detergent.unit == "L"


def test_unit_is_read_only_in_the_admin_once_there_are_movements(
    admin_client, detergent, admin_user
):
    url = reverse("admin:inventory_product_change", args=[detergent.pk])
    assert "unit" in admin_client.get(url).context["adminform"].form.fields

    record(detergent, "purchase", 5000, admin_user)
    assert "unit" not in admin_client.get(url).context["adminform"].form.fields


def test_only_wash_services_consume_supplies(detergent):
    dry = Service.objects.create(
        name="Dry per load", kind="dry", machine_kind="dryer", uses_machine=True
    )
    with pytest.raises(ValidationError):
        LoadConsumption(service=dry, product=detergent, quantity=150).full_clean()


def test_product_for_sale_needs_a_price(branch):
    with pytest.raises(ValidationError):
        Product(name="Bag", unit="piece", is_for_sale=True, branch=branch).full_clean()


def test_low_stock_filter(admin_client, detergent, branch):
    Product.objects.create(name="Softener", unit="ml", stock=5000, min_stock=1000, branch=branch)
    url = reverse("admin:inventory_product_changelist")
    names = [
        p.name for p in admin_client.get(url, {"stock_level": "low"}).context["cl"].result_list
    ]
    assert names == ["Detergent"]


def test_stock_cannot_be_edited_in_the_product_admin(admin_client, detergent, branch):
    url = reverse("admin:inventory_product_change", args=[detergent.pk])
    data = {
        "name": "Detergent",
        "sku": "",
        "unit": "ml",
        "cost": "0",
        "stock": "999999",
        "min_stock": "1000",
        "branch": branch.pk,
    }
    assert admin_client.post(url, data).status_code == 302
    detergent.refresh_from_db()
    assert detergent.stock == 0


def test_receive_stock_can_record_purchases_but_not_adjustments(
    client, staff_with_perms, detergent
):
    clerk = staff_with_perms("inventory.receive_stock")
    client.force_login(clerk)
    url = reverse("admin:inventory_stockmovement_add")

    response = client.post(url, {"product": detergent.pk, "kind": "purchase", "quantity": "5000"})
    assert response.status_code == 302
    movement = StockMovement.objects.get()
    assert movement.user == clerk

    response = client.post(url, {"product": detergent.pk, "kind": "adjustment", "quantity": "-1"})
    assert response.status_code == 200  # form error: kind not allowed
    assert StockMovement.objects.count() == 1
    detergent.refresh_from_db()
    assert detergent.stock == Decimal("5000")


def test_stock_movements_cannot_be_edited_or_deleted(admin_client, detergent, admin_user):
    movement = record(detergent, "purchase", 5000, admin_user)
    change_url = reverse("admin:inventory_stockmovement_change", args=[movement.pk])
    assert admin_client.post(change_url, {"quantity": "1"}).status_code == 403
    delete_url = reverse("admin:inventory_stockmovement_delete", args=[movement.pk])
    assert admin_client.get(delete_url).status_code == 403


def test_inventory_admin_requires_an_inventory_permission(client, staff_with_perms):
    client.force_login(staff_with_perms("inventory.view_product", username="viewer"))
    assert client.get(reverse("admin:inventory_product_changelist")).status_code == 403

    client.force_login(staff_with_perms("inventory.receive_stock", username="clerk"))
    assert client.get(reverse("admin:inventory_product_changelist")).status_code == 200
    # Creating products is part of managing the catalog.
    assert client.get(reverse("admin:inventory_product_add")).status_code == 403


def test_sidebar_shows_inventory_with_receive_stock(client, staff_with_perms):
    # The sidebar uses a dotted path to can_view_inventory; a typo would hide the links.
    client.force_login(staff_with_perms("inventory.receive_stock"))
    content = client.get(reverse("admin:index")).content.decode()
    assert reverse("admin:inventory_product_changelist") in content
    assert reverse("admin:inventory_stockmovement_changelist") in content
    assert reverse("admin:inventory_loadconsumption_changelist") not in content


def test_employee_role_can_receive_but_not_adjust_stock():
    codenames = set(
        Group.objects.get(name=EMPLOYEE_ROLE).permissions.values_list("codename", flat=True)
    )
    assert "receive_stock" in codenames
    assert "adjust_stock" not in codenames
