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


def test_name_and_phone_are_required(branch):
    with pytest.raises(ValidationError) as error:
        Customer(branch=branch).full_clean()
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
    url = reverse("admin:customers_customer_changelist")
    results = admin_client.get(url, {"q": "5678"}).context["cl"].result_list
    assert [c.name for c in results] == ["Ana"]


def test_customers_admin_requires_manage_customers(client, staff_with_perms):
    url = reverse("admin:customers_customer_changelist")
    # Django's own model permission is not enough: the MVP permission is required.
    client.force_login(staff_with_perms("customers.change_customer", username="viewer"))
    assert client.get(url).status_code == 403

    client.force_login(staff_with_perms("customers.manage_customers", username="clerk"))
    assert client.get(url).status_code == 200
    content = client.get(reverse("admin:index")).content.decode()
    assert url in content  # sidebar link


def test_employee_role_can_manage_customers():
    employee = Group.objects.get(name=EMPLOYEE_ROLE)
    assert employee.permissions.filter(codename="manage_customers").exists()
