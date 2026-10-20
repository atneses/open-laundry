from django.contrib import admin
from django.db.models import F
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from sales.admin import MANAGE_CATALOG, CatalogPermissionMixin

from .models import LoadConsumption, Product, StockMovement
from .services import record_stock_movement

RECEIVE_STOCK = "inventory.receive_stock"
ADJUST_STOCK = "inventory.adjust_stock"
INVENTORY_PERMISSIONS = (MANAGE_CATALOG, RECEIVE_STOCK, ADJUST_STOCK)


def has_any_perm(user, perms):
    return any(user.has_perm(perm) for perm in perms)


def can_view_inventory(request):
    """Sidebar check for products and stock movements (see UNFOLD["SIDEBAR"])."""
    return has_any_perm(request.user, INVENTORY_PERMISSIONS)


class LowStockFilter(admin.SimpleListFilter):
    title = _("stock")
    parameter_name = "stock_level"

    def lookups(self, request, model_admin):
        return [("low", _("Below minimum"))]

    def queryset(self, request, queryset):
        if self.value() == "low":
            return queryset.filter(stock__lt=F("min_stock"))
        return queryset


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ["name", "unit", "stock", "min_stock", "is_for_sale", "sale_price"]
    list_filter = [LowStockFilter, "is_for_sale", "branch"]
    search_fields = ["name", "sku"]
    # Stock only changes through stock movements.
    readonly_fields = ["stock"]

    def has_module_permission(self, request):
        return has_any_perm(request.user, INVENTORY_PERMISSIONS)

    def has_view_permission(self, request, obj=None):
        return has_any_perm(request.user, INVENTORY_PERMISSIONS)

    def has_add_permission(self, request):
        return request.user.has_perm(MANAGE_CATALOG)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CATALOG)

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_CATALOG)


@admin.register(LoadConsumption)
class LoadConsumptionAdmin(CatalogPermissionMixin, ModelAdmin):
    list_display = ["service", "product", "quantity"]
    list_filter = ["service"]
    list_select_related = ["service", "product"]


@admin.register(StockMovement)
class StockMovementAdmin(ModelAdmin):
    list_display = ["created_at", "product", "kind", "quantity", "unit_cost", "user"]
    list_filter = ["kind", "product"]
    search_fields = ["product__name"]
    list_select_related = ["product", "user"]
    date_hierarchy = "created_at"
    fields = ["product", "kind", "quantity", "unit_cost", "reason"]

    def has_module_permission(self, request):
        return has_any_perm(request.user, INVENTORY_PERMISSIONS)

    def has_view_permission(self, request, obj=None):
        return has_any_perm(request.user, INVENTORY_PERMISSIONS)

    def has_add_permission(self, request):
        return bool(self.allowed_kinds(request))

    # Movements are history: they are never edited or deleted.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def allowed_kinds(self, request):
        """Kinds this user may record by hand; consumption and sales come from the system."""
        kinds = []
        if request.user.has_perm(RECEIVE_STOCK):
            kinds.append(StockMovement.Kind.PURCHASE)
        if request.user.has_perm(ADJUST_STOCK):
            kinds.append(StockMovement.Kind.ADJUSTMENT)
        return kinds

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "kind":
            allowed = self.allowed_kinds(request)
            kwargs["choices"] = [c for c in StockMovement.Kind.choices if c[0] in allowed]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        obj.user = request.user
        record_stock_movement(obj)
