from core.forms import InputFilterModelForm

from .models import Machine


class MachineForm(InputFilterModelForm):
    input_filters = {"label": "name", "model": "code", "serial_number": "code"}

    class Meta:
        model = Machine
        fields = ["label", "kind", "branch", "model", "serial_number", "status"]
