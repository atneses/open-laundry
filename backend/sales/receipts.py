"""Receipt data: what the customer's ticket shows, already calculated (plan Stage 10).

The receipt is plain data; the POS formats it for the 80 mm printer, and it can be
reused for WhatsApp or PDF.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from core.permissions import requires_perm

from .models import DropOffOrder, Mode, Sale, Service
from .services import CHARGE

if TYPE_CHECKING:
    from datetime import datetime


@dataclass
class ReceiptLine:
    """A line of the receipt; the promotion line has no quantity or unit price."""

    quantity: Decimal | None
    description: str
    unit_price: Decimal | None
    amount: Decimal


@dataclass
class ReceiptDiscount:
    """A discount of the catalog and the total it took off the sale."""

    name: str
    amount: Decimal


@dataclass
class ReceiptPayment:
    """A payment; ``received`` and ``change`` only when cash recorded what was handed over."""

    label: str
    method: str
    amount: Decimal
    reference: str
    received: Decimal | None
    change: Decimal | None


@dataclass
class Receipt:
    """Everything the customer's ticket shows, with the texts in the active language."""

    branch_name: str
    branch_address: str
    branch_phone: str
    number: str
    charged_at: datetime
    cashier: str
    customer_name: str
    customer_phone: str
    mode: str
    lines: list[ReceiptLine]
    subtotal: Decimal
    discounts: list[ReceiptDiscount]
    discount_total: Decimal
    total: Decimal
    payments: list[ReceiptPayment]
    balance: Decimal
    promised_at: datetime | None
    delivered_at: datetime | None
    is_cancelled: bool
    cancel_reason: str


@requires_perm(CHARGE, message=_("You cannot print receipts."))
def build_receipt(user, sale: Sale) -> Receipt:
    """Receipt of a sale of the user's branch; a cancelled sale is marked as such."""

    sale = (
        Sale.objects.select_related("branch", "customer", "created_by", "drop_off_order")
        .prefetch_related(
            "items__service",
            "items__product",
            "applied_discounts__discount",
            "payments",
        )
        .get(pk=sale.pk)
    )

    if sale.branch_id != user.branch_id:
        raise PermissionDenied(_("The sale belongs to another branch."))

    order: DropOffOrder | None = getattr(sale, "drop_off_order", None)

    return Receipt(
        branch_name=sale.branch.name,
        branch_address=sale.branch.address,
        branch_phone=sale.branch.phone,
        number=sale.number,
        charged_at=sale.created_at,
        cashier=sale.created_by.get_display_name(),
        customer_name=sale.customer.name if sale.customer else "",
        customer_phone=sale.customer.phone if sale.customer else "",
        mode=sale.get_mode_display(),
        lines=_lines(sale),
        subtotal=sale.subtotal,
        discounts=_discounts(sale),
        discount_total=sale.discount_total,
        total=sale.total,
        payments=_payments(sale),
        balance=sale.balance,
        promised_at=order.promised_at if order else None,
        delivered_at=order.delivered_at if order else None,
        is_cancelled=sale.status == Sale.Status.CANCELLED,
        cancel_reason=sale.cancel_reason,
    )


def _lines(sale: Sale) -> list[ReceiptLine]:
    """Sale lines, plus the free detergent and softener whenever there is a wash."""

    items = sorted(sale.items.all(), key=lambda item: item.pk)
    lines = [
        ReceiptLine(
            quantity=item.quantity,
            description=str(item.service or item.product),
            unit_price=item.unit_price,
            amount=item.amount,
        )
        for item in items
    ]

    # Shown even when the customer brought their own (customer_supplies is internal).
    if any(item.service and item.service.kind == Service.Kind.WASH for item in items):
        lines.append(
            ReceiptLine(
                quantity=None,
                description=gettext("Detergent and softener (promotion)"),
                unit_price=None,
                amount=Decimal("0.00"),
            ),
        )

    return lines


def _discounts(sale: Sale) -> list[ReceiptDiscount]:
    """One entry per discount; a discount on services adds up its lines."""

    discounts = {}

    for row in sorted(sale.applied_discounts.all(), key=lambda row: row.pk):
        entry = discounts.setdefault(
            row.discount_id,
            ReceiptDiscount(row.discount.name, Decimal(0)),
        )
        entry.amount += row.amount

    return list(discounts.values())


def _payments(sale: Sale) -> list[ReceiptPayment]:
    """Payments in order. In a drop-off, one that leaves a balance is an advance."""

    payments = []
    left = sale.total

    # Payment.Meta.ordering keeps them in the order they were received.
    for payment in sale.payments.all():
        left -= payment.amount
        is_advance = sale.mode == Mode.DROP_OFF and left > 0
        received = payment.received
        payments.append(
            ReceiptPayment(
                label=gettext("Advance") if is_advance else gettext("Payment"),
                method=payment.get_method_display(),
                amount=payment.amount,
                reference=payment.reference,
                received=received,
                change=received - payment.amount if received is not None else None,
            ),
        )

    return payments
