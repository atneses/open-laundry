from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    """A customer of the user's branch; the branch is taken from the user."""

    class Meta:
        model = Customer
        fields = ["id", "name", "phone", "email", "address", "notes"]

    def validate_phone(self, phone):
        """Reject a phone another customer of the branch already has."""

        branch_id = self.context["request"].user.branch_id
        others = Customer.objects.filter(branch_id=branch_id, phone=phone)

        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)

        if others.exists():
            raise serializers.ValidationError(_("A customer with this phone already exists."))

        return phone
