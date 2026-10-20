from django.db import migrations

from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE, grant_permissions


def grant_role_permissions(apps, schema_editor):
    """Admin gets every inventory permission; employees can record stock entries (mvp §4)."""
    grant_permissions(apps, ADMIN_ROLE, app_labels=["inventory"])
    grant_permissions(apps, EMPLOYEE_ROLE, codes=["inventory.receive_stock"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_create_roles"),
        ("inventory", "0002_initial"),
    ]

    operations = [migrations.RunPython(grant_role_permissions, migrations.RunPython.noop)]
