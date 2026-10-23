from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.permissions import requires_perm
from sales.models import Mode, Sale

from .models import Machine, MachineCycle

START_MACHINE = "machines.start_machine"
PENDING = MachineCycle.Status.PENDING
RUNNING = MachineCycle.Status.RUNNING
FINISHED = MachineCycle.Status.FINISHED
CANCELLED = MachineCycle.Status.CANCELLED


def create_cycles(user, lines) -> list[MachineCycle]:
    """Create one pending cycle, without a machine, per load of each line that uses one.

    Call it from the charge, with the saved sale lines: 3 loads give 3 cycles.
    """

    cycles = [
        # bulk_create skips BaseModel.save, so set the user here.
        MachineCycle(sale_item=line, created_by=user, updated_by=user)
        for line in lines
        if line.service is not None and line.service.uses_machine
        for _load in range(int(line.quantity))
    ]

    return MachineCycle.objects.bulk_create(cycles)


def cancel_cycles(user, sale) -> None:
    """Cancel the pending cycles of a sale that is being cancelled.

    Call it inside the cancellation's transaction. A sale with a cycle that was
    already started cannot be cancelled, since its machine was used.
    """

    cycles = MachineCycle.objects.select_for_update().filter(sale_item__sale=sale)

    if cycles.exclude(status__in=[PENDING, CANCELLED]).exists():
        raise ValidationError(_("A sale with a started machine cycle cannot be cancelled."))

    # QuerySet.update skips BaseModel.save, so set who and when here.
    cycles.filter(status=PENDING).update(
        status=CANCELLED,
        updated_by=user,
        updated_at=timezone.now(),
    )


@requires_perm(START_MACHINE, message=_("You cannot start machines."))
@transaction.atomic
def start_cycle(
    user,
    cycle: MachineCycle,
    machine: Machine,
    *,
    customer_supplies=False,
) -> MachineCycle:
    """Start a pending cycle on a machine in manual mode (the employee presses Start).

    A self-service sale must be fully paid first; a drop-off order can have a balance.
    ``customer_supplies`` means the customer brought their own products, so the
    laundry's are not taken from stock.
    """

    # Lock the sale before its cycle, in the same order as a cancellation.
    sale = Sale.objects.select_for_update().get(pk=cycle.sale_item.sale_id)

    if sale.branch_id != user.branch_id:
        raise PermissionDenied(_("The sale belongs to another branch."))

    cycle = MachineCycle.objects.select_for_update().get(pk=cycle.pk)
    machine = Machine.objects.select_for_update().get(pk=machine.pk)

    if cycle.status != PENDING:
        raise ValidationError(_("This cycle was already started or cancelled."))

    if machine.branch_id != user.branch_id:
        raise PermissionDenied(_("The machine belongs to another branch."))

    if machine.kind != cycle.sale_item.service.machine_kind:
        raise ValidationError({"machine": _("This service needs another kind of machine.")})

    if machine.status == Machine.Status.OUT_OF_SERVICE:
        raise ValidationError({"machine": _("This machine is out of service.")})

    if machine.cycles.filter(status=RUNNING).exists():
        raise ValidationError({"machine": _("This machine is already running a cycle.")})

    if sale.mode == Mode.SELF_SERVICE and sale.balance > 0:
        raise ValidationError(
            _("Charge the whole self-service sale before starting its machines."),
        )

    cycle.status = RUNNING
    cycle.machine = machine
    cycle.customer_supplies = customer_supplies
    cycle.is_manual = True
    cycle.started_by = cycle.updated_by = user
    cycle.started_at = timezone.now()
    cycle.save()

    return cycle


@requires_perm(START_MACHINE, message=_("You cannot finish machine cycles."))
@transaction.atomic
def finish_cycle(user, cycle: MachineCycle) -> MachineCycle:
    """Mark a running cycle as finished by hand, which frees its machine."""

    cycle = MachineCycle.objects.select_for_update().select_related("machine").get(pk=cycle.pk)

    if cycle.status != RUNNING:
        raise ValidationError(_("Only a running cycle can be finished."))

    if cycle.machine.branch_id != user.branch_id:
        raise PermissionDenied(_("The machine belongs to another branch."))

    cycle.status = FINISHED
    cycle.finished_at = timezone.now()
    cycle.updated_by = user
    cycle.save()

    return cycle
