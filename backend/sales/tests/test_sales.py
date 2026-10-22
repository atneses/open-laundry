"""Tests for charging sales: lines, prices, numbers and stock (plan Stage 7.1)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from customers.models import Customer
from inventory.models import Product, StockMovement
from sales.models import Mode, Sale, Service, ServicePrice
from sales.services import DropOffRequest, ItemRequest, create_sale, open_cash_session

pytestmark = pytest.mark.django_db


def employee(username, branch):
    """A user with the Employee role, which can charge sales."""
    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    return user


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
    ServicePrice.objects.create(service=service, mode=Mode.SELF_SERVICE, price=45, branch=branch)
    ServicePrice.objects.create(service=service, mode=Mode.DROP_OFF, price=60, branch=branch)
    return service


@pytest.fixture
def bag(branch):
    return Product.objects.create(
        branch=branch,
        name="Bag",
        unit="piece",
        is_for_sale=True,
        sale_price=5,
        stock=10,
    )


@pytest.fixture
def customer(branch):
    return Customer.objects.create(branch=branch, name="Ana", phone="5512345678")


def sell_service(user, service, quantity=1):
    return create_sale(user, Mode.SELF_SERVICE, [ItemRequest(quantity, service=service)])


@pytest.fixture
def detergent(branch):
    return Product.objects.create(branch=branch, name="Detergent", unit="ml")


def test_self_service_sale_uses_the_self_service_price(cashier, wash):
    sale = sell_service(cashier, wash, 3)

    item = sale.items.get()
    assert (item.unit_price, item.amount) == (Decimal("45.00"), Decimal("135.00"))
    assert (sale.subtotal, sale.total, sale.balance) == (135, 135, 135)
    assert sale.status == Sale.Status.PENDING
    assert sale.created_by == cashier
    assert sale.cash_session == cashier.cash_sessions.get()


def test_drop_off_sale_uses_the_drop_off_price(cashier, wash, customer):
    items = [ItemRequest(2, service=wash)]
    drop_off = DropOffRequest(timezone.now() + timedelta(days=1))

    sale = create_sale(cashier, Mode.DROP_OFF, items, customer, drop_off)

    assert sale.total == Decimal("120.00")


def test_price_is_kept_when_the_catalog_changes(cashier, wash, branch):
    sale = sell_service(cashier, wash)

    ServicePrice.objects.create(service=wash, mode=Mode.SELF_SERVICE, price=50, branch=branch)

    assert sale.items.get().unit_price == Decimal("45.00")


def test_product_sale_takes_it_out_of_stock(cashier, bag):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, product=bag)])

    bag.refresh_from_db()
    assert bag.stock == 8
    movement = StockMovement.objects.get()
    assert (movement.kind, movement.quantity, movement.sale) == ("sale", -2, sale)
    assert sale.total == Decimal("10.00")


@pytest.mark.parametrize("quantities", [[11], [6, 5]])
def test_product_cannot_be_sold_beyond_its_stock(cashier, bag, quantities):
    items = [ItemRequest(quantity, product=bag) for quantity in quantities]

    with pytest.raises(ValidationError):
        create_sale(cashier, Mode.SELF_SERVICE, items)

    bag.refresh_from_db()
    assert bag.stock == 10
    assert not Sale.objects.exists()


def test_the_last_units_can_be_sold(cashier, bag):
    create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(10, product=bag)])

    bag.refresh_from_db()
    assert bag.stock == 0


def test_a_product_out_of_stock_cannot_be_sold(cashier, bag):
    create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(10, product=bag)])

    with pytest.raises(ValidationError):
        create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, product=bag)])


def test_sale_numbers_are_consecutive(cashier, wash):
    sell_service(cashier, wash)

    sale = sell_service(cashier, wash)

    assert sale.number == "A-000002"


def test_each_branch_has_its_own_sale_numbers(cashier, wash):
    other_branch = Branch.objects.create(name="Norte", sale_prefix="N")
    other = employee("other", other_branch)
    open_cash_session(other, 500)
    ServicePrice.objects.create(
        service=wash,
        mode=Mode.SELF_SERVICE,
        price=45,
        branch=other_branch,
    )
    sell_service(cashier, wash)

    sale = sell_service(other, wash)

    assert sale.number == "N-000001"


def test_sale_numbers_follow_the_branch_prefix(cashier, wash, branch):
    branch.sale_prefix = "B"
    branch.save()

    sale = sell_service(cashier, wash)

    assert sale.number == "B-000001"


def test_charging_requires_the_charge_permission(branch, wash):
    user = get_user_model().objects.create_user("noperm", branch=branch)
    open_cash_session(employee("opener", branch), 500)

    with pytest.raises(PermissionDenied):
        sell_service(user, wash)

    assert not Sale.objects.exists()


def test_charging_requires_an_open_cash_session(branch, wash):
    user = employee("cashier", branch)

    with pytest.raises(ValidationError):
        sell_service(user, wash)

    assert not Sale.objects.exists()


def test_drop_off_requires_a_customer(cashier, wash):
    with pytest.raises(ValidationError) as error:
        create_sale(cashier, Mode.DROP_OFF, [ItemRequest(1, service=wash)])

    assert "customer" in error.value.message_dict


def test_customer_of_another_branch_is_rejected(cashier, wash):
    other = Customer.objects.create(
        branch=Branch.objects.create(name="Norte"),
        name="Luis",
        phone="5500000000",
    )

    with pytest.raises(ValidationError) as error:
        create_sale(cashier, Mode.DROP_OFF, [ItemRequest(1, service=wash)], other)

    assert "customer" in error.value.message_dict


@pytest.mark.parametrize("quantity", [0, -1, Decimal("1.5")])
def test_service_quantity_must_be_a_positive_whole_number(cashier, wash, quantity):
    with pytest.raises(ValidationError):
        sell_service(cashier, wash, quantity)

    assert not Sale.objects.exists()


def test_service_without_price_for_the_mode_is_rejected(cashier):
    dry = Service.objects.create(name="Dry", kind="dry", machine_kind="dryer", uses_machine=True)

    with pytest.raises(ValidationError):
        sell_service(cashier, dry)


def test_product_not_for_sale_is_rejected(cashier, detergent):
    with pytest.raises(ValidationError):
        create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, product=detergent)])


def test_inactive_service_is_rejected(cashier, wash):
    wash.is_active = False
    wash.save()

    with pytest.raises(ValidationError):
        sell_service(cashier, wash)


def test_a_failed_line_charges_nothing(cashier, bag, detergent, branch):
    items = [ItemRequest(1, product=bag), ItemRequest(1, product=detergent)]

    with pytest.raises(ValidationError):
        create_sale(cashier, Mode.SELF_SERVICE, items)

    bag.refresh_from_db()
    assert bag.stock == 10
    assert not Sale.objects.exists()
    branch.refresh_from_db()
    assert branch.last_sale_number == 0


@pytest.mark.parametrize("role", [ADMIN_ROLE, EMPLOYEE_ROLE])
def test_roles_get_the_charge_permission(role):
    group = Group.objects.get(name=role)

    assert group.permissions.filter(codename="charge").exists()


def test_sale_detail_shows_in_admin(admin_client, cashier, wash):
    sale = sell_service(cashier, wash)

    response = admin_client.get(reverse("admin:sales_sale_change", args=[sale.pk]))

    assert response.status_code == 200
    assert sale.number in response.content.decode()


def test_sales_cannot_be_added_in_admin(admin_client):
    response = admin_client.get(reverse("admin:sales_sale_add"))

    assert response.status_code == 403
