"""Tests for roles, extra permissions and the permission log (plan Stage 3)."""

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.urls import reverse

from core.models import PermissionLog
from core.roles import ADMIN_ROLE, EMPLOYEE_ROLE, grant_permissions

pytestmark = pytest.mark.django_db


def perm(codename):
    return Permission.objects.get(codename=codename)


@pytest.fixture
def manager():
    """Staff user with the Admin role (not a superuser)."""
    user = get_user_model().objects.create_user("manager", password="pass-123", is_staff=True)
    user.groups.add(Group.objects.get(name=ADMIN_ROLE))
    return user


@pytest.fixture
def employee():
    user = get_user_model().objects.create_user("employee", password="pass-123", is_staff=True)
    user.groups.add(Group.objects.get(name=EMPLOYEE_ROLE))
    return user


def test_manage_users_permission_exists():
    assert perm("manage_users").content_type.app_label == "core"


def test_admin_role_has_all_permissions_and_employee_lacks_manage_users():
    admin_role = Group.objects.get(name=ADMIN_ROLE)
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE)
    assert admin_role.permissions.count() == Permission.objects.count()
    assert not employee_role.permissions.filter(codename="manage_users").exists()


def test_role_changes_survive_migrate():
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE)
    employee_role.permissions.add(perm("view_branch"))
    admin_role = Group.objects.get(name=ADMIN_ROLE)
    admin_role.permissions.remove(perm("delete_branch"))

    call_command("migrate", verbosity=0)

    assert employee_role.permissions.filter(codename="view_branch").exists()
    assert not admin_role.permissions.filter(codename="delete_branch").exists()


def test_grant_permissions_only_adds():
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE)
    employee_role.permissions.add(perm("view_branch"))

    grant_permissions(django_apps, EMPLOYEE_ROLE, codes=["core.view_permissionlog"])

    codenames = set(employee_role.permissions.values_list("codename", flat=True))
    assert codenames == {"view_branch", "view_permissionlog"}


def test_roles_admin_requires_manage_users(client, employee, manager):
    url = reverse("admin:auth_group_change", args=[Group.objects.get(name=EMPLOYEE_ROLE).pk])
    employee.user_permissions.add(perm("change_group"))
    client.force_login(employee)
    assert client.get(url).status_code == 403
    client.force_login(manager)
    assert client.get(url).status_code == 200


def test_user_admin_requires_manage_users(client, employee, manager):
    url = reverse("admin:core_user_changelist")
    client.force_login(employee)
    assert client.get(url).status_code == 403
    client.force_login(manager)
    assert client.get(url).status_code == 200


def test_granting_and_revoking_extra_permissions_is_logged(client, manager, employee):
    client.force_login(manager)
    url = reverse("admin:core_user_change", args=[employee.pk])
    data = {
        "username": employee.username,
        "is_active": "on",
        "is_staff": "on",
        "groups": [Group.objects.get(name=EMPLOYEE_ROLE).pk],
        "user_permissions": [perm("view_branch").pk],
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
    }
    response = client.post(url, data)
    assert response.status_code == 302, response.content

    granted = PermissionLog.objects.get(user=employee)
    assert granted.action == PermissionLog.Action.GRANTED
    assert granted.permission.codename == "view_branch"
    assert granted.performed_by == manager

    data["user_permissions"] = []
    client.post(url, data)
    revoked = PermissionLog.objects.filter(user=employee).first()
    assert revoked.action == PermissionLog.Action.REVOKED


def test_non_superuser_cannot_see_superuser_field(client, manager, employee):
    client.force_login(manager)
    form = (
        client.get(reverse("admin:core_user_change", args=[employee.pk])).context["adminform"].form
    )
    assert "is_superuser" not in form.fields


def test_non_superuser_cannot_edit_a_superuser(client, manager):
    root = get_user_model().objects.create_superuser("root", password="pass-123")
    client.force_login(manager)
    response = client.post(
        reverse("admin:core_user_change", args=[root.pk]), {"username": "hacked"}
    )
    assert response.status_code == 403


def test_users_cannot_be_deleted(admin_client, employee):
    response = admin_client.get(reverse("admin:core_user_delete", args=[employee.pk]))
    assert response.status_code == 403


def test_permission_log_is_read_only(admin_client, employee):
    log = PermissionLog.objects.create(
        user=employee, permission=perm("view_branch"), action=PermissionLog.Action.GRANTED
    )
    assert admin_client.get(reverse("admin:core_permissionlog_add")).status_code == 403
    assert (
        admin_client.get(reverse("admin:core_permissionlog_delete", args=[log.pk])).status_code
        == 403
    )
    change_page = admin_client.get(reverse("admin:core_permissionlog_change", args=[log.pk]))
    assert change_page.status_code == 200
    assert 'name="_save"' not in change_page.content.decode()
