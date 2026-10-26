"""Dashboard indicators of a branch, for today and the month so far (plan Stage 11.1)."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Count, F, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.permissions import requires_perm
from inventory.models import Product
from machines.models import Machine, MachineCycle
from sales.models import AppliedDiscount, CashSession, DropOffOrder, Payment, Sale

VIEW_REPORTS = "core.view_reports"
# A load counts once its machine started, unless the cycle failed.
STARTED = [MachineCycle.Status.RUNNING, MachineCycle.Status.FINISHED]


@dataclass
class Period:
    """First moment of the period and first moment after it."""

    start: datetime
    end: datetime


@dataclass
class Money:
    """Money collected in a period: payments minus what cancellations gave back."""

    cash: Decimal
    card: Decimal


@dataclass
class MachineLoads:
    machine: str
    today: int
    month: int


@dataclass
class EmployeeTotal:
    """How many times an employee did something and for how much."""

    employee: str
    count: int
    amount: Decimal


@dataclass
class Dashboard:
    """Indicators for today and the month; drop-off orders and stock are as of now."""

    collected_today: Money
    collected_month: Money
    loads: list[MachineLoads]
    pending_orders: int
    ready_orders: int
    low_stock: list[Product]
    cash_differences: list[CashSession]
    cancellations_today: list[EmployeeTotal]
    cancellations_month: list[EmployeeTotal]
    discounts_today: list[EmployeeTotal]
    discounts_month: list[EmployeeTotal]


@requires_perm(VIEW_REPORTS, message=_("You cannot view reports."))
def build_dashboard(user, day: date | None = None) -> Dashboard:
    """Indicators of the user's branch for ``day`` (today by default) and its month."""

    if user.branch_id is None:
        raise ValidationError(_("Your user has no branch assigned."))

    day = day or timezone.localdate()
    today = Period(_start_of(day), _start_of(day + timedelta(days=1)))
    month = Period(_start_of(day.replace(day=1)), today.end)
    branch_id = user.branch_id
    orders = DropOffOrder.objects.filter(sale__branch_id=branch_id).exclude(
        sale__status=Sale.Status.CANCELLED,
    )

    return Dashboard(
        collected_today=_collected(branch_id, today),
        collected_month=_collected(branch_id, month),
        loads=_loads(branch_id, today, month),
        pending_orders=orders.filter(
            status__in=[DropOffOrder.Status.RECEIVED, DropOffOrder.Status.IN_PROGRESS],
        ).count(),
        ready_orders=orders.filter(status=DropOffOrder.Status.READY).count(),
        # Same rule as the "low stock" filter of the products admin.
        low_stock=list(
            Product.objects.filter(branch_id=branch_id, stock__lt=F("min_stock")).order_by("name"),
        ),
        cash_differences=list(
            CashSession.objects.filter(branch_id=branch_id, **_within("closed_at", month))
            .exclude(difference=0)
            .select_related("user")
            .order_by("-closed_at"),
        ),
        cancellations_today=_cancellations(branch_id, today),
        cancellations_month=_cancellations(branch_id, month),
        discounts_today=_discounts(branch_id, today),
        discounts_month=_discounts(branch_id, month),
    )


def _start_of(day: date) -> datetime:
    """Midnight of the day in the local time zone."""

    return timezone.make_aware(datetime.combine(day, time.min))


def _within(field: str, period: Period) -> dict:
    """Filter arguments for a date and time field inside the period."""

    return {f"{field}__gte": period.start, f"{field}__lt": period.end}


def _collected(branch_id, period: Period) -> Money:
    """Cash and card received in the period minus what its cancellations gave back."""

    cash = Q(method=Payment.Method.CASH)
    card = Q(method__in=[Payment.Method.CREDIT_CARD, Payment.Method.DEBIT_CARD])
    totals = {
        "cash": Sum("amount", filter=cash, default=Decimal(0)),
        "card": Sum("amount", filter=card, default=Decimal(0)),
    }
    payments = Payment.objects.filter(sale__branch_id=branch_id)
    received = payments.filter(**_within("created_at", period)).aggregate(**totals)
    returned = payments.filter(**_within("sale__cancelled_at", period)).aggregate(**totals)

    return Money(
        cash=received["cash"] - returned["cash"],
        card=received["card"] - returned["card"],
    )


def _loads(branch_id, today: Period, month: Period) -> list[MachineLoads]:
    """Loads started on each machine of the branch, including machines without any."""

    def started_in(period: Period):
        return Q(
            cycles__status__in=STARTED,
            cycles__started_at__gte=period.start,
            cycles__started_at__lt=period.end,
        )

    machines = (
        Machine.objects.filter(branch_id=branch_id)
        .annotate(
            today=Count("cycles", filter=started_in(today)),
            month=Count("cycles", filter=started_in(month)),
        )
        # Washers first, then dryers.
        .order_by("-kind", "label")
    )

    return [MachineLoads(str(machine), machine.today, machine.month) for machine in machines]


def _cancellations(branch_id, period: Period) -> list[EmployeeTotal]:
    """Sales cancelled in the period by each employee, with their totals."""

    rows = (
        Sale.objects.filter(
            branch_id=branch_id,
            status=Sale.Status.CANCELLED,
            **_within("cancelled_at", period),
        )
        .values("cancelled_by")
        .annotate(count=Count("pk"), amount=Sum("total"))
    )

    return _by_employee(rows, "cancelled_by")


def _discounts(branch_id, period: Period) -> list[EmployeeTotal]:
    """Sales each employee applied discounts to in the period, and the amount taken off."""

    rows = (
        AppliedDiscount.objects.filter(sale__branch_id=branch_id, **_within("created_at", period))
        .values("created_by")
        .annotate(count=Count("sale", distinct=True), amount=Sum("amount"))
    )

    return _by_employee(rows, "created_by")


def _by_employee(rows, user_field: str) -> list[EmployeeTotal]:
    """Totals with the employee's name, the highest amount first."""

    rows = list(rows)
    users = get_user_model().objects.in_bulk([row[user_field] for row in rows])
    totals = [
        EmployeeTotal(
            employee=_name(users[row[user_field]]),
            count=row["count"],
            amount=row["amount"],
        )
        for row in rows
    ]

    return sorted(totals, key=lambda total: (-total.amount, total.employee))


def _name(user) -> str:
    return user.get_full_name() or user.get_username()
