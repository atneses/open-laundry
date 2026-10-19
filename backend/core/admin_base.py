from unfold.admin import ModelAdmin


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
