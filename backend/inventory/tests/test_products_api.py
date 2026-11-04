"""Tests for the products API: what the POS can sell (plan Stage 12.3)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from inventory.models import Product

pytestmark = pytest.mark.django_db

URL = "/api/products/"


def product(name, branch, **fields):
    return Product.objects.create(name=name, unit="piece", branch=branch, **fields)


def test_products_for_sale_of_the_branch_with_their_stock(branch):
    user = get_user_model().objects.create_user("cashier", branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    client = APIClient()
    client.force_authenticate(user)
    detergent = product("Detergent", branch, is_for_sale=True, sale_price=25, stock=10)
    product("Softener for the loads", branch)
    other = Branch.objects.create(name="Norte", sale_prefix="B")
    product("Bleach", other, is_for_sale=True, sale_price=20)

    response = client.get(URL)

    assert response.data["results"] == [
        {
            "id": detergent.pk,
            "name": "Detergent",
            "unit": "piece",
            "sale_price": "25.00",
            "stock": "10.000",
        },
    ]


def test_products_without_the_permission_are_forbidden(branch):
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user("guest", branch=branch))

    response = client.get(URL)

    assert response.status_code == 403
