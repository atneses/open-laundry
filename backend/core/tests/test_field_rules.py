"""Tests for the field rules: names, codes, phones and amounts (letters in numbers)."""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from customers.models import Customer
from inventory.models import Product
from sales.models import Service, ServicePrice

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("name", ["Detergente 5 L", "Suavizante 1.5 L", "Bolsa-Grande"])
def test_name_accepts_letters_numbers_spaces_and_some_punctuation(branch, name):
    Product(branch=branch, name=name, unit="L").full_clean()


@pytest.mark.parametrize("name", ["Jabón!", "Jabón_B", "Jabón & Cloro", "Jabón#2"])
def test_name_rejects_symbols(branch, name):
    product = Product(branch=branch, name=name, unit="L")

    with pytest.raises(ValidationError) as error:
        product.full_clean()

    assert "name" in error.value.message_dict


@pytest.mark.parametrize("name", ["Ana López", "María-José Pérez", "O'Brien", "Ma. Luisa"])
def test_person_name_accepts_letters_spaces_and_some_punctuation(branch, name):
    Customer(branch=branch, name=name, phone="5512345678").full_clean()


@pytest.mark.parametrize("name", ["Ana 2", "Ana!", "Ana_B"])
def test_person_name_rejects_numbers_and_symbols(branch, name):
    customer = Customer(branch=branch, name=name, phone="5512345678")

    with pytest.raises(ValidationError) as error:
        customer.full_clean()

    assert "name" in error.value.message_dict


@pytest.mark.parametrize("phone", ["55 1234 5678", "55-1234-5678", "55abc"])
def test_phone_accepts_only_digits(branch, phone):
    customer = Customer(branch=branch, name="Ana", phone=phone)

    with pytest.raises(ValidationError) as error:
        customer.full_clean()

    assert "phone" in error.value.message_dict


def test_sku_accepts_letters_numbers_and_hyphens(branch):
    Product(branch=branch, name="Jabón", unit="L", sku="DET-500").full_clean()


@pytest.mark.parametrize("sku", ["DET 500", "DET_500", "DET#5"])
def test_sku_rejects_spaces_and_symbols(branch, sku):
    product = Product(branch=branch, name="Jabón", unit="L", sku=sku)

    with pytest.raises(ValidationError) as error:
        product.full_clean()

    assert "sku" in error.value.message_dict


@pytest.mark.parametrize("price", ["12a", "-1"])
def test_price_rejects_letters_and_negatives(branch, price):
    service = Service.objects.create(name="Lavado", kind=Service.Kind.WASH)
    service_price = ServicePrice(service=service, mode="self_service", price=price, branch=branch)

    with pytest.raises(ValidationError) as error:
        service_price.full_clean()

    assert "price" in error.value.message_dict


def test_product_amounts_reject_negatives(branch):
    product = Product(branch=branch, name="Jabón", unit="L", cost=-1, min_stock=-1, sale_price=-1)

    with pytest.raises(ValidationError) as error:
        product.full_clean()

    assert {"cost", "min_stock", "sale_price"} <= error.value.message_dict.keys()


def test_admin_rejects_letters_in_phone(admin_client, branch):
    data = {"branch": branch.pk, "name": "Ana", "phone": "55abc"}

    response = admin_client.post(reverse("admin:customers_customer_add"), data)

    assert response.status_code == 200
    assert not Customer.objects.exists()


def assert_page_loads_input_filters(content):
    assert "core/js/input_filters.js" in content

    # A number input would let Firefox accept letters out of the script's reach.
    assert 'type="number"' not in content


@pytest.mark.parametrize(
    ("url_name", "expected"),
    [
        ("admin:core_branch_add", ["name", "digits"]),
        ("admin:customers_customer_add", ["person-name", "digits"]),
        ("admin:inventory_product_add", ["name", "code", "decimal"]),
        ("admin:inventory_loadconsumption_add", ["decimal"]),
        ("admin:inventory_stockmovement_add", ["signed-decimal", "decimal"]),
        ("admin:sales_service_add", ["name", "decimal"]),
    ],
)
def test_admin_forms_mark_fields_with_their_input_filter(admin_client, url_name, expected):
    content = admin_client.get(reverse(url_name)).content.decode()

    assert_page_loads_input_filters(content)

    for input_filter in expected:
        assert f'data-input-filter="{input_filter}"' in content


def test_user_form_marks_names(admin_client):
    user = get_user_model().objects.create_user("ana")
    url = reverse("admin:core_user_change", args=[user.pk])

    content = admin_client.get(url).content.decode()

    assert_page_loads_input_filters(content)
    assert 'name="first_name"' in content
    assert 'data-input-filter="person-name"' in content
