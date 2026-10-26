"""Tests for the shared API pieces: permission class, errors and pagination (plan Stage 12.1)."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings
from django.urls import path
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.serializers import ModelSerializer
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from core.api import HasPermission
from core.models import Branch

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]


class BranchSerializer(ModelSerializer):
    class Meta:
        model = Branch
        fields = ["name"]


class CreateBranchView(APIView):
    """Creates a branch; needs core.manage_users."""

    permission_classes = [HasPermission("core.manage_users")]

    def post(self, request):
        branch = Branch.objects.create(name=request.data["name"])

        return Response({"id": branch.pk}, status=201)


class FailingView(APIView):
    """Raises what a service raises, as given in ``?error=``."""

    def post(self, request):
        errors = {
            "field": ValidationError({"amount": "The amount must be greater than zero."}),
            "general": ValidationError("Open the cash session first."),
            "permission": PermissionDenied("You cannot charge sales."),
        }

        raise errors[request.query_params["error"]]


class BranchListView(ListAPIView):
    queryset = Branch.objects.order_by("pk")
    serializer_class = BranchSerializer


urlpatterns = [
    path("branches/", CreateBranchView.as_view()),
    path("failing/", FailingView.as_view()),
    path("branches/list/", BranchListView.as_view()),
]


def user_with(*codes):
    user = get_user_model().objects.create_user("employee")

    for code in codes:
        app_label, codename = code.split(".")
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename),
        )

    return user


def logged_in(api_client, user):
    """The client sends the user's JWT, as the POS does."""

    token = RefreshToken.for_user(user).access_token
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    return api_client


def test_user_without_the_permission_gets_403(api_client):
    client = logged_in(api_client, user_with())

    response = client.post("/branches/", {"name": "Norte"})

    assert response.status_code == 403
    assert not Branch.objects.filter(name="Norte").exists()


def test_user_with_the_permission_is_saved_as_created_by(api_client):
    user = user_with("core.manage_users")
    client = logged_in(api_client, user)

    response = client.post("/branches/", {"name": "Norte"})

    assert response.status_code == 201
    assert Branch.objects.get(pk=response.data["id"]).created_by == user


def test_request_without_token_gets_401(api_client):
    response = api_client.post("/branches/", {"name": "Norte"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("error", "status", "body"),
    [
        ("field", 400, {"amount": ["The amount must be greater than zero."]}),
        ("general", 400, {"non_field_errors": ["Open the cash session first."]}),
        ("permission", 403, {"detail": "You cannot charge sales."}),
    ],
)
def test_service_errors_become_api_responses(api_client, error, status, body):
    client = logged_in(api_client, user_with())

    response = client.post(f"/failing/?error={error}")

    assert response.status_code == status
    assert response.json() == body


@override_settings(API_PAGE_SIZE=2, API_MAX_PAGE_SIZE=3)
@pytest.mark.parametrize(("page_size", "expected"), [(None, 2), (3, 3), (10, 3)])
def test_lists_are_paginated_up_to_the_maximum(api_client, page_size, expected):
    Branch.objects.bulk_create([Branch(name=f"Branch {number}") for number in range(5)])
    client = logged_in(api_client, user_with())
    params = {"page_size": page_size} if page_size else {}

    response = client.get("/branches/list/", params)

    assert response.data["count"] == 5
    assert len(response.data["results"]) == expected
