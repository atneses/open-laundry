"""Tests for the filters of the sales, cycles and cash sessions lists (plan Stage 11.2)."""

from datetime import date, datetime, time

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from core.roles import EMPLOYEE_ROLE
from machines.models import Machine, MachineCycle
from sales.models import CashSession, Mode, Payment, Sale, Service, ServicePrice
from sales.services import ItemRequest, add_payment, create_sale, open_cash_session

pytestmark = pytest.mark.django_db

DAY = date(2026, 3, 15)
CASH = Payment.Method.CASH
CREDIT_CARD = Payment.Method.CREDIT_CARD


def at(day, hour=12):
    """A moment of the day in the local time zone."""

    return timezone.make_aware(datetime.combine(day, time(hour)))


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

    return service


def sale_paid_with(cashier, wash, *methods, charged_at=None):
    """A sale of 2 washes ($90.00) paid in equal parts with each method."""

    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, service=wash)])
    amount = 90 / len(methods)

    for method in methods:
        add_payment(cashier, sale, method, f"{amount:.2f}", "" if method == CASH else "V-1")

    if charged_at:
        Sale.objects.filter(pk=sale.pk).update(created_at=charged_at)

    return sale


def listed(response):
    return set(response.context["cl"].result_list)


@pytest.mark.parametrize(
    ("method", "expected"),
    [(CASH, {"cash", "mixed"}), (CREDIT_CARD, {"card", "mixed"})],
)
def test_sales_filter_by_payment_method(admin_client, cashier, wash, method, expected):
    sales = {
        "cash": sale_paid_with(cashier, wash, CASH),
        "card": sale_paid_with(cashier, wash, CREDIT_CARD),
        "mixed": sale_paid_with(cashier, wash, CASH, CREDIT_CARD),
    }
    url = reverse("admin:sales_sale_changelist")

    response = admin_client.get(url, {"payment_method": method})

    assert listed(response) == {sales[name] for name in expected}


def test_sales_date_range_includes_the_whole_last_day(admin_client, cashier, wash):
    late_on_the_day = sale_paid_with(cashier, wash, CASH, charged_at=at(DAY, 23))
    sale_paid_with(cashier, wash, CASH, charged_at=at(date(2026, 3, 16), 9))
    url = reverse("admin:sales_sale_changelist")

    response = admin_client.get(
        url,
        {"created_at_from": "2026-03-15", "created_at_to": "2026-03-15"},
    )

    assert listed(response) == {late_on_the_day}


def test_card_sales_of_last_week_by_one_employee(admin_client, cashier, wash, branch):
    other = employee("other", branch)
    wanted = sale_paid_with(cashier, wash, CREDIT_CARD, charged_at=at(DAY))
    sale_paid_with(cashier, wash, CASH, charged_at=at(DAY))
    sale_paid_with(cashier, wash, CREDIT_CARD, charged_at=at(date(2026, 3, 1)))
    by_other = sale_paid_with(cashier, wash, CREDIT_CARD, charged_at=at(DAY))
    Sale.objects.filter(pk=by_other.pk).update(created_by=other)
    filters = {
        "payment_method": CREDIT_CARD,
        "created_by__id__exact": cashier.pk,
        "created_at_from": "2026-03-09",
        "created_at_to": "2026-03-15",
    }

    response = admin_client.get(reverse("admin:sales_sale_changelist"), filters)

    assert listed(response) == {wanted}


def test_cycles_filter_by_start_date(admin_client, cashier, wash, branch):
    washer = Machine.objects.create(branch=branch, kind=Machine.Kind.WASHER, label="Lavadora 1")
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, service=wash)])
    first, second = MachineCycle.objects.filter(sale_item__sale=sale)

    for cycle, day in ((first, DAY), (second, date(2026, 3, 16))):
        MachineCycle.objects.filter(pk=cycle.pk).update(
            machine=washer,
            status=MachineCycle.Status.RUNNING,
            started_by=cashier,
            started_at=at(day),
        )

    url = reverse("admin:machines_machinecycle_changelist")

    response = admin_client.get(
        url,
        {"started_at_from": "2026-03-15", "started_at_to": "2026-03-15"},
    )

    assert listed(response) == {first}


def test_cash_sessions_filter_by_opening_date(admin_client, cashier):
    session = CashSession.objects.get()
    CashSession.objects.filter(pk=session.pk).update(opened_at=at(DAY))
    url = reverse("admin:sales_cashsession_changelist")

    response = admin_client.get(
        url,
        {"opened_at_from": "2026-03-15", "opened_at_to": "2026-03-15"},
    )

    assert listed(response) == {session}


def test_sales_filters_always_show_their_counts(admin_client):
    response = admin_client.get(reverse("admin:sales_sale_changelist"))

    assert response.context["cl"].add_facets
