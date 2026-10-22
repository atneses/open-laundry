from django import forms
from django.utils.translation import gettext_lazy as _
from unfold.forms import BaseDialogForm
from unfold.widgets import UnfoldAdminTextareaWidget, UnfoldAdminTextInputWidget

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


class CloseCashSessionForm(BaseDialogForm):
    """Cash count captured in the admin to close a forgotten cash session."""

    counted_cash = forms.DecimalField(
        label=_("counted cash"),
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=UnfoldAdminTextInputWidget(
            attrs={"data-input-filter": "decimal", "inputmode": "decimal"}
        ),
    )
    notes = forms.CharField(
        label=_("notes"),
        required=False,
        widget=UnfoldAdminTextareaWidget,
        help_text=_("Required when the counted cash does not match the expected cash."),
    )

    class Media:
        js = ["core/js/input_filters.js"]
