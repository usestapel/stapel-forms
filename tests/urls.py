from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("forms/", include("stapel_forms.urls")),
    # The admin peephole is a tested surface since 0.6.0 (the responses
    # table, the builder and the mandate that gates them), so the bare test
    # mount carries it. It is NOT in `codegen_urls.py`: the contract triad
    # describes the HTTP API, and admin pages are not part of it.
    path("admin/", admin.site.urls),
]
