from typing import TYPE_CHECKING

from django.db.models import Prefetch, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.api import HasPermission

from .models import Machine, MachineCycle
from .serializers import MachineCycleSerializer, MachineSerializer, StartCycleSerializer
from .services import finish_cycle, start_cycle

if TYPE_CHECKING:
    from rest_framework.request import Request


class MachineViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The machines board: each machine of the user's branch and its running cycle."""

    serializer_class = MachineSerializer
    permission_classes = [HasPermission(*start_cycle.required_perms)]

    def get_queryset(self) -> QuerySet[Machine]:
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return Machine.objects.none()

        running = MachineCycle.objects.filter(status=MachineCycle.Status.RUNNING).select_related(
            "sale_item__sale",
            "sale_item__service",
        )

        # "washer" sorts after "dryer", so a descending kind puts washers first.
        return (
            Machine.objects.filter(branch_id=self.request.user.branch_id)
            .prefetch_related(Prefetch("cycles", queryset=running, to_attr="running_cycles"))
            .order_by("-kind", "label")
        )


class MachineCycleViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Pending cycles of the user's branch, and starting or finishing a cycle."""

    serializer_class = MachineCycleSerializer
    permission_classes = [HasPermission(*start_cycle.required_perms)]

    def get_queryset(self) -> QuerySet[MachineCycle]:
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return MachineCycle.objects.none()

        cycles = MachineCycle.objects.filter(
            sale_item__sale__branch_id=self.request.user.branch_id,
        ).select_related("sale_item__sale__customer", "sale_item__service")

        if self.action == "list":
            return cycles.filter(status=MachineCycle.Status.PENDING).order_by(
                "sale_item__sale__created_at",
                "pk",
            )

        return cycles

    @extend_schema(request=StartCycleSerializer, responses={200: MachineCycleSerializer})
    @action(detail=True, methods=["post"])
    def start(self, request: Request, pk: str | None = None) -> Response:
        """Start the cycle on a machine, in manual mode (the employee presses Start)."""

        cycle = self.get_object()
        data = StartCycleSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        cycle = start_cycle(
            user=request.user,
            cycle=cycle,
            machine=data.validated_data["machine"],
            customer_supplies=data.validated_data["customer_supplies"],
        )

        return self._respond(cycle)

    @extend_schema(request=None, responses={200: MachineCycleSerializer})
    @action(detail=True, methods=["post"])
    def finish(self, request: Request, pk: str | None = None) -> Response:
        """Mark the running cycle as finished, which frees its machine."""

        cycle = finish_cycle(user=request.user, cycle=self.get_object())

        return self._respond(cycle)

    def _respond(self, cycle: MachineCycle) -> Response:
        """The cycle read again with its sale, customer and service in one query."""

        cycle = self.get_queryset().get(pk=cycle.pk)

        return Response(MachineCycleSerializer(cycle).data)
