from core.forms import InputFilterModelForm

from .models import Customer


class CustomerForm(InputFilterModelForm):
    input_filters = {"name": "person-name", "phone": "digits"}

    class Meta:
        model = Customer
        fields = ["branch", "name", "phone", "email", "address", "notes"]
