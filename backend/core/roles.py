"""Roles (Django groups) and helpers to give them permissions.

Roles are created by a data migration and can then be edited in the admin. Each stage
that defines new permissions adds a data migration that calls ``grant_permissions``
once, so later changes made by an admin are never undone.
"""

from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db.models import Q

ADMIN_ROLE = "Admin"
EMPLOYEE_ROLE = "Empleado"


def grant_permissions(apps, role_name, codes=(), app_labels=()) -> None:
    """Add permissions to a role from a data migration, creating the role if needed.

    ``codes`` are "app_label.codename" codes and ``app_labels`` adds every permission
    of those apps. Permissions are only added, never removed.
    """
    # Django creates permissions after migrate finishes; create them now so this
    # migration can use them.
    for app_config in global_apps.get_app_configs():
        create_permissions(app_config, apps=apps, verbosity=0)

    group_model = apps.get_model("auth", "Group")
    permission_model = apps.get_model("auth", "Permission")
    role, _ = group_model.objects.get_or_create(name=role_name)
    query = _codes_query(codes) | Q(content_type__app_label__in=app_labels)
    role.permissions.add(*permission_model.objects.filter(query))


def _codes_query(codes) -> Q:
    query = Q(pk__in=[])
    for code in codes:
        app_label, codename = code.split(".", 1)
        query |= Q(content_type__app_label=app_label, codename=codename)
    return query
