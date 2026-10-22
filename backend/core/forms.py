from django import forms
from unfold import forms as unfold_forms

from .models import Branch, User

# Keyboard shown on phones and tablets for each filter.
INPUT_MODES = {
    "name": "text",
    "person-name": "text",
    "code": "text",
    "digits": "numeric",
    "decimal": "decimal",
    "signed-decimal": "text",
}


class InputFilterModelForm(forms.ModelForm):
    """ModelForm that stops the user from typing characters a field does not accept.

    Each form maps its fields to a filter of core/js/input_filters.js, e.g.
    ``input_filters = {"price": "decimal"}``. It is only a convenience: the model
    validators still reject bad values on save.
    """

    input_filters = {}

    class Media:
        js = ["core/js/input_filters.js"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, input_filter in self.input_filters.items():
            # The admin leaves read-only fields out of the form.
            if name not in self.fields:
                continue

            widget = self.fields[name].widget
            widget.attrs["data-input-filter"] = input_filter
            widget.attrs["inputmode"] = INPUT_MODES[input_filter]

            # Unfold renders decimals as type="number", where Firefox still lets letters
            # in and hides them from the script (value reads as ""); filter as text.
            widget.input_type = "text"


class BranchForm(InputFilterModelForm):
    input_filters = {"name": "name", "phone": "digits"}

    class Meta:
        model = Branch
        fields = ["name", "address", "phone"]


class UserChangeForm(InputFilterModelForm, unfold_forms.UserChangeForm):
    input_filters = {"first_name": "person-name", "last_name": "person-name"}

    class Meta(unfold_forms.UserChangeForm.Meta):
        model = User
