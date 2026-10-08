from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("staff/", include("staff_portal.urls")),
    path("admin/", admin.site.urls),
    path("", include("website.urls")),
]

# Uploaded menu photos. In production the web server serves MEDIA_ROOT at /media/ instead.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
