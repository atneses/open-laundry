from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import CashSession


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

    Sales and payments arrive in Stage 7; until then a session has none.
    """
    return {"cash": Decimal(0), "card": Decimal(0), "sales": 0, "cancellations": 0}
