"""Canonical-prefix URLconf for contract emission (contract-pipeline.md §2).

Mounts the module root at ``forms/`` — the module's own ``urls.py`` bakes
the ``api/v1/`` segment in (api-versioning.md §2), so the resulting public
prefix is ``/forms/api/v1/…``, exactly the mount recipe ``urls.py``
documents for hosts.

Declared separately from the test urlconf so the contract-emission mount
can never silently drift from the module's documented public mount recipe.
"""
from django.urls import include, path

urlpatterns = [
    path("forms/", include("stapel_forms.urls")),
]
