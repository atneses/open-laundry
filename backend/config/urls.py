from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

api_urlpatterns = [
    # Nothing lives at the root yet; the admin is the entry point.
    path("", RedirectView.as_view(pattern_name="admin:index")),
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("", include("core.urls")),
    path("", include("sales.urls")),
    path("", include("inventory.urls")),
    path("", include("customers.urls")),
]

urlpatterns = [
    # Nothing lives at the root yet; the admin is the entry point.
    path("", RedirectView.as_view(pattern_name="admin:index")),
    path("admin/", admin.site.urls),
    path("api/", include(api_urlpatterns)),
]
