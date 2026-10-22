from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Branch
from core.permissions import requires_perm
from inventory.models import Product, StockMovement
from inventory.services import record_stock_movement

from .models import (
    MAX_PERCENTAGE,
    AppliedDiscount,
    CashSession,
    Discount,
    Mode,
    Payment,
    Sale,
    SaleItem,
    Service,
    ServicePrice,
)

OPERATE_CASH_SESSION = "sales.operate_cash_session"
VIEW_ALL_CASH_SESSIONS = "sales.view_all_cash_sessions"
CHARGE = "sales.charge"
APPLY_DISCOUNT = "sales.apply_discount"
CANCEL_SALE = "sales.cancel_sale"
CENTS = Decimal("0.01")


@requires_perm(OPERATE_CASH_SESSION, message=_("You cannot open a cash session."))
def open_cash_session(user, opening_float) -> CashSession:
    """Open a cash session for the user's branch, which must have none open."""

    if user.branch_id is None:
        raise ValidationError(_("Your user has no branch assigned."))

    session = CashSession(branch_id=user.branch_id, user=user, opening_float=opening_float)
    session.full_clean(validate_constraints=False)
    already_open = ValidationError(_("This branch already has an open cash session."))

    if CashSession.objects.filter(branch_id=user.branch_id, closed_at__isnull=True).exists():
        raise already_open

    try:
        # The savepoint keeps the caller's transaction usable if the constraint fails.
        with transaction.atomic():
            session.save()
    except IntegrityError:
        # Another session was opened at the same time.
        raise already_open from None

    return session


@transaction.atomic
def close_cash_session(session: CashSession, user, counted_cash, notes: str = "") -> CashSession:
    """Close the session: compute the expected cash and the difference with the count.

    ``user`` is who closes it: the cashier, or a manager closing a forgotten session.
    """

    own = user.pk == session.user_id and user.has_perm(OPERATE_CASH_SESSION)

    if not own and not user.has_perm(VIEW_ALL_CASH_SESSIONS):
        raise PermissionDenied(_("You cannot close this cash session."))

    # Lock the row so two closes at the same time cannot both go through.
    session = CashSession.objects.select_for_update().get(pk=session.pk)

    if session.closed_at is not None:
        raise ValidationError(_("This cash session is already closed."))

    if counted_cash in (None, ""):
        raise ValidationError({"counted_cash": _("Enter the counted cash.")})

    totals = session_totals(session)
    session.expected_cash = session.opening_float + totals["cash"]
    session.card_total = totals["card"]
    session.sales_count = totals["sales"]
    session.cancellations_count = totals["cancellations"]
    session.counted_cash = counted_cash
    session.notes = notes.strip()
    session.full_clean(exclude=["difference"], validate_constraints=False)
    session.difference = session.counted_cash - session.expected_cash

    if session.difference and not session.notes:
        raise ValidationError(
            {"notes": _("Explain the difference between the counted and the expected cash.")},
        )

    session.closed_at = timezone.now()
    session.closed_by = user
    session.save()

    return session


def session_totals(session: CashSession) -> dict:
    """Cash and card payments, sales and cancellations of the session.

    Payments count in the session that received them, whatever session the sale is from.
    A cancelled sale gives its payments back in the session where it was cancelled.
    """

    cash = Q(method=Payment.Method.CASH)
    card = Q(method__in=[Payment.Method.CREDIT_CARD, Payment.Method.DEBIT_CARD])
    received = session.payments.aggregate(
        cash=Sum("amount", filter=cash, default=Decimal(0)),
        card=Sum("amount", filter=card, default=Decimal(0)),
    )
    returned = Payment.objects.filter(sale__cancel_cash_session=session).aggregate(
        cash=Sum("amount", filter=cash, default=Decimal(0)),
        card=Sum("amount", filter=card, default=Decimal(0)),
    )

    return {
        "cash": received["cash"] - returned["cash"],
        "card": received["card"] - returned["card"],
        "sales": session.sales.exclude(status=Sale.Status.CANCELLED).count(),
        "cancellations": session.cancelled_sales.count(),
    }


@dataclass
class ItemRequest:
    """A line to charge: a service or a product, and how many."""

    quantity: Decimal
    service: Service | None = None
    product: Product | None = None


@requires_perm(CHARGE, message=_("You cannot charge sales."))
@transaction.atomic
def create_sale(user, mode: str, items: list[ItemRequest], customer=None) -> Sale:
    """Charge a sale in the open cash session of the user's branch.

    Copies each price from the catalog and takes sold products out of stock. The sale
    starts unpaid; payments are added with ``add_payment``.
    """

    session = _open_session(user)

    if mode == Mode.DROP_OFF and customer is None:
        raise ValidationError({"customer": _("A drop-off sale needs a customer.")})

    if customer is not None and customer.branch_id != user.branch_id:
        raise ValidationError({"customer": _("The customer belongs to another branch.")})

    if not items:
        raise ValidationError(_("Add at least one service or product."))

    lines = [_sale_item(item, mode, user.branch_id) for item in items]
    _check_stock(lines)
    subtotal = sum((line.amount for line in lines), Decimal(0))
    sale = Sale.objects.create(
        number=next_sale_number(user.branch_id),
        branch_id=user.branch_id,
        cash_session=session,
        customer=customer,
        mode=mode,
        subtotal=subtotal,
        total=subtotal,
        balance=subtotal,
        created_by=user,
    )

    for line in lines:
        line.sale = sale
        # bulk_create skips BaseModel.save, so set the user here.
        line.created_by = line.updated_by = user

    SaleItem.objects.bulk_create(lines)

    for line in lines:
        if line.product is not None:
            record_stock_movement(
                StockMovement(
                    product=line.product,
                    kind=StockMovement.Kind.SALE,
                    quantity=-line.quantity,
                    sale=sale,
                    created_by=user,
                ),
            )

    return sale


