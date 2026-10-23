"""Tests for the machine cycles a sale creates and cancels (plan Stage 9.2)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.roles import EMPLOYEE_ROLE
from customers.models import Customer
from inventory.models import Product
from machines.models import Machine, MachineCycle
from sales.models import Mode, Sale, Service, ServicePrice
from sales.services import DropOffRequest, ItemRequest, cancel_sale, create_sale, open_cash_session

pytestmark = pytest.mark.django_db

PENDING = MachineCycle.Status.PENDING
CANCELLED = MachineCycle.Status.CANCELLED
REASON = "Charged the wrong service"


def make_service(branch, name, kind, machine_kind):
    """A service with a price in both modes."""

    service = Service.objects.create(
        name=name,
        kind=kind,
        machine_kind=machine_kind,
        uses_machine=machine_kind != "none",
    )

    for mode in Mode.values:
        ServicePrice.objects.create(service=service, mode=mode, price=50, branch=branch)

    return service


def start(cycle, user, machine):
    """Put the cycle in progress directly, as if its machine was started."""

    MachineCycle.objects.filter(pk=cycle.pk).update(
        status=MachineCycle.Status.RUNNING,
        machine=machine,
        started_by=user,
        started_at=timezone.now(),
    )


@pytest.fixture
def cashier(branch):
    user = get_user_model().objects.create_user("cashier", branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    open_cash_session(user, 500)

    return user


@pytest.fixture
def wash(branch):
    return make_service(branch, "Wash per load", "wash", "washer")


@pytest.fixture
def dry(branch):
    return make_service(branch, "Dry per load", "dry", "dryer")


@pytest.fixture
def sale(cashier, wash, dry):
    """A self-service sale of 2 washes and 1 dry: 3 pending cycles."""

    items = [ItemRequest(2, service=wash), ItemRequest(1, service=dry)]

    return create_sale(cashier, Mode.SELF_SERVICE, items)


def cycles_of(sale):
    return MachineCycle.objects.filter(sale_item__sale=sale)


def test_each_load_of_a_machine_service_creates_a_pending_cycle(sale, wash, dry):
    cycles = cycles_of(sale)

    assert cycles.count() == 3
    assert cycles.filter(sale_item__service=wash).count() == 2
    assert cycles.filter(sale_item__service=dry).count() == 1
    assert set(cycles.values_list("status", flat=True)) == {PENDING}
    assert not cycles.filter(machine__isnull=False).exists()


def test_a_new_cycle_records_who_charged_it(cashier, sale):
    assert set(cycles_of(sale).values_list("created_by", flat=True)) == {cashier.pk}


def test_services_without_machine_and_products_create_no_cycles(cashier, branch):
    sneakers = make_service(branch, "Sneaker wash", "other", "none")
    bag = Product.objects.create(
        branch=branch,
        name="Bag",
        unit="piece",
        is_for_sale=True,
        sale_price=5,
        stock=10,
    )
    items = [ItemRequest(1, service=sneakers), ItemRequest(2, product=bag)]

    sale = create_sale(cashier, Mode.SELF_SERVICE, items)

    assert not cycles_of(sale).exists()


def test_a_drop_off_sale_also_creates_pending_cycles(cashier, wash, branch):
    customer = Customer.objects.create(branch=branch, name="Ana", phone="5512345678")
    drop_off = DropOffRequest(timezone.now() + timedelta(days=1))

    sale = create_sale(cashier, Mode.DROP_OFF, [ItemRequest(3, service=wash)], customer, drop_off)

    assert cycles_of(sale).filter(status=PENDING).count() == 3


def test_cancelling_a_sale_cancels_its_pending_cycles(cashier, sale):
    cancel_sale(cashier, sale, REASON)

    cycles = cycles_of(sale)
    assert set(cycles.values_list("status", flat=True)) == {CANCELLED}
    assert set(cycles.values_list("updated_by", flat=True)) == {cashier.pk}


def test_a_sale_with_a_started_cycle_cannot_be_cancelled(cashier, sale, branch):
    washer = Machine.objects.create(branch=branch, kind=Machine.Kind.WASHER, label="Lavadora 1")
    start(cycles_of(sale).first(), cashier, washer)

    with pytest.raises(ValidationError):
        cancel_sale(cashier, sale, REASON)

    sale.refresh_from_db()
    assert sale.status == Sale.Status.PENDING
    assert cycles_of(sale).filter(status=PENDING).count() == 2
