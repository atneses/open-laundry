"""Tests for the dashboard indicators, for today and the month (plan Stage 11.1)."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from core.models import Branch
from core.reports import EmployeeTotal, MachineLoads, Money, build_dashboard
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from customers.models import Customer
from inventory.models import Product
from machines.models import Machine, MachineCycle
from sales.models import (
    CashSession,
    Discount,
    DropOffOrder,
    Mode,
    Payment,
    Sale,
    Service,
    ServicePrice,
)
from sales.services import (
    DropOffRequest,
    ItemRequest,
    add_payment,
    apply_discount,
    cancel_sale,
    create_sale,
    open_cash_session,
)

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 15)
EARLIER_THIS_MONTH = date(2026, 3, 2)
LAST_MONTH = date(2026, 2, 28)
CASH = Payment.Method.CASH
CREDIT_CARD = Payment.Method.CREDIT_CARD


def at(day, hour=12):
    """A moment of the day in the local time zone."""

    return timezone.make_aware(datetime.combine(day, time(hour)))


def employee(username, branch, **fields):
    """A user with the Employee role, which can charge, cancel and discount sales."""

    user = get_user_model().objects.create_user(username, branch=branch, **fields)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


@pytest.fixture
def manager(branch):
    """A user with the Admin role, which can view reports."""

    user = get_user_model().objects.create_user("manager", branch=branch, is_staff=True)
    user.groups.add(Group.objects.get(name=ADMIN_ROLE))

    return user


@pytest.fixture
def cashier(branch):
    user = employee("cashier", branch, first_name="Laura", last_name="Pérez")
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


def paid_sale(cashier, wash, method, paid_on):
    """A $45.00 self-service sale paid on ``paid_on``."""

    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    payment = add_payment(cashier, sale, method, "45.00", "VOUCHER-1" if method != CASH else "")
    Payment.objects.filter(pk=payment.pk).update(created_at=at(paid_on))

    return sale


def cancelled_sale(cashier, wash, cancelled_on):
    """A $45.00 self-service sale cancelled on ``cancelled_on``."""

    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    cancel_sale(cashier, sale, "Wrong service")
    Sale.objects.filter(pk=sale.pk).update(cancelled_at=at(cancelled_on))

    return sale


def test_money_collected_today_and_this_month(manager, cashier, wash):
    paid_sale(cashier, wash, CASH, DAY)
    paid_sale(cashier, wash, CREDIT_CARD, EARLIER_THIS_MONTH)
    paid_sale(cashier, wash, CASH, LAST_MONTH)

    dashboard = build_dashboard(manager, DAY)

    assert dashboard.collected_today == Money(cash=Decimal("45.00"), card=Decimal(0))
    assert dashboard.collected_month == Money(cash=Decimal("45.00"), card=Decimal("45.00"))


def test_cancellation_gives_back_its_payments_when_it_was_cancelled(manager, cashier, wash):
    sale = paid_sale(cashier, wash, CASH, LAST_MONTH)
    cancel_sale(cashier, sale, "Wrong service")
    Sale.objects.filter(pk=sale.pk).update(cancelled_at=at(DAY))

    dashboard = build_dashboard(manager, DAY)

    assert dashboard.collected_today == Money(cash=Decimal("-45.00"), card=Decimal(0))


def test_loads_count_started_cycles_of_each_machine(manager, cashier, wash, branch):
    washer = Machine.objects.create(branch=branch, kind=Machine.Kind.WASHER, label="Lavadora 1")
    Machine.objects.create(branch=branch, kind=Machine.Kind.DRYER, label="Secadora 1")
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(5, service=wash)])
    cycles = list(MachineCycle.objects.filter(sale_item__sale=sale))
    started = [
        (MachineCycle.Status.RUNNING, DAY),
        (MachineCycle.Status.FINISHED, DAY),
        (MachineCycle.Status.FINISHED, EARLIER_THIS_MONTH),
        (MachineCycle.Status.FAILED, DAY),
        (MachineCycle.Status.FINISHED, LAST_MONTH),
    ]

    for cycle, (status, day) in zip(cycles, started, strict=True):
        MachineCycle.objects.filter(pk=cycle.pk).update(
            machine=washer,
            status=status,
            started_by=cashier,
            started_at=at(day),
            finished_at=at(day, 13),
        )

    dashboard = build_dashboard(manager, DAY)

    assert dashboard.loads == [
        MachineLoads("Lavadora 1", today=2, month=3),
        MachineLoads("Secadora 1", today=0, month=0),
    ]


def test_drop_off_orders_pending_and_ready(manager, cashier, wash, branch):
    statuses = [
        DropOffOrder.Status.RECEIVED,
        DropOffOrder.Status.IN_PROGRESS,
        DropOffOrder.Status.READY,
        DropOffOrder.Status.DELIVERED,
    ]

    for number, status in enumerate(statuses):
        customer = Customer.objects.create(branch=branch, name="Ana", phone=f"551234567{number}")
        sale = create_sale(
            cashier,
            Mode.DROP_OFF,
            [ItemRequest(1, service=wash)],
            customer=customer,
            drop_off=DropOffRequest(timezone.now() + timedelta(days=1)),
        )
        DropOffOrder.objects.filter(sale=sale).update(
            status=status,
            delivered_at=timezone.now() if status == DropOffOrder.Status.DELIVERED else None,
            delivered_by=cashier if status == DropOffOrder.Status.DELIVERED else None,
        )

    # A received order whose sale was cancelled no longer counts.
    cancelled = create_sale(
        cashier,
        Mode.DROP_OFF,
        [ItemRequest(1, service=wash)],
        customer=customer,
        drop_off=DropOffRequest(timezone.now() + timedelta(days=1)),
    )
    cancel_sale(cashier, cancelled, "Duplicated")

    dashboard = build_dashboard(manager, DAY)

    assert (dashboard.pending_orders, dashboard.ready_orders) == (2, 1)


def test_low_stock_lists_products_below_their_minimum(manager, branch):
    Product.objects.create(branch=branch, name="Detergent", unit="ml", stock=100, min_stock=500)
    Product.objects.create(branch=branch, name="Softener", unit="ml", stock=500, min_stock=500)
    other = Branch.objects.create(name="Norte", sale_prefix="B")
    Product.objects.create(branch=other, name="Bleach", unit="ml", stock=0, min_stock=500)

    dashboard = build_dashboard(manager, DAY)

    assert [product.name for product in dashboard.low_stock] == ["Detergent"]


def test_cash_differences_of_the_month(manager, cashier, branch):
    closed = [
        (Decimal("-20.00"), DAY),
        (Decimal(0), DAY),
        (Decimal("10.00"), LAST_MONTH),
    ]

    for difference, day in closed:
        CashSession.objects.create(
            branch=branch,
            user=cashier,
            opening_float=500,
            counted_cash=500 + difference,
            difference=difference,
            notes="Count" if difference else "",
            closed_at=at(day, 20),
            closed_by=cashier,
        )

    dashboard = build_dashboard(manager, DAY)

    assert [session.difference for session in dashboard.cash_differences] == [Decimal("-20.00")]


def test_cancellations_by_employee(manager, cashier, wash):
    cancelled_sale(cashier, wash, DAY)
    cancelled_sale(cashier, wash, EARLIER_THIS_MONTH)
    cancelled_sale(cashier, wash, LAST_MONTH)

    dashboard = build_dashboard(manager, DAY)

    assert dashboard.cancellations_today == [EmployeeTotal("Laura Pérez", 1, Decimal("45.00"))]
    assert dashboard.cancellations_month == [EmployeeTotal("Laura Pérez", 2, Decimal("90.00"))]


def test_discounts_by_employee_count_each_sale_once(manager, cashier, wash, branch):
    discount = Discount.objects.create(
        branch=branch,
        name="10 off",
        kind=Discount.Kind.PERCENTAGE,
        value=10,
        scope=Discount.Scope.SERVICE,
    )
    discount.services.set([wash])
    items = [ItemRequest(1, service=wash), ItemRequest(1, service=wash)]
    sale = create_sale(cashier, Mode.SELF_SERVICE, items)
    applied = apply_discount(cashier, sale, discount)
    discount.applied.filter(pk__in=[row.pk for row in applied]).update(created_at=at(DAY))

    dashboard = build_dashboard(manager, DAY)

    assert dashboard.discounts_today == [EmployeeTotal("Laura Pérez", 1, Decimal("9.00"))]


def test_dashboard_requires_the_reports_permission(cashier):
    with pytest.raises(PermissionDenied):
        build_dashboard(cashier, DAY)


def test_dashboard_needs_a_branch(staff_with_perms):
    user = staff_with_perms("core.view_reports")

    with pytest.raises(ValidationError):
        build_dashboard(user, DAY)


def test_admin_home_shows_the_dashboard_with_the_reports_permission(client, manager):
    client.force_login(manager)

    response = client.get(reverse("admin:index"))

    assert "dashboard" in response.context


def test_admin_home_is_the_default_one_without_the_reports_permission(client, branch):
    user = employee("employee", branch, is_staff=True)
    client.force_login(user)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert "dashboard" not in response.context


def test_only_the_admin_role_gets_the_reports_permission():
    roles = Group.objects.filter(permissions__codename="view_reports")

    assert list(roles.values_list("name", flat=True)) == [ADMIN_ROLE]
