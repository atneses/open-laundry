from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import CashSession
from .services import VIEW_ALL_CASH_SESSIONS, session_totals

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
