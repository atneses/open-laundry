"""Pieces shared by the REST API of every app: permissions, errors and pagination."""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import pagination
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler as drf_exception_handler


class HasPermission(BasePermission):
    """Require every "app_label.codename" in ``codes``, e.g. ``HasPermission("sales.charge")``.

    Goes in ``permission_classes`` like a class. The services check the same
    permissions; this answers 403 before calling them. Use the service's
    ``required_perms`` to keep both in sync: ``HasPermission(*create_sale.required_perms)``.
    """

    message = _("You do not have permission to do this.")

    def __init__(self, *codes):
        self.codes = codes

    def __call__(self):
        # DRF instantiates each permission class; an instance stands in for its class.
        return self

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_perms(self.codes)


def exception_handler(exc, context):
    """DRF's handler, plus the ``ValidationError`` of the services as a 400 by field."""

    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(as_serializer_error(exc))

    return drf_exception_handler(exc, context)


class PageNumberPagination(pagination.PageNumberPagination):
    """Pages of ``API_PAGE_SIZE``; the client may ask for ``?page_size=`` up to the maximum."""

    page_size_query_param = "page_size"

    @property
    def page_size(self):
        return settings.API_PAGE_SIZE

    @property
    def max_page_size(self):
        return settings.API_MAX_PAGE_SIZE
