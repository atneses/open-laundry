from django.db import migrations

from core.roles import ADMIN_ROLE, grant_permissions


def grant_role_permissions(apps, schema_editor):
    """Admin gets every catalog permission; employees do not manage the catalog."""
    grant_permissions(apps, ADMIN_ROLE, app_labels=["sales"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_create_roles"),
        ("sales", "0001_initial"),
    ]

    operations = [migrations.RunPython(grant_role_permissions, migrations.RunPython.noop)]
