from django.db import migrations

from core.roles import ADMIN_ROLE, grant_permissions


def grant_role_permissions(apps, schema_editor):
    """Admin gets every drop-off order permission, including delivering with a balance."""
    grant_permissions(apps, ADMIN_ROLE, app_labels=["sales"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_create_roles"),
        ("sales", "0014_drop_off_order"),
    ]

    operations = [migrations.RunPython(grant_role_permissions, migrations.RunPython.noop)]
