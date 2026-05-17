from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.db import connections
from django.core.cache import cache
from django.http import JsonResponse


def healthz(request):
    """Liveness + minimal readiness probe used by Docker/k8s.

    Hits both the DB and Redis cache; returns 503 if either fails so the
    orchestrator can route traffic away. Unauthenticated by design.
    """
    problems = []
    try:
        connections["default"].cursor().execute("SELECT 1")
    except Exception as e:
        problems.append(f"db:{e.__class__.__name__}")
    try:
        cache.set("__healthz__", "1", 5)
        if cache.get("__healthz__") != "1":
            problems.append("cache:roundtrip")
    except Exception as e:
        problems.append(f"cache:{e.__class__.__name__}")
    if problems:
        return JsonResponse({"status": "unhealthy", "problems": problems}, status=503)
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("webhooks/google/gmail/push", include("apps.mailboxes.webhook_urls")),
    path("api/settings/",  include("apps.settings.urls")),
    path("api/", include("apps.api_urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
