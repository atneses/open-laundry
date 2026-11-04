"""Tests for the cash sessions API: open, close, current and history (plan Stage 12.2)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from sales.models import CashSession, Mode, Payment, Service, ServicePrice
from sales.services import ItemRequest, add_payment, create_sale, open_cash_session

pytestmark = pytest.mark.django_db

URL = "/api/cash-sessions/"
HIDDEN_TOTALS = {
    "expected_cash": None,
    "card_total": None,
    "sales_count": None,
    "cancellations_count": None,
}


def user_with_role(username, branch, role):
    user = get_user_model().objects.create_user(username, branch=branch, first_name=username)
    user.groups.add(Group.objects.get(name=role))

    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)

    return client


@pytest.fixture
def cashier(branch):
    return user_with_role("Laura", branch, EMPLOYEE_ROLE)


@pytest.fixture
def other_cashier(branch):
    return user_with_role("Pedro", branch, EMPLOYEE_ROLE)


@pytest.fixture
def manager(branch):
    """Admin role: sees every cash session (view_all_cash_sessions)."""

    return user_with_role("Marta", branch, ADMIN_ROLE)


@pytest.fixture
def cash_sale(cashier, branch):
    """A $45.00 sale paid in cash in the cashier's open session."""

    open_cash_session(cashier, 500)
    wash = Service.objects.create(name="Wash per load", kind="wash")
    ServicePrice.objects.create(service=wash, mode=Mode.SELF_SERVICE, price=45, branch=branch)
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    add_payment(cashier, sale, Payment.Method.CASH, "45.00")

    return sale


def closed_session(user, counted_cash="500.00", notes=""):
    session = open_cash_session(user, 500)
    client_for(user).post(
        f"{URL}{session.pk}/close/",
        {"counted_cash": counted_cash, "notes": notes},
    )

    return session


def test_open_a_cash_session(cashier):
    response = client_for(cashier).post(URL, {"opening_float": "500.00"})

    assert response.status_code == 201
    assert CashSession.objects.get(pk=response.data["id"]).user == cashier


def test_open_without_the_permission_is_forbidden(branch):
    user = get_user_model().objects.create_user("guest", branch=branch)

    response = client_for(user).post(URL, {"opening_float": "500.00"})

    assert response.status_code == 403


def test_open_when_the_branch_has_one_open_is_rejected(cashier, other_cashier):
    open_cash_session(other_cashier, 500)

    response = client_for(cashier).post(URL, {"opening_float": "500.00"})

    assert response.status_code == 400
    assert "non_field_errors" in response.data


def test_opening_float_cannot_be_negative(cashier):
    response = client_for(cashier).post(URL, {"opening_float": "-1.00"})

    assert response.status_code == 400
    assert "opening_float" in response.data


def test_cashier_does_not_see_the_totals_of_an_open_session(cashier, cash_sale):
    response = client_for(cashier).get(f"{URL}current/")

    assert {field: response.data[field] for field in HIDDEN_TOTALS} == HIDDEN_TOTALS


def test_manager_sees_the_totals_of_an_open_session(manager, cash_sale):
    response = client_for(manager).get(f"{URL}current/")

    assert response.data["expected_cash"] == "545.00"
    assert response.data["sales_count"] == 1


def test_current_shows_the_session_another_cashier_opened(cashier, other_cashier):
    open_cash_session(other_cashier, 500)

    response = client_for(cashier).get(f"{URL}current/")

    assert response.data["user"] == "Pedro"
    assert response.data["expected_cash"] is None


def test_current_without_an_open_session_is_not_found(cashier):
    response = client_for(cashier).get(f"{URL}current/")

    assert response.status_code == 404


def test_close_own_session_shows_the_difference(cashier, cash_sale):
    session = CashSession.objects.get()

    response = client_for(cashier).post(
        f"{URL}{session.pk}/close/",
        {"counted_cash": "540.00", "notes": "Missing change"},
    )

    assert response.status_code == 200
    assert response.data["expected_cash"] == "545.00"
    assert response.data["difference"] == "-5.00"


def test_close_with_a_difference_needs_notes(cashier, cash_sale):
    session = CashSession.objects.get()

    response = client_for(cashier).post(f"{URL}{session.pk}/close/", {"counted_cash": "540.00"})

    assert response.status_code == 400
    assert "notes" in response.data


def test_cashier_cannot_close_the_session_of_another(cashier, other_cashier):
    session = open_cash_session(other_cashier, 500)

    response = client_for(cashier).post(f"{URL}{session.pk}/close/", {"counted_cash": "500.00"})

    assert response.status_code == 404
    session.refresh_from_db()
    assert session.closed_at is None


def test_manager_closes_a_forgotten_session(manager, other_cashier):
    session = open_cash_session(other_cashier, 500)

    response = client_for(manager).post(f"{URL}{session.pk}/close/", {"counted_cash": "500.00"})

    assert response.status_code == 200
    assert response.data["closed_by"] == "Marta"


def test_cashier_history_lists_only_their_sessions(cashier, other_cashier):
    own = closed_session(cashier)
    closed_session(other_cashier)

    response = client_for(cashier).get(URL)

    assert [row["id"] for row in response.data["results"]] == [own.pk]


def test_manager_history_lists_every_session(manager, cashier, other_cashier):
    first = closed_session(cashier)
    second = closed_session(other_cashier)

    response = client_for(manager).get(URL)

    assert [row["id"] for row in response.data["results"]] == [second.pk, first.pk]


def test_cashier_cannot_see_the_session_of_another(cashier, other_cashier):
    session = closed_session(other_cashier)

    response = client_for(cashier).get(f"{URL}{session.pk}/")

    assert response.status_code == 404


def test_history_without_the_permission_is_forbidden(branch):
    user = get_user_model().objects.create_user("guest", branch=branch)

    response = client_for(user).get(URL)

    assert response.status_code == 403


def test_closed_session_shows_its_totals_to_the_cashier(cashier):
    session = closed_session(cashier)

    response = client_for(cashier).get(f"{URL}{session.pk}/")

    assert Decimal(response.data["expected_cash"]) == Decimal("500.00")