def _open_session(user) -> CashSession:
    """Open cash session of the user's branch; charging and cancelling need one."""

    if user.branch_id is None:
        raise ValidationError(_("Your user has no branch assigned."))

    session = CashSession.objects.filter(branch_id=user.branch_id, closed_at__isnull=True).first()

    if session is None:
        raise ValidationError(_("Open the cash session first."))

    return session


def _lock_sale(user, sale: Sale) -> Sale:
    """Lock the sale until the transaction ends; it must be of the user's branch.

    Call inside a transaction, so two changes at the same time cannot both use the same
    total or balance.
    """

    sale = Sale.objects.select_for_update().get(pk=sale.pk)

    if sale.branch_id != user.branch_id:
        raise PermissionDenied(_("The sale belongs to another branch."))

    return sale


@requires_perm(CANCEL_SALE, message=_("You cannot cancel sales."))
@transaction.atomic
def cancel_sale(user, sale: Sale, reason: str) -> Sale:
    """Cancel a sale with a reason, in the open cash session of the user's branch.

    That session gives the payments back: its cash count subtracts them, even when
    they were received in an earlier session. Sold products go back to stock.
    """

    session = _open_session(user)
    sale = _lock_sale(user, sale)

    if sale.status == Sale.Status.CANCELLED:
        raise ValidationError(_("This sale is already cancelled."))

    reason = reason.strip()

    if not reason:
        raise ValidationError({"cancel_reason": _("Explain why the sale is cancelled.")})

    sale.status = Sale.Status.CANCELLED
    sale.cancelled_at = timezone.now()
    sale.cancelled_by = sale.updated_by = user
    sale.cancel_cash_session = session
    sale.cancel_reason = reason
    sale.save()

    for line in sale.items.filter(product__isnull=False).select_related("product"):
        record_stock_movement(
            StockMovement(
                product=line.product,
                kind=StockMovement.Kind.SALE_CANCELLATION,
                quantity=line.quantity,
                sale=sale,
                created_by=user,
            ),
        )

    return sale


@requires_perm(CHARGE, message=_("You cannot charge sales."))
@transaction.atomic
def add_payment(user, sale: Sale, method: str, amount, reference: str = "") -> Payment:
    """Record a payment of the sale in the open cash session and update its balance.

    A payment cannot be more than the balance; the change for cash is not recorded.
    """

    session = _open_session(user)
    sale = _lock_sale(user, sale)

    if sale.status == Sale.Status.CANCELLED:
        raise ValidationError(_("A cancelled sale cannot be paid."))

    payment = Payment(
        sale=sale,
        cash_session=session,
        method=method,
        amount=amount,
        reference=reference.strip(),
        created_by=user,
    )
    payment.full_clean(exclude=["sale", "cash_session"], validate_constraints=False)

    if payment.amount <= 0:
        raise ValidationError({"amount": _("The amount must be greater than zero.")})

    if payment.amount > sale.balance:
        message = _("The amount is more than the balance of %(balance)s.")

        raise ValidationError({"amount": message % {"balance": sale.balance}})

    payment.save()
    sale.balance -= payment.amount
    sale.status = Sale.Status.PAID if sale.balance == 0 else Sale.Status.PARTIALLY_PAID
    sale.updated_by = user
    sale.save(update_fields=["balance", "status", "updated_at", "updated_by"])

    return payment


def available_discounts(sale: Sale):
    """Discounts that can still be applied to the sale, as a queryset.

    Active, in force today, for the sale's branch and mode, not applied yet and, for a
    discount on services, with at least one of its services in the sale. Only a sale
    without payments takes discounts.
    """

    if sale.status != Sale.Status.PENDING:
        return Discount.objects.none()

    today = timezone.localdate()
    services = sale.items.filter(service__isnull=False).values("service_id")

    return (
        Discount.objects.filter(branch_id=sale.branch_id, is_active=True)
        .filter(Q(mode="") | Q(mode=sale.mode))
        .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .filter(
            Q(scope=Discount.Scope.SALE) | Q(scope=Discount.Scope.SERVICE, services__in=services),
        )
        .exclude(applied__sale=sale)
        .distinct()
    )


