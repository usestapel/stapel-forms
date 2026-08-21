from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Mounted so the module's read-only operator peephole (admin.py) exists
    # somewhere real, and so LOGIN_URL/LOGIN_REDIRECT_URL resolve.
    path("admin/", admin.site.urls),
    path("auth/api/", include("stapel_auth.urls")),
    path("forms/", include("stapel_forms.urls")),
]
