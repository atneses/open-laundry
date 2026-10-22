"""Tests for the project foundation (plan Stage 1)."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.translation import gettext

from core.models import Branch, User


def test_health_is_public(api_client):
    response = api_client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_custom_user_model():
    assert get_user_model() is User


@pytest.mark.django_db
def test_user_belongs_to_branch():
    branch = Branch.objects.create(name="Matriz")

    user = get_user_model().objects.create_user("ana", password="secure-pass-123", branch=branch)

    assert user.branch == branch
    assert branch.users.count() == 1


@pytest.mark.django_db
def test_jwt_token(api_client):
    get_user_model().objects.create_user("ana", password="secure-pass-123")
    credentials = {"username": "ana", "password": "secure-pass-123"}

    response = api_client.post(reverse("token_obtain_pair"), credentials)

    assert response.status_code == 200
    assert {"access", "refresh"} <= response.json().keys()


def test_api_requires_authentication_by_default(settings):
    # Every new endpoint requires a token unless stated otherwise.
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]


def test_openapi_schema_is_public_in_development(api_client):
    response = api_client.get(reverse("schema"))

    # Public in development so the frontend can generate its types.
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_login_page_is_in_spanish(client):
    response = client.get("/admin/login/")

    assert response.status_code == 200
    assert "Iniciar sesión" in response.content.decode()


def test_root_redirects_to_admin(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.url == reverse("admin:index")


@pytest.mark.parametrize(
    ("text", "spanish"),
    [("Users and permissions", "Usuarios y permisos"), ("Select action", "Seleccionar acción")],
)
def test_project_and_unfold_strings_are_translated(text, spanish):
    # One string from locale/ (project) and one from locale_unfold/ (Unfold).
    assert gettext(text) == spanish
