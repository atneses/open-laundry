"""Load fictitious demo data for development: ``python manage.py seed_demo``.

It only creates what is missing, so it can be run again safely. It refuses to run
with DEBUG off, so it never touches a production database.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Branch
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE
from customers.models import Customer, normalize_phone
from inventory.models import LoadConsumption, Product, StockMovement
from inventory.services import record_stock_movement
from sales.models import Mode, Service, ServicePrice

DEMO_PASSWORD = "demo1234"  # noqa: S105 (fictitious development data)

USERS = [
    # username, first name, role, is_staff
    ("demo_admin", "Admin Demo", ADMIN_ROLE, True),
    ("demo_empleado", "Empleado Demo", EMPLOYEE_ROLE, False),
]

SERVICES = [
    # Each service: name, kind, unit, machine kind and its price per mode.
    ("Lavado por carga", "wash", "load", "washer", {Mode.SELF_SERVICE: 60, Mode.DROP_OFF: 75}),
    ("Secado por carga", "dry", "load", "dryer", {Mode.SELF_SERVICE: 55, Mode.DROP_OFF: 70}),
    ("Lavado de tenis", "other", "pair", "none", {Mode.DROP_OFF: 90}),
]

PRODUCTS = [
    # name, unit, cost, min_stock, sale_price (None = not for sale), initial stock
    ("Detergente", "ml", "0.05", 2000, None, 10000),
    ("Suavizante", "ml", "0.04", 2000, None, 10000),
    ("Bolsa", "unit", "1.50", 50, None, 200),
    ("Bolsa Grande", "unit", "1.50", 50, None, 200),
]

# service name -> {product name: quantity per load}
CONSUMPTION = {"Lavado por carga": {"Detergente": 180, "Suavizante": 150}}

# Add or edit demo customers here. Only "name" and "phone" are required; the phone
# identifies the customer, so a customer is created only if its phone is new.
CUSTOMERS = [
    {"name": "Ana López", "phone": "5512345678", "email": "ana@example.com"},
    {"name": "Luis Hernández", "phone": "5598765432", "notes": "Prefiere suavizante extra"},
    {"name": "María García", "phone": "5511112222", "address": "Av. Siempre Viva 742"},
]


class Command(BaseCommand):
    help = "Load fictitious demo data (branch, users, customers, catalog and stock)."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            msg = "Demo data is only for development (DEBUG must be on)."
            raise CommandError(msg)

        branch, _ = Branch.objects.get_or_create(
            name="Sucursal Demo",
            defaults={"address": "Calle Falsa 123", "phone": "5555555555"},
        )
        admin = self._create_users(branch)
        services = self._create_services(branch)
        products = self._create_products(branch, admin)

        for service_name, quantities in CONSUMPTION.items():
            for product_name, quantity in quantities.items():
                LoadConsumption.objects.get_or_create(
                    service=services[service_name],
                    product=products[product_name],
                    defaults={"quantity": quantity},
                )

        for data in CUSTOMERS:
            phone = normalize_phone(data["phone"])
            Customer.objects.get_or_create(
                branch=branch,
                phone=phone,
                defaults={**data, "phone": phone},
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready. Users {[u[0] for u in USERS]}, password '{DEMO_PASSWORD}'.",
            ),
        )

    def _create_users(self, branch):
        user_model = get_user_model()
        users = {}

        for username, first_name, role, is_staff in USERS:
            user, created = user_model.objects.get_or_create(
                username=username,
                defaults={"first_name": first_name, "branch": branch, "is_staff": is_staff},
            )

            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                user.groups.add(Group.objects.get(name=role))

            users[username] = user

        return users["demo_admin"]

    def _create_services(self, branch):
        services = {}

        for name, kind, unit, machine_kind, prices in SERVICES:
            service, _ = Service.objects.get_or_create(
                name=name,
                defaults={
                    "kind": kind,
                    "unit": unit,
                    "machine_kind": machine_kind,
                    "uses_machine": machine_kind != "none",
                },
            )

            for mode, price in prices.items():
                has_price = service.prices.filter(mode=mode, branch=branch, is_active=True)

                if not has_price.exists():
                    ServicePrice.objects.create(
                        service=service,
                        mode=mode,
                        price=price,
                        branch=branch,
                    )

            services[name] = service

        return services

    def _create_products(self, branch, user):
        products = {}

        for name, unit, cost, min_stock, sale_price, stock in PRODUCTS:
            product, created = Product.objects.get_or_create(
                name=name,
                branch=branch,
                defaults={
                    "unit": unit,
                    "cost": cost,
                    "min_stock": min_stock,
                    "is_for_sale": sale_price is not None,
                    "sale_price": sale_price,
                },
            )

            if created:
                # Initial stock goes through a purchase, like any stock change.
                record_stock_movement(
                    StockMovement(
                        product=product,
                        kind="purchase",
                        quantity=stock,
                        unit_cost=cost,
                        created_by=user,
                    ),
                )

            products[name] = product

        return products