@requires_perm(APPLY_DISCOUNT, message=_("You cannot apply discounts."))
@transaction.atomic
def apply_discount(user, sale: Sale, discount: Discount) -> list[AppliedDiscount]:
    """Apply a discount of the catalog to a sale before its first payment.

    Several different discounts can be applied, but the total never goes below zero.
    """

    sale = _lock_sale(user, sale)

    if sale.status != Sale.Status.PENDING:
        raise ValidationError(_("Discounts are applied before the first payment."))

    discount = available_discounts(sale).filter(pk=discount.pk).first()

    if discount is None:
        raise ValidationError(_("This discount does not apply to this sale."))

    applied = _discount_rows(sale, discount)

    if not applied:
        raise ValidationError(_("This discount does not reduce the sale."))

    for row in applied:
        # bulk_create skips BaseModel.save, so set the user here.
        row.created_by = row.updated_by = user

    AppliedDiscount.objects.bulk_create(applied)
    sale.discount_total += sum(row.amount for row in applied)
    sale.total = sale.subtotal - sale.discount_total
    sale.balance = sale.total
    sale.status = Sale.Status.PAID if sale.total == 0 else Sale.Status.PENDING
    sale.updated_by = user
    sale.save(
        update_fields=["discount_total", "total", "balance", "status", "updated_at", "updated_by"],
    )

    return applied


def _discount_rows(sale: Sale, discount: Discount) -> list[AppliedDiscount]:
    """Rows of the discount for the sale, never taking more than what is left to pay."""

    left = sale.total

    if discount.scope == Discount.Scope.SALE:
        amount = min(_discount_amount(discount, sale.subtotal), left)

        return [AppliedDiscount(sale=sale, discount=discount, amount=amount)] if amount else []

    rows = []
    lines = sale.items.filter(service__in=discount.services.all()).annotate(
        discounted=Sum("applied_discounts__amount", default=Decimal(0)),
    )

    for line in lines.order_by("pk"):
        amount = min(_discount_amount(discount, line.amount), line.amount - line.discounted, left)

        if amount > 0:
            rows.append(
                AppliedDiscount(sale=sale, sale_item=line, discount=discount, amount=amount),
            )
            left -= amount

    return rows


def _discount_amount(discount: Discount, base: Decimal) -> Decimal:
    """Amount a discount takes from a base amount, before any limit."""

    if discount.kind == Discount.Kind.PERCENTAGE:
        return (base * discount.value / MAX_PERCENTAGE).quantize(CENTS)

    return discount.value


def _check_stock(lines: list[SaleItem]) -> None:
    """Reject the sale if a product does not have enough stock for its lines.

    The product rows stay locked until the sale is saved, so two sales at the same
    time cannot sell the same last units.
    """

    wanted = defaultdict(Decimal)

    for line in lines:
        if line.product is not None:
            wanted[line.product_id] += line.quantity

    products = Product.objects.select_for_update().filter(pk__in=wanted).order_by("pk")

    for product in products:
        if product.stock < wanted[product.pk]:
            raise ValidationError(
                _("Not enough %(product)s in stock: %(stock)s left.")
                % {"product": product, "stock": product.stock.normalize()},
            )


def next_sale_number(branch_id) -> str:
    """Next sale number of the branch, e.g. "A-000124". Call inside a transaction.

    The branch row stays locked until the transaction ends, so numbers have no gaps
    or repeats even when two sales are charged at the same time.
    """

    branch = Branch.objects.select_for_update().get(pk=branch_id)
    branch.last_sale_number += 1
    branch.save(update_fields=["last_sale_number"])

    return f"{branch.sale_prefix}-{branch.last_sale_number:06d}"


def active_price(service: Service, mode: str, branch_id, program: str = "") -> ServicePrice | None:
    """Active price of a service for a mode; a program without its own uses the general one."""

    prices = ServicePrice.objects.filter(
        service=service,
        mode=mode,
        branch_id=branch_id,
        is_active=True,
    )

    return prices.filter(program=program).first() or (
        prices.filter(program="").first() if program else None
    )


def _sale_item(item: ItemRequest, mode: str, branch_id) -> SaleItem:
    """Build a sale line with the current catalog price."""

    quantity = Decimal(item.quantity)

    if quantity <= 0:
        raise ValidationError({"quantity": _("The quantity must be greater than zero.")})

    if (item.service is None) == (item.product is None):
        raise ValidationError(_("Each line is either a service or a product."))

    if item.service is not None:
        if not item.service.is_active:
            raise ValidationError(_("%(service)s is not active.") % {"service": item.service})

        # Services are sold by whole loads, pieces or pairs.
        if quantity != quantity.to_integral_value():
            raise ValidationError({"quantity": _("Services are sold in whole units.")})

        price = active_price(item.service, mode, branch_id)

        if price is None:
            raise ValidationError(
                _("%(service)s has no price for this mode.") % {"service": item.service},
            )

        unit_price = price.price
    else:
        if not item.product.is_for_sale or item.product.branch_id != branch_id:
            raise ValidationError(_("%(product)s is not for sale.") % {"product": item.product})

        unit_price = item.product.sale_price

    return SaleItem(
        service=item.service,
        product=item.product,
        quantity=quantity,
        unit_price=unit_price,
        amount=(quantity * unit_price).quantize(CENTS),
    )
