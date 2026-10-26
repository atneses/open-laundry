"""Tests for the receipt data of each kind of sale (plan Stage 10)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.translation import gettext

from core.models import Branch
from core.roles import EMPLOYEE_ROLE
from customers.models import Customer
from sales.models import Discount, DropOffOrder, Mode, Payment, Service, ServicePrice
from sales.receipts import Receipt, ReceiptDiscount, ReceiptLine, ReceiptPayment, build_receipt
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

CASH = Payment.Method.CASH
DEBIT_CARD = Payment.Method.DEBIT_CARD


def employee(username, branch, **fields):
    """A user with the Employee role, which can charge sales and print receipts."""

    user = get_user_model().objects.create_user(username, branch=branch, **fields)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))

    return user


def promotion_line():
    return ReceiptLine(
        quantity=None,
        description=gettext("Detergent and softener (promotion)"),
        unit_price=None,
        amount=Decimal("0.00"),
    )


@pytest.fixture
def cashier(branch):
    Branch.objects.filter(pk=branch.pk).update(address="Av. Juárez 10", phone="5512345678")
    user = employee("cashier", branch, first_name="Laura", last_name="Pérez")
    open_cash_session(user, 500)

    return user


@pytest.fixture
def customer(branch):
    return Customer.objects.create(branch=branch, name="Ana López", phone="5587654321")


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


@pytest.fixture
def dry(branch):
    service = Service.objects.create(
        name="Dry per load",
        kind="dry",
        machine_kind="dryer",
        uses_machine=True,
    )
    ServicePrice.objects.create(service=service, mode=Mode.SELF_SERVICE, price=40, branch=branch)
    ServicePrice.objects.create(service=service, mode=Mode.DROP_OFF, price=50, branch=branch)

    return service


def make_discount(branch, name, services=()):
    """A 10% discount on the whole sale, or on ``services`` when given."""

    scope = Discount.Scope.SERVICE if services else Discount.Scope.SALE
    discount = Discount.objects.create(
        branch=branch,
        name=name,
        kind=Discount.Kind.PERCENTAGE,
        value=10,
        scope=scope,
    )
    discount.services.set(services)

    return discount


def drop_off_sale(cashier, customer, items, promised_at=None):
    drop_off = DropOffRequest(promised_at or timezone.now() + timedelta(days=1))

    return create_sale(cashier, Mode.DROP_OFF, items, customer=customer, drop_off=drop_off)


def test_self_service_receipt(cashier, wash):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, service=wash)])
    add_payment(cashier, sale, DEBIT_CARD, "90.00", "VOUCHER-1")
    sale.refresh_from_db()

    receipt = build_receipt(cashier, sale)

    assert receipt == Receipt(
        branch_name="Matriz",
        branch_address="Av. Juárez 10",
        branch_phone="5512345678",
        number=sale.number,
        charged_at=sale.created_at,
        cashier="Laura Pérez",
        customer_name="",
        customer_phone="",
        mode=str(Mode.SELF_SERVICE.label),
        lines=[
            ReceiptLine(Decimal(2), "Wash per load", Decimal("45.00"), Decimal("90.00")),
            promotion_line(),
        ],
        subtotal=Decimal("90.00"),
        discounts=[],
        discount_total=Decimal("0.00"),
        total=Decimal("90.00"),
        payments=[
            ReceiptPayment(
                label=gettext("Payment"),
                method=str(DEBIT_CARD.label),
                amount=Decimal("90.00"),
                reference="VOUCHER-1",
                received=None,
                change=None,
            ),
        ],
        balance=Decimal("0.00"),
        promised_at=None,
        delivered_at=None,
        is_cancelled=False,
        cancel_reason="",
    )


def test_drop_off_receipt(cashier, customer, wash, dry, branch):
    promised_at = timezone.now() + timedelta(days=1)
    items = [ItemRequest(3, service=wash), ItemRequest(2, service=dry)]
    sale = drop_off_sale(cashier, customer, items, promised_at)
    apply_discount(cashier, sale, make_discount(branch, "Tuesday promo"))
    add_payment(cashier, sale, CASH, "100.00", received="200.00")
    sale.refresh_from_db()

    receipt = build_receipt(cashier, sale)

    assert receipt == Receipt(
        branch_name="Matriz",
        branch_address="Av. Juárez 10",
        branch_phone="5512345678",
        number=sale.number,
        charged_at=sale.created_at,
        cashier="Laura Pérez",
        customer_name="Ana López",
        customer_phone="5587654321",
        mode=str(Mode.DROP_OFF.label),
        lines=[
            ReceiptLine(Decimal(3), "Wash per load", Decimal("60.00"), Decimal("180.00")),
            ReceiptLine(Decimal(2), "Dry per load", Decimal("50.00"), Decimal("100.00")),
            promotion_line(),
        ],
        subtotal=Decimal("280.00"),
        discounts=[ReceiptDiscount("Tuesday promo", Decimal("28.00"))],
        discount_total=Decimal("28.00"),
        total=Decimal("252.00"),
        payments=[
            ReceiptPayment(
                label=gettext("Advance"),
                method=str(CASH.label),
                amount=Decimal("100.00"),
                reference="",
                received=Decimal("200.00"),
                change=Decimal("100.00"),
            ),
        ],
        balance=Decimal("152.00"),
        promised_at=promised_at,
        delivered_at=None,
        is_cancelled=False,
        cancel_reason="",
    )


def test_receipt_without_a_wash_has_no_promotion_line(cashier, dry):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=dry)])

    receipt = build_receipt(cashier, sale)

    assert [line.description for line in receipt.lines] == ["Dry per load"]


def test_drop_off_payment_that_leaves_a_balance_is_an_advance(cashier, customer, wash):
    sale = drop_off_sale(cashier, customer, [ItemRequest(2, service=wash)])
    add_payment(cashier, sale, CASH, "50.00")
    add_payment(cashier, sale, CASH, "70.00")

    receipt = build_receipt(cashier, sale)

    assert [payment.label for payment in receipt.payments] == [
        gettext("Advance"),
        gettext("Payment"),
    ]


def test_drop_off_paid_in_full_at_once_is_not_an_advance(cashier, customer, wash):
    sale = drop_off_sale(cashier, customer, [ItemRequest(2, service=wash)])
    add_payment(cashier, sale, CASH, "120.00")

    receipt = build_receipt(cashier, sale)

    assert [payment.label for payment in receipt.payments] == [gettext("Payment")]


def test_self_service_partial_payment_is_not_an_advance(cashier, wash):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, service=wash)])
    add_payment(cashier, sale, CASH, "50.00")

    receipt = build_receipt(cashier, sale)

    assert [payment.label for payment in receipt.payments] == [gettext("Payment")]


def test_delivered_drop_off_receipt_shows_when_it_was_delivered(cashier, customer, wash):
    sale = drop_off_sale(cashier, customer, [ItemRequest(1, service=wash)])
    delivered_at = timezone.now()
    DropOffOrder.objects.filter(sale=sale).update(
        status=DropOffOrder.Status.DELIVERED,
        delivered_at=delivered_at,
        delivered_by=cashier,
    )

    receipt = build_receipt(cashier, sale)

    assert receipt.delivered_at == delivered_at


def test_discount_on_services_adds_up_its_lines(cashier, wash, dry, branch):
    items = [ItemRequest(2, service=wash), ItemRequest(1, service=dry)]
    sale = create_sale(cashier, Mode.SELF_SERVICE, items)
    apply_discount(cashier, sale, make_discount(branch, "Loads promo", services=[wash, dry]))

    receipt = build_receipt(cashier, sale)

    assert receipt.discounts == [ReceiptDiscount("Loads promo", Decimal("13.00"))]


def test_each_discount_has_its_own_line(cashier, wash, branch):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(2, service=wash)])
    apply_discount(cashier, sale, make_discount(branch, "Tuesday promo"))
    apply_discount(cashier, sale, make_discount(branch, "Loyalty"))

    receipt = build_receipt(cashier, sale)

    assert [discount.name for discount in receipt.discounts] == ["Tuesday promo", "Loyalty"]


def test_cancelled_sale_receipt_is_marked_with_the_reason(cashier, wash):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    cancel_sale(cashier, sale, "Wrong service")

    receipt = build_receipt(cashier, sale)

    assert receipt.is_cancelled
    assert receipt.cancel_reason == "Wrong service"


def test_receipt_requires_the_charge_permission(cashier, wash, branch):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    user = get_user_model().objects.create_user("no-perms", branch=branch)

    with pytest.raises(PermissionDenied):
        build_receipt(user, sale)


def test_receipt_of_another_branch_is_denied(cashier, wash):
    sale = create_sale(cashier, Mode.SELF_SERVICE, [ItemRequest(1, service=wash)])
    other = employee("other", Branch.objects.create(name="Norte", sale_prefix="B"))

    with pytest.raises(PermissionDenied):
        build_receipt(other, sale)
