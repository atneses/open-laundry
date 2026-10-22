from django.db import migrations

from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE, grant_permissions


def grant_role_permissions(apps, schema_editor):
    """Admin gets every sale permission; employees charge sales (mvp §4)."""
    grant_permissions(apps, ADMIN_ROLE, app_labels=["sales"])
    grant_permissions(apps, EMPLOYEE_ROLE, codes=["sales.charge"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_create_roles"),
        ("sales", "0006_sale"),
    ]

    operations = [migrations.RunPython(grant_role_permissions, migrations.RunPython.noop)]
