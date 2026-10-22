"""Tests for BaseModel: who and when created and last changed each record."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Branch

pytestmark = pytest.mark.django_db


def test_admin_records_who_created_a_record(client, admin_user):
    client.force_login(admin_user)

    client.post(reverse("admin:core_branch_add"), {"name": "Matriz", "sale_prefix": "A"})

    branch = Branch.objects.get()
    assert branch.created_by == admin_user
    assert branch.updated_by == admin_user
    assert branch.created_at is not None


def test_admin_records_who_changed_a_record_and_keeps_its_creator(client, admin_user):
    branch = Branch.objects.create(name="Matriz", created_by=admin_user)
    editor = get_user_model().objects.create_superuser("editor", password="pass-123")
    client.force_login(editor)
    url = reverse("admin:core_branch_change", args=[branch.pk])

    client.post(url, {"name": "Centro", "sale_prefix": "A"})

    changed = Branch.objects.get()
    assert changed.created_by == admin_user
    assert changed.updated_by == editor
    assert changed.created_at == branch.created_at
    assert changed.updated_at > branch.created_at


def test_outside_a_request_the_user_stays_empty():
    branch = Branch.objects.create(name="Matriz")

    assert branch.created_by is None
    assert branch.updated_by is None


def test_a_given_creator_is_kept_and_copied_to_updated_by(admin_user):
    branch = Branch.objects.create(name="Matriz", created_by=admin_user)

    assert branch.updated_by == admin_user
