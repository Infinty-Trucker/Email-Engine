from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from .models import Mailbox


class MailboxSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    company_mc   = serializers.CharField(source="company.mc_number", read_only=True)

    class Meta:
        model  = Mailbox
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class MailboxViewSet(viewsets.ModelViewSet):
    queryset = Mailbox.objects.select_related("company").all()
    serializer_class = MailboxSerializer

    @action(detail=True, methods=["post"])
    def register_watch(self, request, pk=None):
        mb = self.get_object()
        try:
            from apps.mailboxes.gmail_client import register_watch
            from django.conf import settings
            from datetime import datetime, timezone
            result = register_watch(mb.email_address, settings.GOOGLE_PUBSUB_TOPIC)
            expiry = datetime.fromtimestamp(int(result["expiration"]) / 1000, tz=timezone.utc)
            mb.watch_status   = "active"
            mb.watch_expiry   = expiry
            mb.last_history_id = result.get("historyId", mb.last_history_id)
            mb.save()
            return Response({"ok": True, "historyId": mb.last_history_id})
        except Exception as e:
            mb.watch_status = "error"
            mb.save(update_fields=["watch_status"])
            return Response({"error": str(e)}, status=400)

    @action(detail=True, methods=["post"])
    def stop_watch(self, request, pk=None):
        mb = self.get_object()
        try:
            from apps.mailboxes.gmail_client import stop_watch
            stop_watch(mb.email_address)
        except Exception:
            pass
        mb.watch_status = "expired"
        mb.save(update_fields=["watch_status"])
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def test_connection(self, request, pk=None):
        mb = self.get_object()
        try:
            from apps.mailboxes.gmail_client import _get_service
            svc = _get_service(mb.email_address)
            svc.users().getProfile(userId="me").execute()
            return Response({"ok": True, "email": mb.email_address})
        except Exception as e:
            return Response({"ok": False, "error": str(e)}, status=400)


router = DefaultRouter()
router.register("", MailboxViewSet, basename="mailboxes")
urlpatterns = router.urls
