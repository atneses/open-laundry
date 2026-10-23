"""Fictitious operation history for ``seed_demo``: cash sessions, sales and cycles.

Everything goes through the real services, so the data follows the same rules as
the POS (stock, balances, cash counts, permissions). The services read the time
from ``timezone.now()``; ``Clock`` replaces it while the history is created, so the
records are spread over the past days.
"""

import random
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from inventory.models import StockMovement
from inventory.services import record_stock_movement
from machines.models import Machine, MachineCycle
from machines.services import finish_cycle, start_cycle
from sales.models import DropOffOrder, Mode, Payment
from sales.services import (
    DropOffRequest,
    ItemRequest,
    add_payment,
    advance_drop_off_order,
    apply_discount,
    available_discounts,
    cancel_sale,
    close_cash_session,
    create_sale,
    deliver_drop_off_order,
    open_cash_session,
    session_totals,
)

DAYS = 7
OPENING_FLOAT = Decimal(500)
DEFAULT_MINUTES = 40
DROP_OFF_NOTES = ["", "", "Sin suavizante", "Usar sus hojas aromatizantes en el secado"]
CARD_METHODS = [Payment.Method.DEBIT_CARD, Payment.Method.CREDIT_CARD]

# How often each thing happens (0 = never, 1 = always).
DROP_OFF_CHANCE = 0.3
CANCEL_CHANCE = 0.1
DISCOUNT_CHANCE = 0.25
CUSTOMER_SUPPLIES_CHANCE = 0.1
CASH_SHORT_CHANCE = 0.2
WAIT_A_DAY_CHANCE = 0.3
PICK_UP_LATER_CHANCE = 0.2
PAYS_BALANCE_CHANCE = 0.85


class Clock:
    """The time the services see while the history is created."""

    def __init__(self):
        self.moment = timezone.now()

    def now(self):
        return self.moment

    def advance(self, minutes):
        self.moment += timedelta(minutes=minutes)

    @contextmanager
    def running(self):
        """Make ``timezone.now()`` return this clock's time."""

        with mock.patch.object(timezone, "now", self.now):
            yield

    @contextmanager
    def at(self, moment):
        """Go to ``moment`` for one action, then come back."""

        current = self.moment
        self.moment = moment

        try:
            yield
        finally:
            self.moment = current


