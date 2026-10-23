"""Tests for the demo data command."""

import pytest
from django.core.management import CommandError, call_command

from core.management.commands.seed_demo import CUSTOMERS, MACHINES, PRODUCTS
from customers.models import Customer
from inventory.models import Product, StockMovement
from machines.models import Machine
from sales.models import Service, ServicePrice

pytestmark = pytest.mark.django_db


def test_seed_demo_can_run_twice_without_duplicates(settings):
    settings.DEBUG = True
    call_command("seed_demo")

    call_command("seed_demo")

    assert ServicePrice.objects.filter(is_active=True).count() == 5
    assert Product.objects.get(name="Detergente").stock == 10000

    # One initial purchase per product.
    assert StockMovement.objects.count() == len(PRODUCTS)
    assert Customer.objects.count() == len(CUSTOMERS)
    assert Machine.objects.count() == len(MACHINES)


def test_seed_demo_sets_the_expected_minutes_of_wash_and_dry(settings):
    settings.DEBUG = True

    call_command("seed_demo")

    minutes = dict(
        Service.objects.filter(uses_machine=True).values_list("kind", "expected_minutes"),
    )
    assert minutes == {"wash": 36, "dry": 40}


def test_seed_demo_refuses_to_run_without_debug(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError):
        call_command("seed_demo")
