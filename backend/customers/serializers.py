from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Customer

PHONE_TAKEN = _("A customer with this phone already exists.")


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
            raise serializers.ValidationError(PHONE_TAKEN)

        return phone

    def save(self, **kwargs):
        """Save; a phone registered at the same moment by another request is a 400 too.

        Two requests can both pass ``validate_phone`` before either saves; the
        database constraint then rejects the second one.
        """

        try:
            # The savepoint keeps the request's transaction usable if the constraint fails.
            with transaction.atomic():
                return super().save(**kwargs)
        except IntegrityError as error:
            if "unique_phone_per_branch" not in str(error):
                raise

            raise serializers.ValidationError({"phone": [PHONE_TAKEN]}) from None
