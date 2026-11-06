"""Tests for the machines API: board, pending cycles, start and finish (plan Stage 12.7)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import serializers
from rest_framework.test import APIClient

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from machines.models import Machine, MachineCycle
from machines.services import finish_cycle, start_cycle
from sales.models import Mode, Payment, Service, ServicePrice
from sales.services import ItemRequest, add_payment, cancel_sale, create_sale, open_cash_session

pytestmark = pytest.mark.django_db

MACHINES_URL = "/api/machines/"
CYCLES_URL = "/api/machine-cycles/"
PENDING = MachineCycle.Status.PENDING
RUNNING = MachineCycle.Status.RUNNING
FINISHED = MachineCycle.Status.FINISHED


def employee(username, branch):
    """A user with the Employee role: charges sales and starts machines."""

    user = get_user_model().objects.create_user(username=username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)

    return client


def make_service(branch, name, machine_kind, expected_minutes=None):
    service = Service.objects.create(
        name=name,
        kind="wash" if machine_kind == "washer" else "dry",
        machine_kind=machine_kind,
        uses_machine=True,
        expected_minutes=expected_minutes,
    )
    ServicePrice.objects.create(service=service, mode=Mode.SELF_SERVICE, price=50, branch=branch)

    return service


def make_machine(branch, label, kind=Machine.Kind.WASHER, **fields):
    return Machine.objects.create(branch=branch, kind=kind, label=label, **fields)


def pending_cycles(sale):
    return list(MachineCycle.objects.filter(sale_item__sale=sale, status=PENDING).order_by("pk"))


@pytest.fixture
def cashier(branch):
    user = employee(username="cashier", branch=branch)
    open_cash_session(user=user, opening_float=500)

    return user


@pytest.fixture
def client(cashier):
    return client_for(cashier)


@pytest.fixture
def wash(branch):
    return make_service(
        branch=branch,
        name="Wash per load",
        machine_kind="washer",
        expected_minutes=36,
    )


@pytest.fixture
def washer(branch):
    return make_machine(branch=branch, label="Lavadora 1")


@pytest.fixture
def paid_sale(cashier, wash):
    """A self-service sale of 2 washes ($100.00), fully paid."""

    sale = create_sale(
        user=cashier,
        mode=Mode.SELF_SERVICE,
        items=[ItemRequest(quantity=2, service=wash)],
    )
    add_payment(user=cashier, sale=sale, method=Payment.Method.CASH, amount="100.00")

    return sale


@pytest.fixture
def cycle(paid_sale):
    return pending_cycles(paid_sale)[0]


@pytest.fixture
def running(cashier, cycle, washer):
    return start_cycle(user=cashier, cycle=cycle, machine=washer)


def as_text(value):
    """A date and time as the API writes it (same format and time zone as ``started_at``)."""

    return serializers.DateTimeField().to_representation(value=value)


def start(client, cycle, machine, **fields):
    return client.post(
        f"{CYCLES_URL}{cycle.pk}/start/",
        {"machine": machine.pk, **fields},
        format="json",
    )


def finish(client, cycle):
    return client.post(f"{CYCLES_URL}{cycle.pk}/finish/")


def test_the_board_shows_each_machine_with_its_running_cycle(client, branch, running, washer):
    make_machine(
        branch=branch,
        label="Antigua secadora",
        kind=Machine.Kind.DRYER,
        status="out_of_service",
    )
    make_machine(branch=branch, label="Lavadora 2")

    response = client.get(MACHINES_URL)

    rows = response.data["results"]
    assert [(row["label"], row["status"]) for row in rows] == [
        ("Lavadora 1", "available"),
        ("Lavadora 2", "available"),
        ("Antigua secadora", "out_of_service"),
    ]
    current = rows[0]["current_cycle"]
    assert (current["id"], current["number"]) == (running.pk, running.sale_item.sale.number)
    expected_end = running.started_at + timedelta(minutes=36)
    assert current["expected_end_at"] == as_text(expected_end)
    assert rows[1]["current_cycle"] is None


def test_a_running_cycle_without_minutes_has_no_expected_end(client, cashier, branch):
    dry = make_service(branch=branch, name="Dry per load", machine_kind="dryer")
    sale = create_sale(
        user=cashier,
        mode=Mode.SELF_SERVICE,
        items=[ItemRequest(quantity=1, service=dry)],
    )
    add_payment(user=cashier, sale=sale, method=Payment.Method.CASH, amount="50.00")
    dryer = make_machine(branch=branch, label="Secadora 1", kind=Machine.Kind.DRYER)
    start_cycle(user=cashier, cycle=pending_cycles(sale)[0], machine=dryer)

    response = client.get(MACHINES_URL)

    assert response.data["results"][0]["current_cycle"]["expected_end_at"] is None


def test_the_pending_list_marks_cycles_that_cannot_start(
    client,
    cashier,
    wash,
    paid_sale,
    running,
):
    unpaid = create_sale(
        user=cashier,
        mode=Mode.SELF_SERVICE,
        items=[ItemRequest(quantity=1, service=wash)],
    )
    cancelled = create_sale(
        user=cashier,
        mode=Mode.SELF_SERVICE,
        items=[ItemRequest(quantity=1, service=wash)],
    )
    cancel_sale(user=cashier, sale=cancelled, reason="Wrong service")

    response = client.get(CYCLES_URL)

    assert [(row["id"], row["can_start"]) for row in response.data["results"]] == [
        (pending_cycles(paid_sale)[0].pk, True),
        (pending_cycles(unpaid)[0].pk, False),
    ]


def test_start_a_cycle(client, cycle, washer):
    response = start(client=client, cycle=cycle, machine=washer)

    assert response.status_code == 200
    assert (response.data["status"], response.data["machine"]) == (RUNNING, washer.pk)


def test_a_repeated_start_changes_nothing(client, running, washer):
    response = start(client=client, cycle=running, machine=washer)

    assert (response.status_code, response.data["status"]) == (200, RUNNING)
    assert response.data["started_at"] == as_text(running.started_at)


def test_start_on_a_machine_of_another_branch_is_rejected(client, cycle):
    other = make_machine(
        branch=Branch.objects.create(name="Norte", sale_prefix="N"),
        label="Lavadora 1",
    )

    response = start(client=client, cycle=cycle, machine=other)

    assert response.status_code == 400
    assert "machine" in response.data


def test_start_a_self_service_cycle_with_balance_is_rejected(client, cashier, wash, washer):
    sale = create_sale(
        user=cashier,
        mode=Mode.SELF_SERVICE,
        items=[ItemRequest(quantity=1, service=wash)],
    )

    response = start(client=client, cycle=pending_cycles(sale)[0], machine=washer)

    assert response.status_code == 400


def test_finish_a_cycle(client, running):
    response = finish(client=client, cycle=running)

    assert (response.status_code, response.data["status"]) == (200, FINISHED)


def test_a_repeated_finish_changes_nothing(client, cashier, running):
    finished_at = finish_cycle(user=cashier, cycle=running).finished_at

    response = finish(client=client, cycle=running)

    assert (response.status_code, response.data["status"]) == (200, FINISHED)
    assert response.data["finished_at"] == as_text(finished_at)


def test_a_cycle_of_another_branch_is_not_found(running):
    other = employee(username="other", branch=Branch.objects.create(name="Norte", sale_prefix="N"))

    response = finish(client=client_for(other), cycle=running)

    assert response.status_code == 404


@pytest.mark.parametrize("url", [MACHINES_URL, CYCLES_URL])
def test_machines_require_start_machine(branch, url):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    response = client_for(user).get(url)

    assert response.status_code == 403


def test_the_board_leaves_out_machines_of_another_branch(client, washer):
    make_machine(branch=Branch.objects.create(name="Norte", sale_prefix="N"), label="Lavadora 9")

    response = client.get(MACHINES_URL)

    assert [row["label"] for row in response.data["results"]] == ["Lavadora 1"]


def test_starting_a_cycle_of_another_branch_is_not_found(cycle, washer):
    other = employee(username="other", branch=Branch.objects.create(name="Norte", sale_prefix="N"))

    response = start(client=client_for(other), cycle=cycle, machine=washer)

    assert response.status_code == 404


@pytest.mark.parametrize("action", ["start", "finish"])
def test_actions_require_start_machine(branch, running, washer, action):
    user = get_user_model().objects.create_user(username="noperm", branch=branch)

    response = client_for(user).post(
        f"{CYCLES_URL}{running.pk}/{action}/",
        {"machine": washer.pk},
        format="json",
    )

    assert response.status_code == 403
