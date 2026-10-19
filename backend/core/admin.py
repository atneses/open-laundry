from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import Branch, User

# Re-register Group so it uses the Unfold styling.
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    search_fields = ["name"]
    filter_horizontal = ["permissions"]


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ["username", "first_name", "last_name", "branch", "is_active", "is_staff"]
    list_filter = ["is_active", "is_staff", "branch"]
    fieldsets = BaseUserAdmin.fieldsets + (("Lavandería", {"fields": ["branch"]}),)


@admin.register(Branch)
class BranchAdmin(ModelAdmin):
    list_display = ["name", "phone"]
    search_fields = ["name"]
