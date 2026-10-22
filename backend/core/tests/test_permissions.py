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


@pytest.fixture
def user_form(employee):
    """POST data for the employee's admin form, with no extra permissions."""

    return {
        "username": employee.username,
        "is_active": "on",
        "is_staff": "on",
        "groups": [Group.objects.get(name=EMPLOYEE_ROLE).pk],
        "user_permissions": [],
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
    }


def test_manage_users_permission_exists():
    permission = perm("manage_users")

    assert permission.content_type.app_label == "core"


def test_admin_role_has_all_permissions():
    admin_role = Group.objects.get(name=ADMIN_ROLE)

    assert admin_role.permissions.count() == Permission.objects.count()


def test_employee_role_lacks_manage_users():
    employee_role = Group.objects.get(name=EMPLOYEE_ROLE)

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
    before = set(employee_role.permissions.values_list("codename", flat=True))

    grant_permissions(django_apps, EMPLOYEE_ROLE, codes=["core.view_permissionlog"])

    codenames = set(employee_role.permissions.values_list("codename", flat=True))
    assert codenames == before | {"view_permissionlog"}


def test_roles_admin_rejects_change_group_without_manage_users(client, employee):
    employee.user_permissions.add(perm("change_group"))
    client.force_login(employee)
    url = reverse("admin:auth_group_change", args=[Group.objects.get(name=EMPLOYEE_ROLE).pk])

    response = client.get(url)

    assert response.status_code == 403


def test_roles_admin_allows_manage_users(client, manager):
    client.force_login(manager)
    url = reverse("admin:auth_group_change", args=[Group.objects.get(name=EMPLOYEE_ROLE).pk])

    response = client.get(url)

    assert response.status_code == 200


def test_user_admin_rejects_without_manage_users(client, employee):
    client.force_login(employee)

    response = client.get(reverse("admin:core_user_changelist"))

    assert response.status_code == 403


def test_user_admin_allows_manage_users(client, manager):
    client.force_login(manager)

    response = client.get(reverse("admin:core_user_changelist"))

    assert response.status_code == 200


def test_granting_an_extra_permission_is_logged(client, manager, employee, user_form):
    client.force_login(manager)
    user_form["user_permissions"] = [perm("view_branch").pk]

    response = client.post(reverse("admin:core_user_change", args=[employee.pk]), user_form)

    assert response.status_code == 302, response.content
    granted = PermissionLog.objects.get(user=employee)
    assert granted.action == PermissionLog.Action.GRANTED
    assert granted.permission.codename == "view_branch"
    assert granted.created_by == manager


def test_revoking_an_extra_permission_is_logged(client, manager, employee, user_form):
    employee.user_permissions.add(perm("view_branch"))
    client.force_login(manager)

    client.post(reverse("admin:core_user_change", args=[employee.pk]), user_form)

    revoked = PermissionLog.objects.get(user=employee)
    assert revoked.action == PermissionLog.Action.REVOKED
    assert revoked.permission.codename == "view_branch"


def test_non_superuser_cannot_see_superuser_field(client, manager, employee):
    client.force_login(manager)

    response = client.get(reverse("admin:core_user_change", args=[employee.pk]))

    assert "is_superuser" not in response.context["adminform"].form.fields


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


@pytest.fixture
def permission_log(employee):
    return PermissionLog.objects.create(
        user=employee, permission=perm("view_branch"), action=PermissionLog.Action.GRANTED
    )


def test_permission_log_cannot_be_added(admin_client):
    response = admin_client.get(reverse("admin:core_permissionlog_add"))

    assert response.status_code == 403


def test_permission_log_cannot_be_deleted(admin_client, permission_log):
    url = reverse("admin:core_permissionlog_delete", args=[permission_log.pk])

    response = admin_client.get(url)

    assert response.status_code == 403


def test_permission_log_detail_has_no_save_button(admin_client, permission_log):
    url = reverse("admin:core_permissionlog_change", args=[permission_log.pk])

    response = admin_client.get(url)

    assert response.status_code == 200
    assert 'name="_save"' not in response.content.decode()
