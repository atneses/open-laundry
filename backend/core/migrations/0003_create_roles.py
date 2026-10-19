from django.db import migrations

from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE, grant_permissions


def create_roles(apps, schema_editor):
    """Create the roles once; after that they are managed in the admin."""
    grant_permissions(
        apps, ADMIN_ROLE, app_labels=["admin", "auth", "contenttypes", "sessions", "core"]
    )
    # The employee's default permissions are added by the stages that define them.
    grant_permissions(apps, EMPLOYEE_ROLE)


class Migration(migrations.Migration):
    dependencies = [
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("sessions", "0001_initial"),
        ("core", "0002_alter_branch_options_alter_user_options_and_more"),
    ]

    operations = [migrations.RunPython(create_roles, migrations.RunPython.noop)]
