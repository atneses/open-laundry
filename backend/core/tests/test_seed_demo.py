"""Tests for the demo data command."""

import pytest
from django.core.management import CommandError, call_command

from core.management.commands.seed_demo import CUSTOMERS, DISCOUNTS, MACHINES
from core.management.demo_history import DAYS
from customers.models import Customer
from inventory.models import StockMovement
from machines.models import Machine, MachineCycle
from sales.models import CashSession, Discount, DropOffOrder, Sale, Service, ServicePrice

pytestmark = pytest.mark.django_db

SEEDED_MODELS = [
    ServicePrice,
    StockMovement,
    Customer,
    Machine,
    Discount,
    CashSession,
    Sale,
    MachineCycle,
]


def counts():
    return {model.__name__: model.objects.count() for model in SEEDED_MODELS}


@pytest.fixture
def seeded(settings):
    settings.DEBUG = True
    call_command("seed_demo")


def test_seed_demo_can_run_twice_without_duplicates(seeded):
    before = counts()

    call_command("seed_demo")

    assert counts() == before
    assert ServicePrice.objects.filter(is_active=True).count() == 5
    assert Customer.objects.count() == len(CUSTOMERS)
    assert Machine.objects.count() == len(MACHINES)
    assert Discount.objects.count() == len(DISCOUNTS)


def test_seed_demo_sets_the_expected_minutes_of_wash_and_dry(seeded):
    minutes = dict(
        Service.objects.filter(uses_machine=True).values_list("kind", "expected_minutes"),
    )

    assert minutes == {"wash": 36, "dry": 40}


def test_seed_demo_closes_a_cash_session_per_past_day_and_leaves_today_open(seeded):
    assert CashSession.objects.filter(closed_at__isnull=False).count() == DAYS - 1
    assert CashSession.objects.filter(closed_at__isnull=True).count() == 1


def test_seed_demo_history_has_sales_cycles_and_drop_off_orders(seeded):
    assert Sale.objects.filter(status=Sale.Status.PAID).exists()
    assert MachineCycle.objects.filter(status=MachineCycle.Status.FINISHED).exists()
    assert StockMovement.objects.filter(kind=StockMovement.Kind.CONSUMPTION).exists()
    assert DropOffOrder.objects.filter(status=DropOffOrder.Status.DELIVERED).exists()


def test_seed_demo_refuses_to_run_without_debug(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("seed_demo")
