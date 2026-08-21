from django.urls import include, path

urlpatterns = [
    path("forms/", include("stapel_forms.urls")),
]
