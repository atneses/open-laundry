"""Tests for starting and finishing machine cycles by hand (plan Stage 9.3)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from customers.models import Customer
from machines.models import Machine, MachineCycle
from machines.services import finish_cycle, start_cycle
from sales.models import Mode, Payment, Service, ServicePrice
from sales.services import (
    DropOffRequest,
    ItemRequest,
    add_payment,
    cancel_sale,
    create_sale,
    open_cash_session,
)

pytestmark = pytest.mark.django_db

PENDING = MachineCycle.Status.PENDING
RUNNING = MachineCycle.Status.RUNNING
FINISHED = MachineCycle.Status.FINISHED


def employee(username, branch):
    """A user with the Employee role: charges sales and starts machines."""

    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def make_service(branch, name, kind, machine_kind):
    service = Service.objects.create(
        name=name,
        kind=kind,
        machine_kind=machine_kind,
        uses_machine=True,
    )

    for mode in Mode.values:
        ServicePrice.objects.create(service=service, mode=mode, price=50, branch=branch)

    return service


def make_machine(branch, label, kind=Machine.Kind.WASHER, **fields):
    return Machine.objects.create(branch=branch, kind=kind, label=label, **fields)


def first_cycle(sale):
    return MachineCycle.objects.filter(sale_item__sale=sale).first()


@pytest.fixture
def cashier(branch):
    user = employee("cashier", branch)
    open_cash_session(user, 500)

    return user


@pytest.fixture
def wash(branch):
    return make_service(branch, "Wash per load", "wash", "washer")


@pytest.fixture
def washer(branch):
    return make_machine(branch, "Lavadora 1")


@pytest.fixture
def sale(cashier, wash):
    """A self-service sale of 2 washes ($100.00), fully paid."""

    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, service=wash)])
    add_payment(cashier, sale, Payment.Method.CASH, "100.00")

    return sale


@pytest.fixture
def cycle(sale):
    return first_cycle(sale)


@pytest.fixture
def running(cashier, cycle, washer):
    return start_cycle(cashier, cycle, washer)


def test_starting_puts_the_cycle_in_progress_on_its_machine(cashier, cycle, washer):
    started = start_cycle(cashier, cycle, washer)

    assert started.status == RUNNING
    assert started.machine == washer
    assert started.is_manual
    assert started.started_by == cashier
    assert started.started_at is not None
    assert not started.customer_supplies


def test_starting_records_that_the_customer_brought_supplies(cashier, cycle, washer):
    started = start_cycle(cashier, cycle, washer, customer_supplies=True)

    assert started.customer_supplies


def test_a_dry_cycle_can_also_use_the_customer_supplies(cashier, branch):
    dry = make_service(branch, "Dry per load", "dry", "dryer")
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=dry)])
    add_payment(cashier, sale, Payment.Method.CASH, "50.00")
    dryer = make_machine(branch, "Secadora 1", kind=Machine.Kind.DRYER)

    started = start_cycle(cashier, first_cycle(sale), dryer, customer_supplies=True)

    assert started.customer_supplies


def test_starting_requires_the_start_machine_permission(cycle, washer, branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        start_cycle(user, cycle, washer)

    cycle.refresh_from_db()
    assert cycle.status == PENDING


def test_a_cycle_of_another_branch_cannot_be_started(cycle, washer):
    other = employee("other", Branch.objects.create(name="Norte", sale_prefix="N"))

    with pytest.raises(PermissionDenied):
        start_cycle(other, cycle, washer)


def test_a_machine_of_another_branch_cannot_be_used(cashier, cycle):
    north = make_machine(Branch.objects.create(name="Norte", sale_prefix="N"), "Lavadora 1")

    with pytest.raises(PermissionDenied):
        start_cycle(cashier, cycle, north)


def test_a_wash_cannot_start_on_a_dryer(cashier, cycle, branch):
    dryer = make_machine(branch, "Secadora 1", kind=Machine.Kind.DRYER)

    with pytest.raises(ValidationError) as error:
        start_cycle(cashier, cycle, dryer)

    assert "machine" in error.value.message_dict


def test_a_machine_out_of_service_cannot_be_started(cashier, cycle, branch):
    broken = make_machine(branch, "Lavadora 2", status=Machine.Status.OUT_OF_SERVICE)

    with pytest.raises(ValidationError) as error:
        start_cycle(cashier, cycle, broken)

    assert "machine" in error.value.message_dict


def test_a_machine_running_a_cycle_cannot_start_another(cashier, sale, running, washer):
    other_cycle = MachineCycle.objects.filter(sale_item__sale=sale, status=PENDING).get()

    with pytest.raises(ValidationError) as error:
        start_cycle(cashier, other_cycle, washer)

    assert "machine" in error.value.message_dict


def test_a_started_cycle_cannot_be_started_again(cashier, running, branch):
    with pytest.raises(ValidationError):
        start_cycle(cashier, running, make_machine(branch, "Lavadora 2"))


def test_a_cycle_of_a_cancelled_sale_cannot_be_started(cashier, sale, cycle, washer):
    cancel_sale(cashier, sale, "Charged the wrong service")

    with pytest.raises(ValidationError):
        start_cycle(cashier, cycle, washer)


def test_a_self_service_sale_with_balance_cannot_start_its_machines(cashier, wash, washer):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    add_payment(cashier, sale, Payment.Method.CASH, "20.00")
    cycle = first_cycle(sale)

    with pytest.raises(ValidationError):
        start_cycle(cashier, cycle, washer)

    cycle.refresh_from_db()
    assert cycle.status == PENDING


def test_a_drop_off_order_with_balance_can_start_its_machines(cashier, wash, washer, branch):
    customer = Customer.objects.create(branch=branch, name="Ana", phone="5512345678")
    drop_off = DropOffRequest(timezone.now() + timedelta(days=1))
    sale = create_sale(cashier, Mode.DROP_OFF, [ItemRequest(1, service=wash)], customer, drop_off)

    started = start_cycle(cashier, first_cycle(sale), washer)

    assert started.status == RUNNING


def test_finishing_a_running_cycle_records_when_and_who(cashier, running):
    finished = finish_cycle(cashier, running)

    assert finished.status == FINISHED
    assert finished.finished_at is not None
    assert finished.updated_by == cashier


def test_a_finished_cycle_frees_its_machine(cashier, sale, running, washer):
    finish_cycle(cashier, running)
    other_cycle = MachineCycle.objects.filter(sale_item__sale=sale, status=PENDING).get()

    started = start_cycle(cashier, other_cycle, washer)

    assert started.status == RUNNING


def test_only_a_running_cycle_can_be_finished(cashier, cycle):
    with pytest.raises(ValidationError):
        finish_cycle(cashier, cycle)


def test_finishing_requires_the_start_machine_permission(running, branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        finish_cycle(user, running)

    running.refresh_from_db()
    assert running.status == RUNNING


def test_a_cycle_of_another_branch_cannot_be_finished(running):
    other = employee("other", Branch.objects.create(name="Norte", sale_prefix="N"))

    with pytest.raises(PermissionDenied):
        finish_cycle(other, running)
