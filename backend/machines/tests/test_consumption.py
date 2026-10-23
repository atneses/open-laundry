"""Tests for the supplies a started cycle takes from stock (plan Stage 9.4)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from inventory.models import LoadConsumption, Product, StockMovement
from machines.models import Machine, MachineCycle
from machines.services import start_cycle
from sales.models import Mode, Payment, Service, ServicePrice
from sales.services import ItemRequest, add_payment, create_sale, open_cash_session

pytestmark = pytest.mark.django_db

CONSUMPTION = StockMovement.Kind.CONSUMPTION


def make_product(branch, name, stock):
    return Product.objects.create(branch=branch, name=name, unit="ml", stock=stock)


def make_service(branch, name, kind, machine_kind):
    service = Service.objects.create(
        name=name,
        kind=kind,
        machine_kind=machine_kind,
        uses_machine=True,
    )
    ServicePrice.objects.create(service=service, mode=Mode.SELF_SERVICE, price=50, branch=branch)

    return service


def paid_cycle(cashier, service):
    """The cycle of a paid self-service sale of one load of ``service``."""

    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=service)])
    add_payment(cashier, sale, Payment.Method.CASH, "50.00")

    return MachineCycle.objects.get(sale_item__sale=sale)


@pytest.fixture
def cashier(branch):
    user = get_user_model().objects.create_user("cashier", branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    open_cash_session(user, 500)

    return user


@pytest.fixture
def detergent(branch):
    return make_product(branch, "Detergent", 10000)


@pytest.fixture
def softener(branch):
    return make_product(branch, "Softener", 10000)


@pytest.fixture
def wash(branch, detergent, softener):
    """A wash that uses 180 ml of detergent and 150 ml of softener per load."""

    service = make_service(branch, "Wash per load", "wash", "washer")
    LoadConsumption.objects.create(service=service, product=detergent, quantity=180)
    LoadConsumption.objects.create(service=service, product=softener, quantity=150)

    return service


@pytest.fixture
def washer(branch):
    return Machine.objects.create(branch=branch, kind=Machine.Kind.WASHER, label="Lavadora 1")


def test_starting_a_wash_takes_its_supplies_from_stock(cashier, wash, washer, detergent, softener):
    start_cycle(cashier, paid_cycle(cashier, wash), washer)

    detergent.refresh_from_db()
    softener.refresh_from_db()
    assert detergent.stock == Decimal("9820")
    assert softener.stock == Decimal("9850")


def test_each_consumption_is_linked_to_its_cycle(cashier, wash, washer):
    cycle = start_cycle(cashier, paid_cycle(cashier, wash), washer)

    movements = StockMovement.objects.filter(kind=CONSUMPTION)
    assert movements.count() == 2
    assert set(movements.values_list("machine_cycle", flat=True)) == {cycle.pk}
    assert set(movements.values_list("created_by", flat=True)) == {cashier.pk}


def test_with_customer_supplies_nothing_is_taken(cashier, wash, washer, detergent):
    start_cycle(cashier, paid_cycle(cashier, wash), washer, customer_supplies=True)

    detergent.refresh_from_db()
    assert detergent.stock == Decimal("10000")
    assert not StockMovement.objects.filter(kind=CONSUMPTION).exists()


def test_a_dry_without_consumption_takes_nothing(cashier, branch):
    dry = make_service(branch, "Dry per load", "dry", "dryer")
    dryer = Machine.objects.create(branch=branch, kind=Machine.Kind.DRYER, label="Secadora 1")

    start_cycle(cashier, paid_cycle(cashier, dry), dryer)

    assert not StockMovement.objects.filter(kind=CONSUMPTION).exists()


def test_a_dry_with_consumption_takes_its_supplies(cashier, branch):
    dry = make_service(branch, "Dry per load", "dry", "dryer")
    sheets = make_product(branch, "Dryer sheets", 50)
    LoadConsumption.objects.create(service=dry, product=sheets, quantity=1)
    dryer = Machine.objects.create(branch=branch, kind=Machine.Kind.DRYER, label="Secadora 1")

    start_cycle(cashier, paid_cycle(cashier, dry), dryer)

    sheets.refresh_from_db()
    assert sheets.stock == 49


def test_stock_can_go_below_zero_so_a_paid_wash_is_not_stopped(
    cashier,
    wash,
    washer,
    detergent,
):
    Product.objects.filter(pk=detergent.pk).update(stock=100)

    started = start_cycle(cashier, paid_cycle(cashier, wash), washer)

    detergent.refresh_from_db()
    assert started.status == MachineCycle.Status.RUNNING
    assert detergent.stock == Decimal("-80")


def test_only_the_products_of_the_machine_branch_are_taken(cashier, wash, washer):
    north = Branch.objects.create(name="Norte", sale_prefix="N")
    north_detergent = make_product(north, "Detergent", 10000)
    LoadConsumption.objects.create(service=wash, product=north_detergent, quantity=180)

    start_cycle(cashier, paid_cycle(cashier, wash), washer)

    north_detergent.refresh_from_db()
    assert north_detergent.stock == Decimal("10000")
