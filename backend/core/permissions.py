"""Permission checks shared by the services of every app."""

import functools

from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _


def requires_perm(*codes, message=None):
    """Make the decorated service require every "app_label.codename" in ``codes``.

    The service takes the user as its first argument. ``message`` says what the user
    cannot do; ``required_perms`` on the service lists the codes for other layers
    (e.g. the API permission classes).
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(user, *args, **kwargs):
            if not user.has_perms(codes):
                raise PermissionDenied(message or _("You do not have permission to do this."))

            return func(user, *args, **kwargs)

        wrapper.required_perms = codes

        return wrapper

    return decorator
