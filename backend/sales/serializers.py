from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from customers.models import Customer
from inventory.models import Product
from machines.models import MachineCycle

from .models import (
    CashSession,
    Discount,
    DropOffOrder,
    Mode,
    Payment,
    Sale,
    SaleItem,
    Service,
    ServicePrice,
)
from .services import (
    VIEW_ALL_CASH_SESSIONS,
    ChargeRequest,
    DropOffRequest,
    ItemRequest,
    PaymentRequest,
    session_totals,
)

# Totals hidden from the cashier while the session is open (blind close).
HIDDEN_TOTALS = ["expected_cash", "card_total", "sales_count", "cancellations_count"]


class CashSessionSerializer(serializers.ModelSerializer):
    """A cash session. While it is open, only ``view_all_cash_sessions`` sees its totals.

    The cashier counts the cash without knowing how much there should be, and sees
    the expected cash and the difference once the session is closed.
    """

    user = serializers.SerializerMethodField()
    closed_by = serializers.SerializerMethodField()
    expected_cash = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    card_total = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    sales_count = serializers.IntegerField(read_only=True, allow_null=True)
    cancellations_count = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = CashSession
        fields = [
            "id",
            "user",
            "opened_at",
            "closed_at",
            "closed_by",
            "opening_float",
            "expected_cash",
            "counted_cash",
            "difference",
            "card_total",
            "sales_count",
            "cancellations_count",
            "notes",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.closed_at is not None:
            return data

        if not self.context["request"].user.has_perm(VIEW_ALL_CASH_SESSIONS):
            return data | dict.fromkeys(HIDDEN_TOTALS)

        # The stored totals are filled when it closes; until then compute them.
        totals = session_totals(instance)
        amount = self.fields["expected_cash"]

        return data | {
            "expected_cash": amount.to_representation(instance.opening_float + totals["cash"]),
            "card_total": amount.to_representation(totals["card"]),
            "sales_count": totals["sales"],
            "cancellations_count": totals["cancellations"],
        }

    @extend_schema_field(str)
    def get_user(self, session):
        return session.user.get_display_name()

    @extend_schema_field({"type": "string", "nullable": True})
    def get_closed_by(self, session):
        return session.closed_by.get_display_name() if session.closed_by else None


class OpenCashSessionSerializer(serializers.Serializer):
    opening_float = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


class CloseCashSessionSerializer(serializers.Serializer):
    counted_cash = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ServicePriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePrice
        fields = ["mode", "price"]
        read_only_fields = fields


class ServiceSerializer(serializers.ModelSerializer):
    """A service with its current price for each mode it is sold in, in the user's branch.

    ``prices`` comes from the view's prefetch (``current_prices``); a mode without a
    price is not listed.
    """

    prices = ServicePriceSerializer(source="current_prices", many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "kind",
            "unit",
            "uses_machine",
            "prices",
        ]
        read_only_fields = fields


class DiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discount
        fields = ["id", "name", "kind", "value", "scope"]
        read_only_fields = fields


class CartDiscountsQuerySerializer(serializers.Serializer):
    """Query of ``/api/discounts/``: the mode and services of the sale being built."""

    mode = serializers.ChoiceField(choices=Mode.choices)
    services = serializers.ListField(child=serializers.IntegerField(), required=False)


class ChargeItemSerializer(serializers.Serializer):
    """A line to charge: a service or a product, and how many."""

    service = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        required=False,
        allow_null=True,
    )
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(),
        required=False,
        allow_null=True,
    )
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3)


class PaymentCreateSerializer(serializers.Serializer):
    """A payment; ``received`` is the cash handed over, to show the change."""

    method = serializers.ChoiceField(choices=Payment.Method.choices)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    received = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
    )

    def to_request(self) -> PaymentRequest:
        return PaymentRequest(**self.validated_data)


class DropOffCreateSerializer(serializers.Serializer):
    promised_at = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ChargeSerializer(serializers.Serializer):
    """Everything to charge a sale in one request; the services check the rules."""

    mode = serializers.ChoiceField(choices=Mode.choices)
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    items = ChargeItemSerializer(many=True)
    discounts = serializers.PrimaryKeyRelatedField(
        queryset=Discount.objects.all(),
        many=True,
        required=False,
        default=list,
    )
    payments = PaymentCreateSerializer(many=True, required=False, default=list)
    drop_off = DropOffCreateSerializer(required=False, allow_null=True, default=None)

    def to_request(self) -> ChargeRequest:
        data = self.validated_data
        drop_off = data["drop_off"]

        return ChargeRequest(
            mode=data["mode"],
            items=[ItemRequest(**item) for item in data["items"]],
            customer=data["customer"],
            drop_off=DropOffRequest(**drop_off) if drop_off else None,
            discounts=data["discounts"],
            payments=[PaymentRequest(**payment) for payment in data["payments"]],
        )


