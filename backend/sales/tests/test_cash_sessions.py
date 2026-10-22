"""Tests for cash sessions: opening, closing and the cash count (plan Stage 6)."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from sales.models import CashSession
from sales.services import close_cash_session, open_cash_session

pytestmark = pytest.mark.django_db


@pytest.fixture
def cashier(branch):
    return get_user_model().objects.create_user("cashier", branch=branch)


def test_open_cash_session_in_the_users_branch(cashier, branch):
    session = open_cash_session(cashier, "500.00")
    assert session.branch == branch
    assert session.user == cashier
    assert session.opening_float == Decimal("500.00")
    assert session.closed_at is None


def test_user_without_branch_cannot_open(db):
    user = get_user_model().objects.create_user("nobranch")
    with pytest.raises(ValidationError):
        open_cash_session(user, 500)
    assert not CashSession.objects.exists()


def test_opening_float_cannot_be_negative(cashier):
    with pytest.raises(ValidationError) as error:
        open_cash_session(cashier, -1)
    assert "opening_float" in error.value.message_dict


def test_only_one_open_session_per_branch(cashier, branch):
    open_cash_session(cashier, 500)
    other = get_user_model().objects.create_user("other", branch=branch)
    with pytest.raises(ValidationError):
        open_cash_session(other, 500)
    with pytest.raises(ValidationError):
        open_cash_session(cashier, 500)
    assert CashSession.objects.count() == 1


def test_database_rejects_two_open_sessions_in_a_branch(cashier, branch):
    CashSession.objects.create(branch=branch, user=cashier, opening_float=0)
    with pytest.raises(IntegrityError):
        CashSession.objects.create(branch=branch, user=cashier, opening_float=0)


def test_another_branch_can_open_at_the_same_time(cashier):
    open_cash_session(cashier, 500)
    other_branch = Branch.objects.create(name="Norte")
    other = get_user_model().objects.create_user("other", branch=other_branch)
    assert open_cash_session(other, 300).branch == other_branch


def test_a_new_session_can_open_after_closing(cashier):
    close_cash_session(open_cash_session(cashier, 500), cashier, 500)
    assert open_cash_session(cashier, 500).closed_at is None


def test_close_without_sales_expects_the_opening_float(cashier):
    session = close_cash_session(open_cash_session(cashier, 500), cashier, "500.00")
    assert session.closed_at is not None
    assert session.expected_cash == Decimal("500.00")
    assert session.counted_cash == Decimal("500.00")
    assert session.difference == 0
    assert session.card_total == 0
    assert (session.sales_count, session.cancellations_count) == (0, 0)


@pytest.mark.parametrize(("counted", "difference"), [("450", "-50.00"), ("520", "20.00")])
def test_difference_requires_notes(cashier, counted, difference):
    session = open_cash_session(cashier, 500)
    with pytest.raises(ValidationError) as error:
        close_cash_session(session, cashier, counted)
    assert "notes" in error.value.message_dict
    session.refresh_from_db()
    assert session.closed_at is None

    session = close_cash_session(session, cashier, counted, notes="Change given twice")
    assert session.difference == Decimal(difference)


def test_close_requires_counted_cash(cashier):
    with pytest.raises(ValidationError) as error:
        close_cash_session(open_cash_session(cashier, 500), cashier, None)
    assert "counted_cash" in error.value.message_dict


def test_cannot_close_twice(cashier):
    session = close_cash_session(open_cash_session(cashier, 500), cashier, 500)
    with pytest.raises(ValidationError):
        close_cash_session(session, cashier, 500)


def test_roles_get_cash_session_permissions():
    admin_role = Group.objects.get(name=ADMIN_ROLE)
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE)
    for codename in ("operate_cash_session", "view_all_cash_sessions"):
        assert admin_role.permissions.filter(codename=codename).exists()
    assert employee_role.permissions.filter(codename="operate_cash_session").exists()
    assert not employee_role.permissions.filter(codename="view_all_cash_sessions").exists()


def test_cash_sessions_admin_requires_view_all_cash_sessions(client, staff_with_perms, cashier):
    close_cash_session(open_cash_session(cashier, 500), cashier, 480, notes="Missing change")
    url = reverse("admin:sales_cashsession_changelist")
    client.force_login(staff_with_perms("sales.operate_cash_session"))
    assert client.get(url).status_code == 403

    client.force_login(staff_with_perms("sales.view_all_cash_sessions", username="manager"))
    response = client.get(url)
    assert response.status_code == 200
    assert "cashier" in response.content.decode()


def test_cash_sessions_are_read_only_in_admin(admin_client, cashier):
    session = open_cash_session(cashier, 500)
    assert admin_client.get(reverse("admin:sales_cashsession_add")).status_code == 403
    delete_url = reverse("admin:sales_cashsession_delete", args=[session.pk])
    assert admin_client.post(delete_url, {"post": "yes"}).status_code == 403
    assert CashSession.objects.filter(pk=session.pk).exists()


def close_url(session):
    return reverse("admin:sales_cashsession_close_session", args=[session.pk])


def test_cashier_closing_is_recorded_as_closed_by(cashier):
    session = close_cash_session(open_cash_session(cashier, 500), cashier, 500)
    assert session.closed_by == cashier


def test_manager_closes_a_forgotten_session_from_the_admin(client, staff_with_perms, cashier):
    session = open_cash_session(cashier, 500)
    manager = staff_with_perms("sales.view_all_cash_sessions", username="manager")
    client.force_login(manager)
    detail = client.get(reverse("admin:sales_cashsession_change", args=[session.pk]))
    assert close_url(session) in detail.content.decode()

    # A difference without notes shows the error in the dialog and keeps it open.
    response = client.post(close_url(session), {"_form_submitted": "on", "counted_cash": "450"})
    assert response.status_code == 200
    assert 'id="dialog"' in response.content.decode()
    session.refresh_from_db()
    assert session.closed_at is None

    response = client.post(
        close_url(session),
        {"_form_submitted": "on", "counted_cash": "450", "notes": "Left without closing"},
    )
    assert response.headers["HX-Redirect"] == reverse(
        "admin:sales_cashsession_change", args=[session.pk]
    )
    session.refresh_from_db()
    assert session.closed_by == manager
    assert session.difference == Decimal("-50.00")


def test_closing_from_the_admin_requires_view_all_cash_sessions(client, staff_with_perms, cashier):
    session = open_cash_session(cashier, 500)
    client.force_login(staff_with_perms("sales.operate_cash_session"))
    response = client.post(close_url(session), {"_form_submitted": "on", "counted_cash": "500"})
    assert response.status_code == 403
    session.refresh_from_db()
    assert session.closed_at is None


def test_a_closed_session_cannot_be_closed_from_the_admin(admin_client, cashier):
    session = close_cash_session(open_cash_session(cashier, 500), cashier, 500)
    detail = admin_client.get(reverse("admin:sales_cashsession_change", args=[session.pk]))
    assert close_url(session) not in detail.content.decode()
    response = admin_client.post(
        close_url(session), {"_form_submitted": "on", "counted_cash": "500"}
    )
    assert response.status_code == 403
