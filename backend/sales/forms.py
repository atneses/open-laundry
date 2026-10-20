from core.forms import InputFilterModelForm

from .models import Service, ServicePrice


class ServiceForm(InputFilterModelForm):
    input_filters = {"name": "name"}

    class Meta:
        model = Service
        fields = ["name", "kind", "unit", "machine_kind", "uses_machine", "is_active"]


class ServicePriceForm(InputFilterModelForm):
    input_filters = {"price": "decimal"}

    class Meta:
        model = ServicePrice
        fields = ["mode", "program", "price", "branch"]
