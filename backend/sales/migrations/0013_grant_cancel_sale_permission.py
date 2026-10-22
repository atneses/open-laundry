from django.db import migrations

from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE, grant_permissions


def grant_role_permissions(apps, schema_editor):
    """Admin and employees cancel sales (mvp §4)."""
    grant_permissions(apps, ADMIN_ROLE, codes=["sales.cancel_sale"])
    grant_permissions(apps, EMPLOYEE_ROLE, codes=["sales.cancel_sale"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_create_roles"),
        ("sales", "0012_sale_cancellation"),
    ]

    operations = [migrations.RunPython(grant_role_permissions, migrations.RunPython.noop)]
