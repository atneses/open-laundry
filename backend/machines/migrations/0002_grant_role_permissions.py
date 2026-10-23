from django.db import migrations

from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE, grant_permissions


def grant_role_permissions(apps, schema_editor):
    """Admin gets every machines permission; Employee can start machines."""
    grant_permissions(apps, ADMIN_ROLE, app_labels=["machines"])
    grant_permissions(apps, EMPLOYEE_ROLE, codes=["machines.start_machine"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_create_roles"),
        ("machines", "0001_initial"),
    ]

    operations = [migrations.RunPython(grant_role_permissions, migrations.RunPython.noop)]
