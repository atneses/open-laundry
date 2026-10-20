"""Tests for the admin branding and sidebar (plan Stage 2)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse


@pytest.fixture
def staff_user():
    return get_user_model().objects.create_user(
        "employee", password="secure-pass-123", is_staff=True
    )


def test_login_page_has_branding_favicon(client):
    response = client.get(reverse("admin:login"))
    assert response.status_code == 200
    assert "favicon.svg" in response.content.decode()


@pytest.mark.django_db
def test_login_from_login_page_redirects_to_admin_index(client, staff_user):
    response = client.post(
        reverse("admin:login"), {"username": "employee", "password": "secure-pass-123"}
    )
    assert response.status_code == 302
    assert response.url == reverse("admin:index")


@pytest.mark.django_db
def test_superuser_sees_users_and_permissions_area(admin_client):
    content = admin_client.get(reverse("admin:index")).content.decode()
    assert reverse("admin:core_user_changelist") in content
    assert reverse("admin:auth_group_changelist") in content
    assert reverse("admin:core_branch_changelist") in content


@pytest.mark.django_db
def test_sidebar_only_shows_items_the_user_can_view(client, staff_user):
    staff_user.user_permissions.add(Permission.objects.get(codename="view_branch"))
    client.force_login(staff_user)

    content = client.get(reverse("admin:index")).content.decode()

    assert reverse("admin:core_branch_changelist") in content
    assert reverse("admin:core_user_changelist") not in content
    assert reverse("admin:auth_group_changelist") not in content
