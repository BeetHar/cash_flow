from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("system-admin/", admin.site.urls),
    path("", include("cashflow.presentation.web.urls")),
]

