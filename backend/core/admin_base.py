from django.core.exceptions import ValidationError
from django.core.validators import EMPTY_VALUES
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.utils import parse_date_str


class ReadOnlyModelAdmin(ModelAdmin):
    """Admin for records with history (logs, sales, payments, cash sessions).

    Records can be viewed but never added, edited or deleted from the admin.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LocalDateRangeFilter(RangeDateFilter):
    """From/to dates for a date and time field, in local time; "to" includes the whole day.

    Unfold's filter compares the date and time with a date, which is midnight, so it
    would leave out the records of the last day.
    """

    def queryset(self, request, queryset):
        filters = {}

        for suffix, lookup in (("_from", "gte"), ("_to", "lte")):
            value = self.used_parameters.get(f"{self.parameter_name}{suffix}")

            if value not in EMPTY_VALUES:
                filters[f"{self.field_path}__date__{lookup}"] = parse_date_str(value)

        try:
            return queryset.filter(**filters)
        except ValueError, ValidationError:
            return None
