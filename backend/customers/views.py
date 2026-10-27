from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from rest_framework import filters, mixins, viewsets

from core.api import HasPermission

from .models import Customer
from .serializers import CustomerSerializer

MANAGE_CUSTOMERS = "customers.manage_customers"


class CustomerViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Customers of the user's branch: register, edit and search by name or phone.

    ``?search=`` matches names or phones that contain the text, e.g. the last digits
    of the phone. Customers are not deleted: their sales keep them.
    """

    serializer_class = CustomerSerializer
    permission_classes = [HasPermission(MANAGE_CUSTOMERS)]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "phone"]

    def get_queryset(self):
        # drf-spectacular builds the schema without a logged-in user.
        if getattr(self, "swagger_fake_view", False):
            return Customer.objects.none()

        return Customer.objects.filter(branch_id=self.request.user.branch_id).order_by("name")

    def perform_create(self, serializer):
        if self.request.user.branch_id is None:
            raise ValidationError(_("Your user has no branch assigned."))

        serializer.save(branch_id=self.request.user.branch_id)
