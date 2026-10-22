from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action

from core.admin_base import ReadOnlyModelAdmin

from .forms import CloseCashSessionForm, DiscountForm, ServiceForm, ServicePriceForm
from .models import (
    AppliedDiscount,
    CashSession,
    Discount,
    Payment,
    Sale,
    SaleItem,
    Service,
    ServicePrice,
)
from .services import VIEW_ALL_CASH_SESSIONS, close_cash_session

MANAGE_CATALOG = "sales.manage_catalog"
MANAGE_DISCOUNTS = "sales.manage_discounts"


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


@admin.register(CashSession)
class CashSessionAdmin(ReadOnlyModelAdmin):
    """Cash sessions are history: opened and closed from the POS, only viewed here."""

    list_display = [
        "opened_at",
        "closed_at",
        "user",
        "closed_by",
        "branch",
        "opening_float",
        "expected_cash",
        "counted_cash",
        "difference",
        "card_total",
    ]
    list_filter = ["branch", "user"]
    list_select_related = ["branch", "user", "closed_by"]
    actions_detail = ["close_session"]

    def has_module_permission(self, request):
        return request.user.has_perm(VIEW_ALL_CASH_SESSIONS)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(VIEW_ALL_CASH_SESSIONS)

    def has_close_session_permission(self, request, object_id=None):
        """Whoever sees every cash session can close one that was left open."""

        if not request.user.has_perm(VIEW_ALL_CASH_SESSIONS):
            return False

        return (
            object_id is None
            or CashSession.objects.filter(pk=object_id, closed_at__isnull=True).exists()
        )

    @action(
        description=_("Close cash session"),
        url_path="close",
        icon="lock",
        permissions=["close_session"],
        dialog={
            "title": _("Close cash session"),
            "description": _("Capture the cash counted in the drawer of this forgotten session."),
            "form_class": CloseCashSessionForm,
            "form_submit_text": _("Close"),
        },
    )
    def close_session(self, request, form, object_id):
        session = get_object_or_404(CashSession, pk=object_id)

        try:
            close_cash_session(
                session,
                request.user,
                form.cleaned_data["counted_cash"],
                form.cleaned_data["notes"],
            )
        except ValidationError as error:
            if hasattr(error, "error_dict"):
                for field, field_errors in error.error_dict.items():
                    form.add_error(field if field in form.fields else None, field_errors)
            else:
                form.add_error(None, error)

            return render(
                request,
                "unfold/helpers/dialog.html",
                {
                    "dialog": self.close_session.dialog,
                    "form": form,
                    "form_submit_text": self.close_session.dialog["form_submit_text"],
                },
            )

        messages.success(request, _("The cash session was closed."))

        # The dialog posts with htmx, which follows this header with a full page load.
        url = reverse("admin:sales_cashsession_change", args=[object_id])

        return HttpResponse(headers={"HX-Redirect": url})


class SaleItemInline(TabularInline):
    model = SaleItem
    extra = 0
    fields = ["service", "product", "quantity", "unit_price", "amount"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PaymentInline(TabularInline):
    model = Payment
    extra = 0
    fields = ["created_at", "method", "amount", "reference", "cash_session", "created_by"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AppliedDiscountInline(TabularInline):
    model = AppliedDiscount
    extra = 0
    fields = ["discount", "sale_item", "amount", "created_by", "created_at"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(ReadOnlyModelAdmin):
    """Sales are charged at the POS and only viewed here."""

    list_display = [
        "number",
        "created_at",
        "mode",
        "status",
        "customer",
        "total",
        "balance",
        "created_by",
    ]
    list_filter = ["status", "mode", "branch", "created_by"]
    search_fields = ["number", "customer__name", "customer__phone"]
    list_select_related = ["customer", "created_by"]
    date_hierarchy = "created_at"
    inlines = [SaleItemInline, AppliedDiscountInline, PaymentInline]


@admin.register(Discount)
class DiscountAdmin(ModelAdmin):
    """Discounts are managed with sales.manage_discounts; deactivate them, never delete."""

    form = DiscountForm
    list_display = [
        "name",
        "kind",
        "value",
        "scope",
        "mode",
        "valid_from",
        "valid_until",
        "is_active",
    ]
    list_filter = ["is_active", "kind", "scope", "mode", "branch"]
    search_fields = ["name"]

    def has_module_permission(self, request):
        return request.user.has_perm(MANAGE_DISCOUNTS)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_DISCOUNTS)

    def has_add_permission(self, request):
        return request.user.has_perm(MANAGE_DISCOUNTS)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_DISCOUNTS)

    # Applied discounts point to it.
    def has_delete_permission(self, request, obj=None):
        return False
