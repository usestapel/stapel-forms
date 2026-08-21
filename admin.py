"""Admin for stapel-forms — an operator peephole, nothing more.

Read-only across the board. Workspace admins are not Django staff: in a
multi-tenant product the people who author forms and review responses reach
them through the capability-gated REST surface, never through here. What
this registration is for is the operator looking at a support ticket.

``Submission`` is ``@access.sensitive`` (models.py), so the staff mandate
gates even this view at MID clearance — two independent doors, both shut by
default.
"""
from django.contrib import admin

from .models import Form, FormVersion, Submission


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Form)
class FormAdmin(_ReadOnlyAdmin):
    list_display = ("id", "title", "workspace_id", "state", "deleted_at", "created_at")
    list_filter = ("state",)
    search_fields = ("id", "title", "workspace_id", "public_id")


@admin.register(FormVersion)
class FormVersionAdmin(_ReadOnlyAdmin):
    list_display = ("id", "form", "version", "published_at")
    search_fields = ("id", "form__id")


@admin.register(Submission)
class SubmissionAdmin(_ReadOnlyAdmin):
    list_display = ("id", "form", "version", "submitted_at", "submitted_by", "erased_at")
    search_fields = ("id", "form__id", "workspace_id")
