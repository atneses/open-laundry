from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from core.admin_base import ReadOnlyModelAdmin

from .forms import MachineForm
from .models import Machine, MachineCycle

MANAGE_MACHINES = "machines.manage_machines"


@admin.register(Machine)
class MachineAdmin(ModelAdmin):
    """Machines are not deleted: one that stops working is marked out of service."""

    form = MachineForm
    list_display = ["label", "kind", "branch", "status", "model", "serial_number"]
    list_filter = ["branch", "kind", "status"]
    list_select_related = ["branch"]
    search_fields = ["label", "serial_number"]

    def has_module_permission(self, request):
        return request.user.has_perm(MANAGE_MACHINES)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_MACHINES)

    def has_add_permission(self, request):
        return request.user.has_perm(MANAGE_MACHINES)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_MACHINES)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MachineCycle)
class MachineCycleAdmin(ReadOnlyModelAdmin):
    """Cycles are history: created by the sale and started from the POS."""

    list_display = [
        "created_at",
        "sale",
        "service",
        "machine",
        "status",
        "is_manual",
        "customer_supplies",
        "started_by",
        "started_at",
        "finished_at",
    ]
    list_filter = ["status", "machine", "is_manual"]
    list_select_related = ["sale_item__sale", "sale_item__service", "machine", "started_by"]
    search_fields = ["sale_item__sale__number"]

    @admin.display(description=_("sale"), ordering="sale_item__sale__number")
    def sale(self, cycle):
        return cycle.sale_item.sale.number

    @admin.display(description=_("service"))
    def service(self, cycle):
        return cycle.sale_item.service
