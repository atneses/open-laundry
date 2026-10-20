from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .forms import ServiceForm, ServicePriceForm
from .models import Service, ServicePrice

MANAGE_CATALOG = "sales.manage_catalog"


class CatalogPermissionMixin:
    """The catalog is seen and edited only with sales.manage_catalog."""

    def has_module_permission(self, request):
        return request.user.has_perm(MANAGE_CATALOG)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CATALOG)

    def has_add_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CATALOG)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CATALOG)

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CATALOG)


class ServicePriceInline(CatalogPermissionMixin, TabularInline):
    model = ServicePrice
    form = ServicePriceForm
    extra = 0
    fields = ["mode", "program", "price", "branch", "is_active", "created_at"]
    readonly_fields = ["is_active", "created_at"]

    # Prices are history: to change one, add a new price.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Service)
class ServiceAdmin(CatalogPermissionMixin, ModelAdmin):
    form = ServiceForm
    list_display = ["name", "kind", "unit", "machine_kind", "is_active"]
    list_filter = ["kind", "machine_kind", "is_active"]
    search_fields = ["name"]
    inlines = [ServicePriceInline]
