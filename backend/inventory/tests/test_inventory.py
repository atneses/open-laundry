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

PRODUCT_LIST = "admin:inventory_product_changelist"
MOVEMENT_ADD = "admin:inventory_stockmovement_add"


@pytest.fixture
def detergent(branch):
    return Product.objects.create(name="Detergent", unit="ml", min_stock=1000, branch=branch)


def record(product, kind, quantity, user, reason=""):
    return record_stock_movement(
        StockMovement(
            product=product,
            kind=kind,
            quantity=quantity,
            created_by=user,
            reason=reason,
        ),
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


def test_unit_can_change_without_movements(detergent):
    detergent.unit = "L"

    detergent.save()

    detergent.refresh_from_db()
    assert detergent.unit == "L"


def test_unit_cannot_change_once_there_are_movements(detergent, admin_user):
    record(detergent, "purchase", 5, admin_user)
    detergent.unit = "L"

    with pytest.raises(ValidationError):
        detergent.save()

    detergent.refresh_from_db()
    assert detergent.unit == "ml"


def test_unit_is_editable_in_the_admin_without_movements(admin_client, detergent):
    url = reverse("admin:inventory_product_change", args=[detergent.pk])

    response = admin_client.get(url)

    assert "unit" in response.context["adminform"].form.fields


def test_unit_is_read_only_in_the_admin_once_there_are_movements(
    admin_client,
    detergent,
    admin_user,
):
    record(detergent, "purchase", 5000, admin_user)
    url = reverse("admin:inventory_product_change", args=[detergent.pk])

    response = admin_client.get(url)

    assert "unit" not in response.context["adminform"].form.fields


def test_a_service_without_machine_does_not_consume_supplies(detergent):
    sneakers = Service.objects.create(name="Sneaker wash", kind="other", unit="pair")
    consumption = LoadConsumption(service=sneakers, product=detergent, quantity=150)

    with pytest.raises(ValidationError) as error:
        consumption.full_clean()

    assert "service" in error.value.message_dict


def test_a_dry_service_can_consume_supplies(detergent):
    dry = Service.objects.create(
        name="Dry per load",
        kind="dry",
        machine_kind="dryer",
        uses_machine=True,
    )
    consumption = LoadConsumption(service=dry, product=detergent, quantity=1)

    consumption.full_clean()

    assert consumption.service == dry


def test_product_for_sale_needs_a_price(branch):
    product = Product(name="Bag", unit="piece", is_for_sale=True, branch=branch)

    with pytest.raises(ValidationError):
        product.full_clean()


def test_low_stock_filter(admin_client, detergent, branch):
    Product.objects.create(name="Softener", unit="ml", stock=5000, min_stock=1000, branch=branch)

    response = admin_client.get(reverse(PRODUCT_LIST), {"stock_level": "low"})

    assert [p.name for p in response.context["cl"].result_list] == ["Detergent"]


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

    response = admin_client.post(url, data)

    assert response.status_code == 302
    detergent.refresh_from_db()
    assert detergent.stock == 0


def test_receive_stock_can_record_purchases(client, staff_with_perms, detergent):
    clerk = staff_with_perms("inventory.receive_stock")
    client.force_login(clerk)
    data = {"product": detergent.pk, "kind": "purchase", "quantity": "5000"}

    response = client.post(reverse(MOVEMENT_ADD), data)

    assert response.status_code == 302
    assert StockMovement.objects.get().created_by == clerk
    detergent.refresh_from_db()
    assert detergent.stock == Decimal("5000")


def test_receive_stock_cannot_record_adjustments(client, staff_with_perms, detergent):
    client.force_login(staff_with_perms("inventory.receive_stock"))
    data = {"product": detergent.pk, "kind": "adjustment", "quantity": "-1"}

    response = client.post(reverse(MOVEMENT_ADD), data)

    assert response.status_code == 200  # form error: kind not allowed
    assert not StockMovement.objects.exists()


def test_stock_movements_cannot_be_edited(admin_client, detergent, admin_user):
    movement = record(detergent, "purchase", 5000, admin_user)
    url = reverse("admin:inventory_stockmovement_change", args=[movement.pk])

    response = admin_client.post(url, {"quantity": "1"})

    assert response.status_code == 403


def test_stock_movements_cannot_be_deleted(admin_client, detergent, admin_user):
    movement = record(detergent, "purchase", 5000, admin_user)
    url = reverse("admin:inventory_stockmovement_delete", args=[movement.pk])

    response = admin_client.get(url)

    assert response.status_code == 403


def test_inventory_admin_rejects_django_model_permission(client, staff_with_perms):
    client.force_login(staff_with_perms("inventory.view_product"))

    response = client.get(reverse(PRODUCT_LIST))

    assert response.status_code == 403


def test_inventory_admin_allows_receive_stock(client, staff_with_perms):
    client.force_login(staff_with_perms("inventory.receive_stock"))

    response = client.get(reverse(PRODUCT_LIST))

    assert response.status_code == 200


def test_receive_stock_cannot_create_products(client, staff_with_perms):
    client.force_login(staff_with_perms("inventory.receive_stock"))

    response = client.get(reverse("admin:inventory_product_add"))

    # Creating products is part of managing the catalog.
    assert response.status_code == 403


def test_sidebar_shows_inventory_with_receive_stock(client, staff_with_perms):
    # The sidebar uses a dotted path to can_view_inventory; a typo would hide the links.
    client.force_login(staff_with_perms("inventory.receive_stock"))

    content = client.get(reverse("admin:index")).content.decode()

    assert reverse(PRODUCT_LIST) in content
    assert reverse("admin:inventory_stockmovement_changelist") in content
    assert reverse("admin:inventory_loadconsumption_changelist") not in content


def test_employee_role_can_receive_but_not_adjust_stock():
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE)

    codenames = set(employee_role.permissions.values_list("codename", flat=True))

    assert "receive_stock" in codenames
    assert "adjust_stock" not in codenames
