from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserCreationForm

from .admin_base import ReadOnlyModelAdmin
from .forms import BranchForm, UserChangeForm
from .models import Branch, PermissionLog, User
from .services import log_permission_changes

MANAGE_USERS = "core.manage_users"

# Re-register Group so it uses the Unfold styling.
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    """Roles: only users with core.manage_users can see or edit them."""

    search_fields = ["name"]
    filter_horizontal = ["permissions"]

    def has_module_permission(self, request):
        return request.user.has_perm(MANAGE_USERS)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_USERS)

    def has_add_permission(self, request):
        return request.user.has_perm(MANAGE_USERS)

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_USERS)

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_USERS)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ["username", "first_name", "last_name", "role", "branch", "is_active"]
    list_filter = ["is_active", "groups", "branch"]
    fieldsets = [
        (None, {"fields": ["username", "password"]}),
        (_("Personal info"), {"fields": ["first_name", "last_name", "email", "branch"]}),
        (
            _("Role and permissions"),
            {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]},
        ),
        (_("Important dates"), {"fields": ["last_login", "date_joined"]}),
    ]
    readonly_fields = ["last_login", "date_joined"]

    @admin.display(description=_("role"))
    def role(self, obj):
        return ", ".join(group.name for group in obj.groups.all()) or "—"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    # Only users with core.manage_users can manage staff accounts.
    def has_module_permission(self, request):
        return request.user.has_perm(MANAGE_USERS)

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm(MANAGE_USERS)

    def has_add_permission(self, request):
        return request.user.has_perm(MANAGE_USERS)

    def has_change_permission(self, request, obj=None):
        # A non-superuser must not edit a superuser (e.g. change their password).
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return request.user.has_perm(MANAGE_USERS)

    def has_delete_permission(self, request, obj=None):
        # Users are deactivated, never deleted, to keep their history.
        return False

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser or obj is None:
            return fieldsets
        # Only superusers can see or grant superuser status.
        return [
            (name, {**opts, "fields": [f for f in opts["fields"] if f != "is_superuser"]})
            for name, opts in fieldsets
        ]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "user_permissions":
            # Each option's label shows its app, so load it in the same query.
            kwargs["queryset"] = Permission.objects.select_related("content_type")
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def save_related(self, request, form, formsets, change):
        user = form.instance
        before = set(user.user_permissions.all()) if change else set()
        super().save_related(request, form, formsets, change)
        log_permission_changes(user, before, user.user_permissions.all(), request.user)


@admin.register(Branch)
class BranchAdmin(ModelAdmin):
    form = BranchForm
    list_display = ["name", "phone"]
    search_fields = ["name"]


@admin.register(PermissionLog)
class PermissionLogAdmin(ReadOnlyModelAdmin):
    list_display = ["created_at", "user", "permission", "action", "created_by"]
    list_filter = ["action"]
    search_fields = ["user__username", "permission__codename"]
    list_select_related = ["user", "permission", "created_by"]
