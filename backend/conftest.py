import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from core.models import Branch


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def branch(db):
    return Branch.objects.create(name="Matriz")


@pytest.fixture
def staff_with_perms(db):
    """Build a staff user that has only the given "app_label.codename" permissions."""

    def make(*codes, username="staff"):
        user = get_user_model().objects.create_user(username, password="pass-123", is_staff=True)

        for code in codes:
            app_label, codename = code.split(".", 1)
            user.user_permissions.add(
                Permission.objects.get(content_type__app_label=app_label, codename=codename),
            )

        return user

    return make
