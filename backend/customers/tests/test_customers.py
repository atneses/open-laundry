"""Tests for customers (plan Stage 5)."""

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from customers.models import Customer

pytestmark = pytest.mark.django_db

CHANGELIST = "admin:customers_customer_changelist"


def test_name_and_phone_are_required(branch):
    customer = Customer(branch=branch)

    with pytest.raises(ValidationError) as error:
        customer.full_clean()

    assert {"name", "phone"} <= error.value.message_dict.keys()


def test_phone_is_saved_with_digits_only(branch):
    customer = Customer.objects.create(branch=branch, name="Ana", phone="55 1234-5678")

    assert customer.phone == "5512345678"


def test_phone_is_unique_per_branch_even_with_another_format(branch):
    Customer.objects.create(branch=branch, name="Ana", phone="5512345678")

    with pytest.raises(IntegrityError):
        Customer.objects.create(branch=branch, name="Ana B", phone="55-1234-5678")


def test_same_phone_is_allowed_in_another_branch(branch):
    other = Branch.objects.create(name="Norte")
    Customer.objects.create(branch=branch, name="Ana", phone="5512345678")

    Customer.objects.create(branch=other, name="Ana", phone="5512345678")

    assert Customer.objects.count() == 2


def test_admin_search_by_last_digits_of_the_phone(admin_client, branch):
    Customer.objects.create(branch=branch, name="Ana", phone="5512345678")
    Customer.objects.create(branch=branch, name="Luis", phone="5598765432")

    response = admin_client.get(reverse(CHANGELIST), {"q": "5678"})

    assert [c.name for c in response.context["cl"].result_list] == ["Ana"]


def test_customers_admin_rejects_django_model_permission(client, staff_with_perms):
    # Django's own model permission is not enough: the MVP permission is required.
    client.force_login(staff_with_perms("customers.change_customer"))

    response = client.get(reverse(CHANGELIST))

    assert response.status_code == 403


def test_customers_admin_allows_manage_customers(client, staff_with_perms):
    client.force_login(staff_with_perms("customers.manage_customers"))

    response = client.get(reverse(CHANGELIST))

    assert response.status_code == 200


def test_sidebar_shows_customers_with_manage_customers(client, staff_with_perms):
    client.force_login(staff_with_perms("customers.manage_customers"))

    content = client.get(reverse("admin:index")).content.decode()

    assert reverse(CHANGELIST) in content


def test_employee_role_can_manage_customers():
    employee = Group.objects.get(name=EMPLOYEE_ROLE)

    assert employee.permissions.filter(codename="manage_customers").exists()
