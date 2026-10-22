from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Branch
from inventory.models import Product, StockMovement
from inventory.services import record_stock_movement

from .models import CashSession, Mode, Payment, Sale, SaleItem, Service, ServicePrice

OPERATE_CASH_SESSION = "sales.operate_cash_session"
VIEW_ALL_CASH_SESSIONS = "sales.view_all_cash_sessions"
CHARGE = "sales.charge"
CENTS = Decimal("0.01")


def open_cash_session(user, opening_float) -> CashSession:
    """Open a cash session for the user's branch, which must have none open."""

    if not user.has_perm(OPERATE_CASH_SESSION):
        raise PermissionDenied(_("You cannot open a cash session."))

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
            {"notes": _("Explain the difference between the counted and the expected cash.")}
        )

    session.closed_at = timezone.now()
    session.closed_by = user
    session.save()

    return session


def session_totals(session: CashSession) -> dict:
    """Cash and card payments, sales and cancellations of the session.

    Payments count in the session that received them, whatever session the sale is from.
    Cancellations arrive in Stage 7.5; until then there are none.
    """

    card = Q(method__in=[Payment.Method.CREDIT_CARD, Payment.Method.DEBIT_CARD])
    payments = session.payments.aggregate(
        cash=Sum("amount", filter=Q(method=Payment.Method.CASH), default=Decimal(0)),
        card=Sum("amount", filter=card, default=Decimal(0)),
    )
    sales = session.sales.aggregate(count=Count("pk"))["count"]

    return {**payments, "sales": sales, "cancellations": 0}


@dataclass
class ItemRequest:
    """A line to charge: a service or a product, and how many."""

    quantity: Decimal
    service: Service | None = None
    product: Product | None = None


@transaction.atomic
def create_sale(user, mode: str, items: list[ItemRequest], customer=None) -> Sale:
    """Charge a sale in the open cash session of the user's branch.

    Copies each price from the catalog and takes sold products out of stock. The sale
    starts unpaid; payments are added with ``add_payment``.
    """

    session = _charging_session(user)

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
                )
            )

    return sale


def _charging_session(user) -> CashSession:
    """Open cash session of the user's branch, if the user can charge."""

    if not user.has_perm(CHARGE):
        raise PermissionDenied(_("You cannot charge sales."))

    if user.branch_id is None:
        raise ValidationError(_("Your user has no branch assigned."))

    session = CashSession.objects.filter(branch_id=user.branch_id, closed_at__isnull=True).first()

    if session is None:
        raise ValidationError(_("Open the cash session before charging."))

    return session


@transaction.atomic
def add_payment(user, sale: Sale, method: str, amount, reference: str = "") -> Payment:
    """Record a payment of the sale in the open cash session and update its balance.

    A payment cannot be more than the balance; the change for cash is not recorded.
    """

    session = _charging_session(user)

    # Lock the sale so two payments at the same time cannot both use the same balance.
    sale = Sale.objects.select_for_update().get(pk=sale.pk)

    if sale.branch_id != user.branch_id:
        raise ValidationError(_("The sale belongs to another branch."))

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
                % {"product": product, "stock": product.stock.normalize()}
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
        service=service, mode=mode, branch_id=branch_id, is_active=True
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
                _("%(service)s has no price for this mode.") % {"service": item.service}
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
