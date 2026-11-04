"""Pieces shared by the REST API of every app: permissions, errors, pagination and retries."""

import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import pagination, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.serializers import as_serializer_error
from rest_framework.views import exception_handler as drf_exception_handler

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models import Model, QuerySet
    from rest_framework.request import Request


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


IDEMPOTENCY_HEADER = "Idempotency-Key"


class IdempotencyConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _("This Idempotency-Key was already used for a different request.")
    default_code = "idempotency_conflict"


def run_once[M: Model](
    request: Request,
    previous_results: QuerySet[M],
    create: Callable[[], M],
) -> M:
    """Run ``create`` once per ``Idempotency-Key`` header, so a retry repeats nothing.

    The POS sends a new key (a UUID) for each charge or payment, and the same key when
    it retries one. ``previous_results`` is where an earlier result with the key would
    be (e.g. the sales of the user's branch); ``create`` makes the new object, which
    then keeps the key and a hash of the request. A repeated key with the same data
    returns the earlier object; with other data it is a 409.
    """

    key = _idempotency_key(request)
    request_hash = hashlib.sha256(
        json.dumps(request.data, sort_keys=True, default=str).encode(),
    ).hexdigest()
    previous = previous_results.filter(idempotency_key=key).first()

    if previous is None:
        try:
            # The savepoint undoes what ``create`` saved if the key is taken meanwhile.
            with transaction.atomic():
                result = create()
                result.idempotency_key = key
                result.request_hash = request_hash
                result.save(update_fields=["idempotency_key", "request_hash"])

                return result
        except IntegrityError as error:
            if "idempotency_key" not in str(error):
                raise

            # Another request with the same key finished first.
            previous = previous_results.filter(idempotency_key=key).first()

    if previous is None or previous.request_hash != request_hash:
        raise IdempotencyConflict

    return previous


def _idempotency_key(request: Request) -> uuid.UUID:
    """The request's ``Idempotency-Key`` header as a UUID; it is required."""

    try:
        return uuid.UUID(request.headers.get(IDEMPOTENCY_HEADER, ""))
    except ValueError:
        raise ValidationError(
            {"idempotency_key": [_("Send a new UUID in the Idempotency-Key header.")]},
        ) from None
