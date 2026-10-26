from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.api import HasPermission

from .models import CashSession
from .serializers import (
    CashSessionSerializer,
    CloseCashSessionSerializer,
    OpenCashSessionSerializer,
)
from .services import VIEW_ALL_CASH_SESSIONS, close_cash_session, open_cash_session


class CashSessionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Cash sessions of the user's branch: open, close, the current one and the history.

    A cashier sees only their own sessions; ``view_all_cash_sessions`` sees every one.
    """

    serializer_class = CashSessionSerializer
    permission_classes = [HasPermission(*open_cash_session.required_perms)]

    def get_queryset(self):
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return CashSession.objects.none()

        user = self.request.user
        sessions = (
            CashSession.objects.filter(branch_id=user.branch_id)
            .select_related("user", "closed_by")
            .order_by("-opened_at")
        )

        if user.has_perm(VIEW_ALL_CASH_SESSIONS):
            return sessions

        return sessions.filter(user=user)

    @extend_schema(request=OpenCashSessionSerializer, responses={201: CashSessionSerializer})
    def create(self, request):
        """Open a cash session for the branch, which must have none open."""

        data = OpenCashSessionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = open_cash_session(request.user, data.validated_data["opening_float"])

        return Response(self.get_serializer(session).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: CashSessionSerializer})
    @action(detail=False)
    def current(self, request):
        """The open session of the branch, even if another cashier opened it (404 if none)."""

        session = (
            CashSession.objects.filter(branch_id=request.user.branch_id, closed_at__isnull=True)
            .select_related("user", "closed_by")
            .first()
        )

        if session is None:
            raise NotFound(_("There is no open cash session."))

        return Response(self.get_serializer(session).data)

    @extend_schema(request=CloseCashSessionSerializer, responses={200: CashSessionSerializer})
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close the session with the counted cash; a difference needs notes."""

        session = self.get_object()
        data = CloseCashSessionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = close_cash_session(session, request.user, **data.validated_data)

        return Response(self.get_serializer(session).data)
