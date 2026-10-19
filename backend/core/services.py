from django.db import transaction

from .models import PermissionLog, User


@transaction.atomic
def log_permission_changes(user: User, before, after, performed_by: User | None) -> None:
    """Record in PermissionLog the extra permissions granted to or revoked from a user."""
    before, after = set(before), set(after)

    entries = [
        PermissionLog(
            user=user,
            permission=permission,
            action=PermissionLog.Action.GRANTED,
            performed_by=performed_by,
        )
        for permission in after - before
    ] + [
        PermissionLog(
            user=user,
            permission=permission,
            action=PermissionLog.Action.REVOKED,
            performed_by=performed_by,
        )
        for permission in before - after
    ]
    PermissionLog.objects.bulk_create(entries)
