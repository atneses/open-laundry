from django.db.models import Exists, OuterRef, Prefetch, Q, QuerySet
from django.utils.translation import gettext_lazy as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.api import IDEMPOTENCY_HEADER, HasPermission, run_once

from .models import (
    AppliedDiscount,
    CashSession,
    Discount,
    Payment,
    Sale,
    Service,
    ServicePrice,
)
from .serializers import (
    CancelSaleSerializer,
    CartDiscountsQuerySerializer,
    CashSessionSerializer,
    ChargeSerializer,
    CloseCashSessionSerializer,
    DiscountSerializer,
    OpenCashSessionSerializer,
    PaymentRequestSerializer,
    SaleDetailSerializer,
    SaleFilterSerializer,
    SaleListSerializer,
    ServiceSerializer,
)
from .services import (
    VIEW_ALL_CASH_SESSIONS,
    add_payment,
    cancel_sale,
    charge_sale,
    close_cash_session,
    create_sale,
    discounts_for_cart,
    open_cash_session,
)

IDEMPOTENCY_KEY = OpenApiParameter(
    name=IDEMPOTENCY_HEADER,
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.HEADER,
    required=True,
    description="A new UUID for each charge or payment; the same one when retrying it.",
)


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


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """Active services with a price in the user's branch, for the POS to build a sale.

    Read only: the catalog is edited in the admin.
    """

    serializer_class = ServiceSerializer
    permission_classes = [HasPermission(*create_sale.required_perms)]

    def get_queryset(self):
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return Service.objects.none()

        # The general price (no program) of the branch, as charging uses it.
        current_prices = ServicePrice.objects.filter(
            branch_id=self.request.user.branch_id,
            program="",
            is_active=True,
        ).order_by("mode")

        return (
            Service.objects.filter(is_active=True)
            .filter(Exists(current_prices.filter(service=OuterRef("pk"))))
            .prefetch_related(Prefetch("prices", current_prices, to_attr="current_prices"))
            .order_by("name")
        )


@extend_schema_view(list=extend_schema(parameters=[SaleFilterSerializer]))
class SaleViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Sales of the user's branch: charge, pay a balance, cancel, list and see one.

    ``?search=`` matches the sale number or the customer's name or phone.
    """

    filter_backends = [filters.SearchFilter]
    search_fields = ["number", "customer__name", "customer__phone"]

    def get_permissions(self):
        if self.action == "cancel":
            return [HasPermission(*cancel_sale.required_perms)]

        return [HasPermission(*charge_sale.required_perms)]

    def get_serializer_class(self):
        return SaleListSerializer if self.action == "list" else SaleDetailSerializer

    def get_queryset(self):
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return Sale.objects.none()

        sales = Sale.objects.filter(branch_id=self.request.user.branch_id).select_related(
            "customer",
            "created_by",
        )

        if self.action == "list":
            return self._filter(sales).order_by("-created_at")

        return sales.select_related("drop_off_order").prefetch_related(
            "items__service",
            "items__product",
            "items__cycles__machine",
            Prefetch(
                "applied_discounts",
                AppliedDiscount.objects.select_related("discount").order_by("pk"),
            ),
            "payments",
        )

    def _filter(self, sales: QuerySet[Sale]) -> QuerySet[Sale]:
        """Apply the query filters; an invalid value is a 400."""

        query = SaleFilterSerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data

        if "status" in data:
            sales = sales.filter(status=data["status"])

        if "mode" in data:
            sales = sales.filter(mode=data["mode"])

        if "date_from" in data:
            sales = sales.filter(created_at__date__gte=data["date_from"])

        if "date_to" in data:
            sales = sales.filter(created_at__date__lte=data["date_to"])

        if data["has_balance"] is True:
            sales = sales.exclude(status=Sale.Status.CANCELLED).filter(balance__gt=0)
        elif data["has_balance"] is False:
            # A cancelled sale is no longer charged, so it owes nothing.
            sales = sales.filter(Q(balance=0) | Q(status=Sale.Status.CANCELLED))

        return sales

    def _detail(self, sale, status_code=status.HTTP_200_OK):
        """The sale as in GET /api/sales/{id}/, read again with its related rows."""

        sale = self.get_queryset().get(pk=sale.pk)

        return Response(SaleDetailSerializer(sale).data, status=status_code)

    @extend_schema(
        request=ChargeSerializer,
        responses={201: SaleDetailSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def create(self, request):
        """Charge a sale in one go: lines, then discounts, then payments; all or nothing."""

        data = ChargeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        sale = run_once(
            request=request,
            previous_results=Sale.objects.filter(branch_id=request.user.branch_id),
            create=lambda: charge_sale(request.user, data.to_request()),
        )

        return self._detail(sale, status.HTTP_201_CREATED)

    @extend_schema(
        request=PaymentRequestSerializer,
        responses={201: SaleDetailSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        """Record a later payment, such as the balance of a drop-off order."""

        sale = self.get_object()
        data = PaymentRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        payment = data.to_request()
        run_once(
            request=request,
            previous_results=Payment.objects.filter(sale=sale),
            create=lambda: add_payment(
                request.user,
                sale,
                payment.method,
                payment.amount,
                payment.reference,
                received=payment.received,
            ),
        )

        return self._detail(sale, status.HTTP_201_CREATED)

    @extend_schema(request=CancelSaleSerializer, responses={200: SaleDetailSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel the sale with a reason, in the open cash session."""

        sale = self.get_object()
        data = CancelSaleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        cancel_sale(request.user, sale, data.validated_data["reason"])

        return self._detail(sale)


@extend_schema(parameters=[CartDiscountsQuerySerializer])
class DiscountViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Discounts that apply to the sale being built, from ``?mode=`` and ``?services=``.

    ``services`` repeats for each service id: ``?services=1&services=2``.
    """

    serializer_class = DiscountSerializer
    permission_classes = [HasPermission(*discounts_for_cart.required_perms)]

    def get_queryset(self):
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return Discount.objects.none()

        query = CartDiscountsQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)

        return discounts_for_cart(
            self.request.user,
            query.validated_data["mode"],
            query.validated_data.get("services", []),
        )
