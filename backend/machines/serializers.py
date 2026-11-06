from datetime import timedelta
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from sales.models import Mode
from sales.serializers import SaleCustomerSerializer

from .models import Machine, MachineCycle
from .services import sale_can_start_machines


class CurrentCycleSerializer(serializers.ModelSerializer):
    """The cycle running on a machine, with when it should end."""

    number = serializers.CharField(source="sale_item.sale.number", read_only=True)
    service = serializers.CharField(source="sale_item.service.name", read_only=True)
    expected_end_at = serializers.SerializerMethodField()

    class Meta:
        model = MachineCycle
        fields = ["id", "number", "service", "started_at", "expected_end_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_expected_end_at(self, cycle: MachineCycle) -> str | None:
        """Start plus the service's expected minutes; none if the service has no minutes."""

        minutes = cycle.sale_item.service.expected_minutes

        if minutes is None:
            return None

        # Same format and time zone as ``started_at``.
        return serializers.DateTimeField().to_representation(
            value=cycle.started_at + timedelta(minutes=minutes),
        )


class MachineSerializer(serializers.ModelSerializer):
    """A machine of the board: free, in use (with its cycle) or out of service."""

    current_cycle = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = ["id", "label", "kind", "status", "current_cycle"]
        read_only_fields = fields

    @extend_schema_field(CurrentCycleSerializer(allow_null=True))
    def get_current_cycle(self, machine: Machine) -> dict | None:
        """The running cycle, prefetched by the view in ``running_cycles``."""

        if not machine.running_cycles:
            return None

        return CurrentCycleSerializer(machine.running_cycles[0]).data


class MachineCycleSerializer(serializers.ModelSerializer):
    """A cycle with its sale, so the POS can tell which load it is."""

    sale = serializers.IntegerField(source="sale_item.sale_id", read_only=True)
    number = serializers.CharField(source="sale_item.sale.number", read_only=True)
    mode = serializers.ChoiceField(
        source="sale_item.sale.mode",
        choices=Mode.choices,
        read_only=True,
    )
    customer = SaleCustomerSerializer(
        source="sale_item.sale.customer",
        read_only=True,
        allow_null=True,
    )
    service = serializers.CharField(source="sale_item.service.name", read_only=True)
    # A cycle's service always uses a machine, so its kind is a washer or a dryer.
    machine_kind = serializers.ChoiceField(
        source="sale_item.service.machine_kind",
        choices=Machine.Kind.choices,
        read_only=True,
    )
    can_start = serializers.SerializerMethodField()

    class Meta:
        model = MachineCycle
        fields = [
            "id",
            "status",
            "sale",
            "number",
            "mode",
            "customer",
            "service",
            "machine_kind",
            "machine",
            "started_at",
            "finished_at",
            "can_start",
        ]
        read_only_fields = fields

    def get_can_start(self, cycle: MachineCycle) -> bool:
        """False while a self-service sale has a balance: charge it first."""

        return sale_can_start_machines(cycle.sale_item.sale)


class StartCycleSerializer(serializers.Serializer):
    """The machine to start the cycle on; only machines of the user's branch."""

    machine = serializers.PrimaryKeyRelatedField(queryset=Machine.objects.none())
    customer_supplies = serializers.BooleanField(default=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        request = self.context.get("request")

        if request is not None:
            self.fields["machine"].queryset = Machine.objects.filter(
                branch_id=request.user.branch_id,
            )
