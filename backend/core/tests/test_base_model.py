"""Tests for BaseModel: who and when created and last changed each record."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Branch

pytestmark = pytest.mark.django_db


def test_admin_records_who_created_and_who_changed(client, admin_user):
    client.force_login(admin_user)
    client.post(reverse("admin:core_branch_add"), {"name": "Matriz"})
    branch = Branch.objects.get()
    assert branch.created_by == admin_user
    assert branch.updated_by == admin_user
    assert branch.created_at is not None

    editor = get_user_model().objects.create_superuser("editor", password="pass-123")
    client.force_login(editor)
    created_at = branch.created_at
    client.post(reverse("admin:core_branch_change", args=[branch.pk]), {"name": "Centro"})
    branch.refresh_from_db()
    assert branch.created_by == admin_user
    assert branch.updated_by == editor
    assert branch.created_at == created_at
    assert branch.updated_at > created_at


def test_outside_a_request_the_user_stays_empty():
    branch = Branch.objects.create(name="Matriz")
    assert branch.created_by is None
    assert branch.updated_by is None


def test_a_given_creator_is_kept_and_copied_to_updated_by(admin_user):
    branch = Branch.objects.create(name="Matriz", created_by=admin_user)
    assert branch.updated_by == admin_user
