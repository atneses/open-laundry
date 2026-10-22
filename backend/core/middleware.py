from contextvars import ContextVar

_current_request = ContextVar("current_request", default=None)


def get_current_user():
    """User of the request being handled, or None outside a request or if anonymous.

    The user is read when needed, so it also sees the user that DRF authenticates
    with JWT after the middleware runs.
    """
    request = _current_request.get()
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


class CurrentUserMiddleware:
    """Keep the current request available to models (see core.models.BaseModel)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)
