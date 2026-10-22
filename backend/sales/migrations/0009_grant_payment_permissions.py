from django.db import migrations

from core.roles import ADMIN_ROLE, grant_permissions


def grant_role_permissions(apps, schema_editor):
    """Admin gets the payment permissions, so it sees the payments of a sale (mvp §4)."""
    grant_permissions(apps, ADMIN_ROLE, app_labels=["sales"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_create_roles"),
        ("sales", "0008_payment"),
    ]

    operations = [migrations.RunPython(grant_role_permissions, migrations.RunPython.noop)]
