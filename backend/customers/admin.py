from django.contrib import admin
from unfold.admin import ModelAdmin

from .forms import CustomerForm
from .models import Customer

MANAGE_CUSTOMERS = "customers.manage_customers"


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    form = CustomerForm
    list_display = ["name", "phone", "email", "created_at"]
    list_filter = ["branch"]
    # Searching the phone also matches its last digits.
    search_fields = ["phone", "name"]

    def has_module_permission(self, request):
        return request.user.has_perm(MANAGE_CUSTOMERS)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CUSTOMERS)

    def has_add_permission(self, request):
        return request.user.has_perm(MANAGE_CUSTOMERS)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CUSTOMERS)

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CUSTOMERS)
