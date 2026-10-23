"""Tests for machines and machine cycles: data rules, roles and admin (plan Stage 9.1)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from machines.models import Machine, MachineCycle
from sales.models import Mode, Service, ServicePrice
from sales.services import ItemRequest, create_sale, open_cash_session

pytestmark = pytest.mark.django_db

RUNNING = MachineCycle.Status.RUNNING


@pytest.fixture
def cashier(branch):
    user = get_user_model().objects.create_user("cashier", branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    open_cash_session(user, 500)

    return user


@pytest.fixture
def washer(branch):
    return Machine.objects.create(branch=branch, kind=Machine.Kind.WASHER, label="Lavadora 1")


@pytest.fixture
def sale(cashier, branch):
    """A self-service sale of 1 wash."""

    wash = Service.objects.create(
        name="Wash per load",
        kind="wash",
        machine_kind="washer",
        uses_machine=True,
        expected_minutes=36,
    )
    ServicePrice.objects.create(service=wash, mode=Mode.SELF_SERVICE, price=45, branch=branch)

    return create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])


@pytest.fixture
def cycle(sale):
    return MachineCycle.objects.create(sale_item=sale.items.get())


def test_a_machine_label_is_unique_per_branch(branch, washer):
    with pytest.raises(IntegrityError):
        Machine.objects.create(branch=branch, kind=Machine.Kind.DRYER, label="Lavadora 1")


def test_the_same_label_is_allowed_in_another_branch(washer):
    other = Branch.objects.create(name="Norte", sale_prefix="N")

    machine = Machine.objects.create(branch=other, kind=Machine.Kind.WASHER, label="Lavadora 1")

    assert machine.pk is not None


def test_a_new_machine_is_available(washer):
    assert washer.status == Machine.Status.AVAILABLE


def test_a_new_cycle_is_pending_without_a_machine(cycle):
    assert cycle.status == MachineCycle.Status.PENDING
    assert cycle.machine is None


def test_a_started_cycle_needs_a_machine(cycle, cashier):
    with pytest.raises(IntegrityError):
        MachineCycle.objects.filter(pk=cycle.pk).update(
            status=RUNNING,
            started_by=cashier,
            started_at=timezone.now(),
        )


def test_a_running_cycle_needs_its_start_time(cycle, cashier, washer):
    with pytest.raises(IntegrityError):
        MachineCycle.objects.filter(pk=cycle.pk).update(
            status=RUNNING,
            machine=washer,
            started_by=cashier,
        )


def test_a_finished_cycle_needs_its_end_time(cycle, cashier, washer):
    with pytest.raises(IntegrityError):
        MachineCycle.objects.filter(pk=cycle.pk).update(
            status=MachineCycle.Status.FINISHED,
            machine=washer,
            started_by=cashier,
            started_at=timezone.now(),
        )


def test_expected_minutes_must_be_positive():
    service = Service(name="Wash", kind="wash", machine_kind="washer", uses_machine=True)
    service.expected_minutes = 0

    with pytest.raises(ValidationError) as error:
        service.full_clean()

    assert "expected_minutes" in error.value.message_dict


def test_employee_role_starts_but_does_not_manage_machines():
    permissions = Group.objects.get(name=EMPLOYEE_ROLE).permissions

    assert permissions.filter(codename="start_machine").exists()
    assert not permissions.filter(codename="manage_machines").exists()


def test_admin_role_gets_the_machines_permissions():
    permissions = Group.objects.get(name=ADMIN_ROLE).permissions

    assert permissions.filter(codename="manage_machines").exists()
    assert permissions.filter(codename="view_machinecycle").exists()


def test_machines_admin_rejects_without_manage_machines(client, staff_with_perms):
    client.force_login(staff_with_perms("machines.start_machine"))

    response = client.get(reverse("admin:machines_machine_changelist"))

    assert response.status_code == 403


def test_machines_admin_lists_with_manage_machines(client, staff_with_perms, washer):
    client.force_login(staff_with_perms("machines.manage_machines"))

    response = client.get(reverse("admin:machines_machine_changelist"))

    assert "Lavadora 1" in response.content.decode()


def test_machines_cannot_be_deleted_in_admin(admin_client, washer):
    url = reverse("admin:machines_machine_delete", args=[washer.pk])

    response = admin_client.post(url, {"post": "yes"})

    assert response.status_code == 403
    assert Machine.objects.filter(pk=washer.pk).exists()


def test_machine_cycles_admin_lists_cycles(admin_client, sale, cycle):
    response = admin_client.get(reverse("admin:machines_machinecycle_changelist"))

    assert sale.number in response.content.decode()


def test_machine_cycles_cannot_be_added_in_admin(admin_client):
    response = admin_client.get(reverse("admin:machines_machinecycle_add"))

    assert response.status_code == 403
