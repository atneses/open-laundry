from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

validate_name = RegexValidator(
    r"^(?:[^\W_]|[ .'-])+$",
    _("Use only letters, numbers, spaces, periods, hyphens and apostrophes."),
)
validate_person_name = RegexValidator(
    r"^(?:[^\W\d_]|[ .'-])+$",
    _("Use only letters, spaces, periods, hyphens and apostrophes."),
)
validate_code = RegexValidator(
    r"^(?:[^\W_]|-)+$", _("Use only letters, numbers and hyphens, without spaces.")
)
validate_phone = RegexValidator(r"^\d+$", _("Use only digits, without spaces or dashes."))
