from django.urls import path
from django.http import JsonResponse
from rest_framework.decorators import api_view


def health(request):
    return JsonResponse({"status": "ok"})


@api_view(["GET"])
def worker_status(request):
    """Check if Celery worker is alive."""
    try:
        from config.celery import app as celery_app
        inspect = celery_app.control.inspect(timeout=2.0)
        active  = inspect.active()
        if active:
            workers = list(active.keys())
            total   = sum(len(v) for v in active.values())
            return JsonResponse({"ok": True, "workers": workers, "active_tasks": total})
        return JsonResponse({"ok": False, "error": "No workers responding. Run: docker compose up worker -d"})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})


urlpatterns = [
    path("health/",        health),
    path("worker-status/", worker_status),
]
