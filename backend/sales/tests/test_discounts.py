"""Tests for discounts: which ones apply and how much they take off (plan Stage 7.4)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from inventory.models import Product
from sales.forms import DiscountForm
from sales.models import AppliedDiscount, Discount, Mode, Payment, Sale, Service, ServicePrice
from sales.services import (
    ItemRequest,
    add_payment,
    apply_discount,
    available_discounts,
    create_sale,
    open_cash_session,
)

pytestmark = pytest.mark.django_db

PERCENTAGE = Discount.Kind.PERCENTAGE
FIXED_AMOUNT = Discount.Kind.FIXED_AMOUNT


def employee(username, branch):
    """A user with the Employee role, which can charge sales and apply discounts."""

    user = get_user_model().objects.create_user(username, branch=branch)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def make_discount(branch, kind=PERCENTAGE, value=10, services=(), **fields):
    """A discount on the whole sale, or on ``services`` when given."""

    scope = Discount.Scope.SERVICE if services else Discount.Scope.SALE
    discount = Discount.objects.create(
        branch=branch,
        name=f"{value} off",
        kind=kind,
        value=value,
        scope=scope,
        **fields,
    )
    discount.services.set(services)

    return discount


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


@pytest.fixture
def sale(cashier, wash):
    """A self-service sale of 3 washes: $135.00, unpaid."""

    return create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(3, service=wash)])


@pytest.fixture
def mixed_sale(cashier, wash, branch):
    """3 washes ($135.00) and 2 bags ($10.00): $145.00."""

    bag = Product.objects.create(
        branch=branch,
        name="Bag",
        unit="piece",
        is_for_sale=True,
        sale_price=5,
        stock=10,
    )
    items = [ItemRequest(3, service=wash), ItemRequest(2, product=bag)]

    return create_sale(cashier, Mode.SELF_SERVICE, items)


def yesterday():
    return timezone.localdate() - timedelta(days=1)


def tomorrow():
    return timezone.localdate() + timedelta(days=1)


def test_an_active_discount_in_force_is_available(sale, branch):
    discount = make_discount(branch, valid_from=yesterday(), valid_until=tomorrow())

    assert list(available_discounts(sale)) == [discount]


@pytest.mark.parametrize(
    "fields",
    [
        {"valid_until": yesterday()},
        {"valid_from": tomorrow()},
        {"mode": Mode.DROP_OFF},
        {"is_active": False},
    ],
    ids=["expired", "not-started", "other-mode", "inactive"],
)
def test_a_discount_out_of_force_is_not_available(sale, branch, fields):
    make_discount(branch, **fields)

    assert not available_discounts(sale).exists()


@pytest.mark.parametrize(
    "fields",
    [{"valid_until": yesterday()}, {"mode": Mode.DROP_OFF}],
    ids=["expired", "other-mode"],
)
def test_a_discount_out_of_force_cannot_be_applied(cashier, sale, branch, fields):
    discount = make_discount(branch, **fields)

    with pytest.raises(ValidationError):
        apply_discount(cashier, sale, discount)

    sale.refresh_from_db()
    assert sale.total == Decimal("135.00")


def test_a_discount_of_another_branch_is_not_available(sale):
    make_discount(Branch.objects.create(name="Norte", sale_prefix="N"))

    assert not available_discounts(sale).exists()


def test_a_discount_for_services_not_in_the_sale_is_not_available(sale, branch):
    dry = Service.objects.create(name="Dry", kind="dry", machine_kind="dryer", uses_machine=True)
    make_discount(branch, services=[dry])

    assert not available_discounts(sale).exists()


def test_an_applied_discount_is_no_longer_available(cashier, sale, branch):
    discount = make_discount(branch)
    apply_discount(cashier, sale, discount)

    assert not available_discounts(sale).exists()


def test_a_discount_cannot_be_applied_twice(cashier, sale, branch):
    discount = make_discount(branch)
    apply_discount(cashier, sale, discount)

    with pytest.raises(ValidationError):
        apply_discount(cashier, sale, discount)

    assert AppliedDiscount.objects.count() == 1


def test_a_percentage_on_the_sale_lowers_total_and_balance(cashier, sale, branch):
    apply_discount(cashier, sale, make_discount(branch, value=10))

    sale.refresh_from_db()
    assert sale.discount_total == Decimal("13.50")
    assert sale.total == Decimal("121.50")
    assert sale.balance == Decimal("121.50")
    assert sale.status == Sale.Status.PENDING


def test_applied_discount_records_who_applied_it(cashier, sale, branch):
    [applied] = apply_discount(cashier, sale, make_discount(branch))

    assert applied.created_by == cashier
    assert applied.sale_item is None


def test_a_percentage_on_a_service_only_counts_its_lines(cashier, mixed_sale, branch, wash):
    apply_discount(cashier, mixed_sale, make_discount(branch, value=10, services=[wash]))

    mixed_sale.refresh_from_db()
    assert mixed_sale.discount_total == Decimal("13.50")
    assert mixed_sale.total == Decimal("131.50")


def test_a_fixed_amount_on_a_service_is_taken_once_per_line(cashier, sale, branch, wash):
    discount = make_discount(branch, kind=FIXED_AMOUNT, value=10, services=[wash])

    [applied] = apply_discount(cashier, sale, discount)

    assert applied.sale_item == sale.items.get()
    assert applied.amount == Decimal("10.00")


def test_different_discounts_add_up(cashier, sale, branch):
    apply_discount(cashier, sale, make_discount(branch, kind=FIXED_AMOUNT, value=20))

    apply_discount(cashier, sale, make_discount(branch, value=10))

    sale.refresh_from_db()
    assert sale.discount_total == Decimal("33.50")
    assert sale.total == Decimal("101.50")


def test_discounts_never_take_the_total_below_zero(cashier, sale, branch):
    apply_discount(cashier, sale, make_discount(branch, kind=FIXED_AMOUNT, value=100))

    apply_discount(cashier, sale, make_discount(branch, kind=FIXED_AMOUNT, value=99))

    sale.refresh_from_db()
    assert sale.discount_total == Decimal("135.00")
    assert sale.total == 0
    assert sale.status == Sale.Status.PAID


def test_a_discount_cannot_be_applied_after_a_payment(cashier, sale, branch):
    discount = make_discount(branch)
    add_payment(cashier, sale, Payment.Method.CASH, "50.00")

    with pytest.raises(ValidationError):
        apply_discount(cashier, sale, discount)

    assert not AppliedDiscount.objects.exists()


def test_applying_requires_the_apply_discount_permission(sale, branch):
    user = get_user_model().objects.create_user("noperm", branch=branch)

    with pytest.raises(PermissionDenied):
        apply_discount(user, sale, make_discount(branch))

    assert not AppliedDiscount.objects.exists()


def test_a_sale_of_another_branch_cannot_get_a_discount(sale, branch):
    other = employee("other", Branch.objects.create(name="Norte", sale_prefix="N"))

    with pytest.raises(PermissionDenied):
        apply_discount(other, sale, make_discount(branch))

    assert not AppliedDiscount.objects.exists()


def test_a_percentage_cannot_be_more_than_100(branch):
    discount = Discount(branch=branch, name="Free", kind=PERCENTAGE, value=101)

    with pytest.raises(ValidationError) as error:
        discount.full_clean()

    assert "value" in error.value.message_dict


def test_a_discount_cannot_end_before_it_starts(branch):
    discount = Discount(
        branch=branch,
        name="Week",
        kind=PERCENTAGE,
        value=10,
        valid_from=tomorrow(),
        valid_until=yesterday(),
    )

    with pytest.raises(ValidationError) as error:
        discount.full_clean()

    assert "valid_until" in error.value.message_dict


def test_a_discount_on_services_needs_its_services(branch):
    form = DiscountForm(
        data={
            "name": "Wash",
            "kind": PERCENTAGE,
            "value": "10",
            "scope": Discount.Scope.SERVICE,
            "branch": branch.pk,
            "is_active": "on",
        },
    )

    is_valid = form.is_valid()

    assert not is_valid
    assert "services" in form.errors


def test_employee_role_applies_but_does_not_manage_discounts():
    permissions = Group.objects.get(name=EMPLOYEE_ROLE).permissions

    assert permissions.filter(codename="apply_discount").exists()
    assert not permissions.filter(codename="manage_discounts").exists()


def test_admin_role_gets_the_discount_permissions():
    permissions = Group.objects.get(name=ADMIN_ROLE).permissions

    assert permissions.filter(codename="manage_discounts").exists()
    assert permissions.filter(codename="view_applieddiscount").exists()


def test_discounts_admin_rejects_without_manage_discounts(client, staff_with_perms):
    client.force_login(staff_with_perms("sales.apply_discount"))

    response = client.get(reverse("admin:sales_discount_changelist"))

    assert response.status_code == 403


def test_discounts_admin_lists_with_manage_discounts(client, staff_with_perms, branch):
    make_discount(branch, value=15)
    client.force_login(staff_with_perms("sales.manage_discounts"))

    response = client.get(reverse("admin:sales_discount_changelist"))

    assert "15 off" in response.content.decode()


def test_discounts_cannot_be_deleted_in_admin(admin_client, branch):
    discount = make_discount(branch)
    url = reverse("admin:sales_discount_delete", args=[discount.pk])

    response = admin_client.post(url, {"post": "yes"})

    assert response.status_code == 403
    assert Discount.objects.filter(pk=discount.pk).exists()


def test_sale_detail_shows_its_discounts_in_admin(admin_client, cashier, sale, branch):
    apply_discount(cashier, sale, make_discount(branch, value=15))

    response = admin_client.get(reverse("admin:sales_sale_change", args=[sale.pk]))

    assert "15 off" in response.content.decode()
