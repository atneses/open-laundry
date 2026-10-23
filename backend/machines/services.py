from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import MachineCycle

PENDING = MachineCycle.Status.PENDING
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
