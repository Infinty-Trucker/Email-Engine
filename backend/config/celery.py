import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("dispatch_os")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    """Register Celery Beat periodic tasks in DatabaseScheduler on startup."""
    try:
        from django_celery_beat.models import PeriodicTask, IntervalSchedule

        # Every 2 minutes — urgent stale check
        every_2min, _ = IntervalSchedule.objects.get_or_create(
            every=2, period=IntervalSchedule.MINUTES,
        )
        PeriodicTask.objects.update_or_create(
            name="check-stale-conversations",
            defaults={
                "task": "notifications.check_stale_conversations",
                "interval": every_2min,
                "queue": "send",
                "enabled": True,
            },
        )

        # Every hour — task digest with routine items + reminders
        every_hour, _ = IntervalSchedule.objects.get_or_create(
            every=1, period=IntervalSchedule.HOURS,
        )
        PeriodicTask.objects.update_or_create(
            name="hourly-task-digest",
            defaults={
                "task": "notifications.hourly_task_digest",
                "interval": every_hour,
                "queue": "send",
                "enabled": True,
            },
        )
    except Exception:
        pass  # DB might not be ready yet on first boot
