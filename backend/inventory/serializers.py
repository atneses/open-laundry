from rest_framework import serializers

from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    """A product for sale, with its stock so the POS can warn before charging."""

    class Meta:
        model = Product
        fields = ["id", "name", "unit", "sale_price", "stock"]
        read_only_fields = fields
