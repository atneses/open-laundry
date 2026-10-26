"""Admin home page: the reports dashboard for users with ``core.view_reports``."""

import json

from django.core.exceptions import ValidationError
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext as _

from .reports import VIEW_REPORTS, build_dashboard


def dashboard_callback(request, context):
    """Unfold's ``DASHBOARD_CALLBACK``; other users keep the default home page."""

    if not request.user.has_perm(VIEW_REPORTS):
        return context

    try:
        dashboard = build_dashboard(request.user)
    except ValidationError as error:
        context["dashboard_error"] = error.messages[0]

        return context

    context["dashboard"] = dashboard
    context["collected_cards"] = [
        {
            "title": _("Cash collected today"),
            "today": money(dashboard.collected_today.cash),
            "month": money(dashboard.collected_month.cash),
        },
        {
            "title": _("Card collected today"),
            "today": money(dashboard.collected_today.card),
            "month": money(dashboard.collected_month.card),
        },
    ]
    context["loads_chart"] = json.dumps(
        {
            "labels": [row.machine for row in dashboard.loads],
            "datasets": [
                {"label": _("Today"), "data": [row.today for row in dashboard.loads]},
                {"label": _("This month"), "data": [row.month for row in dashboard.loads]},
            ],
        },
    )
    context["low_stock_table"] = {
        "headers": [_("Product"), _("Stock"), _("Minimum")],
        "rows": [
            [product.name, product.stock.normalize(), product.min_stock.normalize()]
            for product in dashboard.low_stock
        ],
    }
    context["cash_differences_table"] = {
        "headers": [_("Closed at"), _("Cashier"), _("Difference"), _("Notes")],
        "rows": [
            [
                date_format(localtime(session.closed_at), "SHORT_DATETIME_FORMAT"),
                session.user,
                money(session.difference),
                session.notes,
            ]
            for session in dashboard.cash_differences
        ],
    }
    context["cancellations_table"] = _employee_table(
        dashboard.cancellations_today,
        dashboard.cancellations_month,
    )
    context["discounts_table"] = _employee_table(
        dashboard.discounts_today,
        dashboard.discounts_month,
    )

    return context


def money(amount) -> str:
    """Amount in pesos, e.g. "$1,234.50" or "-$20.00"."""

    sign = "-" if amount < 0 else ""

    return f"{sign}${abs(amount):,.2f}"


def _employee_table(today, month) -> dict:
    """One row per employee with their sales and amount today and in the month.

    Everyone with a total today also has one in the month, which includes today.
    """

    today_by_employee = {total.employee: total for total in today}
    rows = []

    for total in month:
        current = today_by_employee.get(total.employee)
        rows.append(
            [
                total.employee,
                current.count if current else 0,
                money(current.amount) if current else money(0),
                total.count,
                money(total.amount),
            ],
        )

    return {
        "headers": [
            _("Employee"),
            _("Sales today"),
            _("Amount today"),
            _("Sales this month"),
            _("Amount this month"),
        ],
        "rows": rows,
    }