class DemoHistory:
    """Create the last ``DAYS`` days of operation of a branch, one cash session a day.

    Past days end with their cash session closed; today's stays open, with drop-off
    orders in every status and a machine still running.
    """

    def __init__(self, branch, admin, employee, services, products):
        self.branch = branch
        self.admin = admin
        self.employee = employee
        self.wash = services["Lavado por carga"]
        self.dry = services["Secado por carga"]
        self.products = products
        self.customers = list(branch.customers.all())
        self.machines = list(Machine.objects.filter(branch=branch))
        # Fixed seed: the same history every time the database is seeded.
        self.random = random.Random(2026)  # noqa: S311 (demo data, not security)
        self.clock = Clock()
        # machine pk -> (cycle, when it ends)
        self.running = {}
        self.orders = []

    def create(self) -> int:
        """Create the history and return how many days it has."""

        today = timezone.localdate()
        real_now = timezone.now()

        with self.clock.running():
            for offset in range(DAYS - 1, 0, -1):
                self._day(today - timedelta(days=offset), restock=offset == DAYS // 2)

            # Today started a few hours ago and is still going on.
            self.clock.moment = real_now - timedelta(hours=6)
            self._open_day(sales=4)

        return DAYS

    def _day(self, day, *, restock):
        self.clock.moment = timezone.make_aware(datetime.combine(day, time(8)))
        session = self._open_day(sales=self.random.randint(6, 9), restock=restock)
        closing = timezone.make_aware(datetime.combine(day, time(20)))
        self.clock.moment = max(self.clock.moment, closing)
        self._finish_all()
        counted = session.opening_float + session_totals(session)["cash"]
        notes = ""

        if self.random.random() < CASH_SHORT_CHANCE:
            counted -= 10
            notes = "Faltaron $10 de cambio."

        close_cash_session(session, self.employee, counted, notes)

    def _open_day(self, *, sales, restock=False):
        session = open_cash_session(self.employee, OPENING_FLOAT)

        if restock:
            self._restock()

        self._deliver_ready_orders()

        for _sale in range(sales):
            self.clock.advance(self.random.randint(20, 60))
            self._finish_due()

            if self.random.random() < DROP_OFF_CHANCE:
                self._drop_off_sale()
            else:
                self._self_service_sale()

        self._process_orders()

        return session

    def _restock(self):
        for name in ("Detergente", "Suavizante"):
            product = self.products[name]
            record_stock_movement(
                StockMovement(
                    product=product,
                    kind=StockMovement.Kind.PURCHASE,
                    quantity=10000,
                    unit_cost=product.cost,
                    created_by=self.admin,
                ),
            )

    def _self_service_sale(self):
        washes = self.random.randint(1, 3)
        items = [ItemRequest(washes, service=self.wash)]
        dries = self.random.randint(0, washes)

        if dries:
            items.append(ItemRequest(dries, service=self.dry))

        sale = create_sale(self.employee, Mode.SELF_SERVICE, items)

        if self.random.random() < CANCEL_CHANCE:
            cancel_sale(self.employee, sale, "Se cobró el servicio equivocado.")

            return

        self._maybe_discount(sale)
        self._pay(sale, self._balance(sale))

        for cycle in self._cycles(sale):
            self._start(cycle)

    def _drop_off_sale(self):
        loads = self.random.randint(1, 3)
        items = [ItemRequest(loads, service=self.wash), ItemRequest(loads, service=self.dry)]
        tomorrow = self.clock.moment.date() + timedelta(days=1)
        drop_off = DropOffRequest(
            promised_at=timezone.make_aware(datetime.combine(tomorrow, time(18))),
            notes=self.random.choice(DROP_OFF_NOTES),
        )
        sale = create_sale(
            self.employee,
            Mode.DROP_OFF,
            items,
            self.random.choice(self.customers),
            drop_off,
        )
        self._maybe_discount(sale)
        balance = self._balance(sale)
        # No deposit, half of it or everything up front.
        self._pay(sale, self.random.choice([0, (balance / 2).quantize(Decimal(1)), balance]))
        self.orders.append(sale.drop_off_order)

    def _maybe_discount(self, sale):
        discount = available_discounts(sale).first()

        if discount is not None and self.random.random() < DISCOUNT_CHANCE:
            apply_discount(self.employee, sale, discount)

    def _pay(self, sale, amount):
        if amount <= 0:
            return

        method = self.random.choice([Payment.Method.CASH] * 3 + CARD_METHODS)
        reference = str(self.random.randint(100000, 999999)) if method in CARD_METHODS else ""
        add_payment(self.employee, sale, method, amount, reference)

    def _balance(self, sale):
        sale.refresh_from_db()

        return sale.balance

    def _cycles(self, sale):
        return MachineCycle.objects.filter(
            sale_item__sale=sale,
            status=MachineCycle.Status.PENDING,
        ).select_related("sale_item__service")

    def _process_orders(self):
        """Start washing most of the received drop-off orders; the rest wait a day."""

        for order in self.orders:
            order.refresh_from_db()

            if order.status != DropOffOrder.Status.RECEIVED:
                continue

            if self.random.random() < WAIT_A_DAY_CHANCE:
                continue

            advance_drop_off_order(self.employee, order)

            for cycle in self._cycles(order.sale):
                self._start(cycle)

    def _deliver_ready_orders(self):
        """Get yesterday's washed orders ready and hand most of them back.

        Most customers pay their balance first.
        """

        for order in self.orders:
            order.refresh_from_db()

            if order.status == DropOffOrder.Status.IN_PROGRESS:
                self._finish_order_cycles(order)
                advance_drop_off_order(self.employee, order)
                order.refresh_from_db()

            # Some customers pick their clothes up another day.
            if order.status != DropOffOrder.Status.READY:
                continue

            if self.random.random() < PICK_UP_LATER_CHANCE:
                continue

            if self.random.random() < PAYS_BALANCE_CHANCE:
                self._pay(order.sale, self._balance(order.sale))
                deliver_drop_off_order(self.employee, order)
            else:
                # Only the admin can deliver an order that still owes money.
                deliver_drop_off_order(self.admin, order)

    def _finish_order_cycles(self, order):
        for machine_pk, (cycle, _end) in list(self.running.items()):
            if cycle.sale_item.sale_id == order.sale_id:
                self._finish(machine_pk)

    def _start(self, cycle):
        machine = self._free_machine(cycle.sale_item.service.machine_kind)
        supplies = self.random.random() < CUSTOMER_SUPPLIES_CHANCE
        started = start_cycle(self.employee, cycle, machine, customer_supplies=supplies)
        minutes = cycle.sale_item.service.expected_minutes or DEFAULT_MINUTES
        self.running[machine.pk] = (started, started.started_at + timedelta(minutes=minutes))

    def _free_machine(self, kind):
        """A machine of ``kind`` without a cycle; if all are busy, wait for the first."""

        machines = [machine for machine in self.machines if machine.kind == kind]

        for machine in machines:
            if machine.pk not in self.running:
                return machine

        machine_pk = min(
            (machine.pk for machine in machines),
            key=lambda pk: self.running[pk][1],
        )
        self.clock.moment = max(self.clock.moment, self.running[machine_pk][1])
        self._finish(machine_pk)

        return next(machine for machine in machines if machine.pk == machine_pk)

    def _finish_due(self):
        for machine_pk, (_cycle, end) in list(self.running.items()):
            if end <= self.clock.moment:
                self._finish(machine_pk)

    def _finish_all(self):
        for machine_pk in list(self.running):
            self._finish(machine_pk)

    def _finish(self, machine_pk):
        """Finish the cycle of a machine when it was due, not later."""

        cycle, end = self.running.pop(machine_pk)

        with self.clock.at(min(end, self.clock.moment)):
            finish_cycle(self.employee, cycle)