class CancelSaleSerializer(serializers.Serializer):
    reason = serializers.CharField()


class SaleFilterSerializer(serializers.Serializer):
    """Query filters of the sales list; ``search`` is handled by SearchFilter."""

    status = serializers.ChoiceField(choices=Sale.Status.choices, required=False)
    mode = serializers.ChoiceField(choices=Mode.choices, required=False)
    has_balance = serializers.BooleanField(required=False, allow_null=True, default=None)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class SaleCustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "phone"]
        read_only_fields = fields


class SaleListSerializer(serializers.ModelSerializer):
    """A sale in a list: enough to find it; the detail has its lines and payments."""

    customer = SaleCustomerSerializer(read_only=True, allow_null=True)
    cashier = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            "id",
            "number",
            "created_at",
            "mode",
            "status",
            "customer",
            "total",
            "balance",
            "cashier",
        ]
        read_only_fields = fields

    @extend_schema_field(str)
    def get_cashier(self, sale):
        return sale.created_by.get_display_name()


class MachineCycleSummarySerializer(serializers.ModelSerializer):
    machine = serializers.StringRelatedField(allow_null=True)

    class Meta:
        model = MachineCycle
        fields = ["id", "status", "machine", "started_at", "finished_at"]
        read_only_fields = fields


class SaleItemSerializer(serializers.ModelSerializer):
    description = serializers.SerializerMethodField()
    cycles = MachineCycleSummarySerializer(many=True, read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id",
            "service",
            "product",
            "description",
            "quantity",
            "unit_price",
            "amount",
            "cycles",
        ]
        read_only_fields = fields

    @extend_schema_field(str)
    def get_description(self, item):
        return str(item.service or item.product)


class SaleDiscountSerializer(serializers.Serializer):
    """A discount applied to the sale and the total it took off."""

    discount = serializers.IntegerField()
    name = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class SalePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["id", "created_at", "method", "amount", "received", "reference"]
        read_only_fields = fields


class SaleDropOffOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = DropOffOrder
        fields = ["id", "status", "promised_at", "notes", "delivered_at"]
        read_only_fields = fields


class SaleDetailSerializer(SaleListSerializer):
    """A sale with its lines, cycles, discounts, payments and drop-off order."""

    items = SaleItemSerializer(many=True, read_only=True)
    discounts = serializers.SerializerMethodField()
    payments = SalePaymentSerializer(many=True, read_only=True)
    drop_off_order = SaleDropOffOrderSerializer(read_only=True, allow_null=True)

    class Meta(SaleListSerializer.Meta):
        fields = [
            *SaleListSerializer.Meta.fields,
            "subtotal",
            "discount_total",
            "items",
            "discounts",
            "payments",
            "drop_off_order",
            "cancelled_at",
            "cancel_reason",
        ]
        read_only_fields = fields

    @extend_schema_field(SaleDiscountSerializer(many=True))
    def get_discounts(self, sale):
        """One entry per discount; a discount on services adds up its lines."""

        totals = {}

        for row in sale.applied_discounts.all():
            entry = totals.setdefault(
                row.discount_id,
                {"discount": row.discount_id, "name": row.discount.name, "amount": 0},
            )
            entry["amount"] += row.amount

        return SaleDiscountSerializer(totals.values(), many=True).data


class DropOffOrderSerializer(serializers.ModelSerializer):
    """A drop-off order with its sale's number, customer, balance and status."""

    number = serializers.CharField(source="sale.number", read_only=True)
    customer = SaleCustomerSerializer(source="sale.customer", read_only=True)
    balance = serializers.DecimalField(
        source="sale.balance",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    sale_status = serializers.ChoiceField(
        source="sale.status",
        choices=Sale.Status.choices,
        read_only=True,
    )

    class Meta:
        model = DropOffOrder
        fields = [
            "id",
            "sale",
            "number",
            "customer",
            "balance",
            "sale_status",
            "status",
            "promised_at",
            "notes",
            "delivered_at",
        ]
        read_only_fields = fields


class DropOffOrderFilterSerializer(serializers.Serializer):
    """Query filters of the drop-off orders list; ``search`` is handled by SearchFilter."""

    status = serializers.ChoiceField(choices=DropOffOrder.Status.choices, required=False)


class AdvanceDropOffOrderSerializer(serializers.Serializer):
    """The status the order should reach; a retry with the same one changes nothing."""

    status = serializers.ChoiceField(choices=DropOffOrder.Status.choices)
