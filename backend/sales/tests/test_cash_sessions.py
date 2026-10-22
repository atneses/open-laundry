"""Tests for cash sessions: opening, closing and the cash count (plan Stage 6)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.urls import reverse

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from sales.models import CashSession
from sales.services import close_cash_session, open_cash_session

pytestmark = pytest.mark.django_db

SUBMITTED = {"_form_submitted": "on"}


def employee(username, branch=None):
    """A user with the Employee role, which can operate their own cash session."""
    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    return user


@pytest.fixture
def cashier(branch):
    return employee("cashier", branch)


@pytest.fixture
def open_session(cashier):
    return open_cash_session(cashier, 500)


@pytest.fixture
def manager(staff_with_perms):
    return staff_with_perms("sales.view_all_cash_sessions", username="manager")


def close_url(session):
    return reverse("admin:sales_cashsession_close_session", args=[session.pk])


def detail_url(session):
    return reverse("admin:sales_cashsession_change", args=[session.pk])


def test_open_cash_session_in_the_users_branch(cashier, branch):
    session = open_cash_session(cashier, "500.00")

    assert session.branch == branch
    assert session.user == cashier
    assert session.opening_float == Decimal("500.00")
    assert session.closed_at is None


def test_user_without_branch_cannot_open(db):
    user = employee("nobranch")

    with pytest.raises(ValidationError):
        open_cash_session(user, 500)

    assert not CashSession.objects.exists()


def test_opening_float_cannot_be_negative(cashier):
    with pytest.raises(ValidationError) as error:
        open_cash_session(cashier, -1)

    assert "opening_float" in error.value.message_dict


def test_another_user_cannot_open_while_the_branch_has_one_open(open_session, branch):
    other = employee("other", branch)

    with pytest.raises(ValidationError):
        open_cash_session(other, 500)

    assert CashSession.objects.count() == 1


def test_the_same_user_cannot_open_a_second_session(open_session, cashier):
    with pytest.raises(ValidationError):
        open_cash_session(cashier, 500)

    assert CashSession.objects.count() == 1


def test_database_rejects_two_open_sessions_in_a_branch(cashier, branch):
    CashSession.objects.create(branch=branch, user=cashier, opening_float=0)

    with pytest.raises(IntegrityError):
        CashSession.objects.create(branch=branch, user=cashier, opening_float=0)


def test_another_branch_can_open_at_the_same_time(open_session):
    other_branch = Branch.objects.create(name="Norte")
    other = employee("other", other_branch)

    session = open_cash_session(other, 300)

    assert session.branch == other_branch


def test_a_new_session_can_open_after_closing(open_session, cashier):
    close_cash_session(open_session, cashier, 500)

    session = open_cash_session(cashier, 500)

    assert session.closed_at is None


def test_close_without_sales_expects_the_opening_float(open_session, cashier):
    session = close_cash_session(open_session, cashier, "500.00")

    assert session.closed_at is not None
    assert session.expected_cash == Decimal("500.00")
    assert session.counted_cash == Decimal("500.00")
    assert session.difference == 0
    assert session.card_total == 0
    assert (session.sales_count, session.cancellations_count) == (0, 0)


def test_cashier_closing_is_recorded_as_closed_by(open_session, cashier):
    session = close_cash_session(open_session, cashier, 500)

    assert session.closed_by == cashier


@pytest.mark.parametrize("counted", ["450", "520"])
def test_difference_requires_notes(open_session, cashier, counted):
    with pytest.raises(ValidationError) as error:
        close_cash_session(open_session, cashier, counted)

    assert "notes" in error.value.message_dict
    open_session.refresh_from_db()
    assert open_session.closed_at is None


@pytest.mark.parametrize(("counted", "difference"), [("450", "-50.00"), ("520", "20.00")])
def test_difference_with_notes_is_recorded(open_session, cashier, counted, difference):
    session = close_cash_session(open_session, cashier, counted, notes="Change given twice")

    assert session.difference == Decimal(difference)


def test_close_requires_counted_cash(open_session, cashier):
    with pytest.raises(ValidationError) as error:
        close_cash_session(open_session, cashier, None)

    assert "counted_cash" in error.value.message_dict


def test_cannot_close_twice(open_session, cashier):
    session = close_cash_session(open_session, cashier, 500)

    with pytest.raises(ValidationError):
        close_cash_session(session, cashier, 500)


def test_admin_role_gets_cash_session_permissions():
    admin_role = Group.objects.get(name=ADMIN_ROLE)

    codenames = set(admin_role.permissions.values_list("codename", flat=True))

    assert {"operate_cash_session", "view_all_cash_sessions"} <= codenames


def test_employee_role_operates_but_does_not_view_all_cash_sessions():
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE)

    codenames = set(employee_role.permissions.values_list("codename", flat=True))

    assert "operate_cash_session" in codenames
    assert "view_all_cash_sessions" not in codenames


def test_cash_sessions_admin_rejects_without_view_all(client, staff_with_perms):
    client.force_login(staff_with_perms("sales.operate_cash_session"))

    response = client.get(reverse("admin:sales_cashsession_changelist"))

    assert response.status_code == 403


def test_cash_sessions_admin_lists_sessions_with_view_all(client, manager, open_session, cashier):
    close_cash_session(open_session, cashier, 480, notes="Missing change")
    client.force_login(manager)

    response = client.get(reverse("admin:sales_cashsession_changelist"))

    assert response.status_code == 200
    assert "cashier" in response.content.decode()


def test_cash_sessions_cannot_be_added_in_admin(admin_client):
    response = admin_client.get(reverse("admin:sales_cashsession_add"))

    assert response.status_code == 403


def test_cash_sessions_cannot_be_deleted_in_admin(admin_client, open_session):
    url = reverse("admin:sales_cashsession_delete", args=[open_session.pk])

    response = admin_client.post(url, {"post": "yes"})

    assert response.status_code == 403
    assert CashSession.objects.filter(pk=open_session.pk).exists()


def test_open_session_detail_offers_the_close_action(client, manager, open_session):
    client.force_login(manager)

    response = client.get(detail_url(open_session))

    assert close_url(open_session) in response.content.decode()


def test_admin_close_with_difference_and_no_notes_keeps_it_open(client, manager, open_session):
    client.force_login(manager)

    response = client.post(close_url(open_session), SUBMITTED | {"counted_cash": "450"})

    # The error shows in the dialog.
    assert response.status_code == 200
    assert 'id="dialog"' in response.content.decode()
    open_session.refresh_from_db()
    assert open_session.closed_at is None


def test_manager_closes_a_forgotten_session_from_the_admin(client, manager, open_session):
    client.force_login(manager)
    data = SUBMITTED | {"counted_cash": "450", "notes": "Left without closing"}

    response = client.post(close_url(open_session), data)

    assert response.headers["HX-Redirect"] == detail_url(open_session)
    open_session.refresh_from_db()
    assert open_session.closed_by == manager
    assert open_session.difference == Decimal("-50.00")


def test_closing_from_the_admin_requires_view_all_cash_sessions(
    client, staff_with_perms, open_session
):
    client.force_login(staff_with_perms("sales.operate_cash_session"))

    response = client.post(close_url(open_session), SUBMITTED | {"counted_cash": "500"})

    assert response.status_code == 403
    open_session.refresh_from_db()
    assert open_session.closed_at is None


def test_closed_session_detail_does_not_offer_the_close_action(
    admin_client, open_session, cashier
):
    session = close_cash_session(open_session, cashier, 500)

    response = admin_client.get(detail_url(session))

    assert close_url(session) not in response.content.decode()


def test_a_closed_session_cannot_be_closed_from_the_admin(admin_client, open_session, cashier):
    session = close_cash_session(open_session, cashier, 500)

    response = admin_client.post(close_url(session), SUBMITTED | {"counted_cash": "500"})

    assert response.status_code == 403


def test_opening_requires_operate_cash_session(branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        open_cash_session(user, 500)

    assert not CashSession.objects.exists()


def test_an_employee_cannot_close_another_employees_session(open_session, branch):
    other = employee("other", branch)

    with pytest.raises(PermissionDenied):
        close_cash_session(open_session, other, 500)

    open_session.refresh_from_db()
    assert open_session.closed_at is None


def test_a_manager_can_close_another_employees_session(open_session, manager):
    session = close_cash_session(open_session, manager, 500)

    assert session.closed_by == manager
