from django.urls import path
from django.utils import timezone
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from .models import Approval


class ApprovalSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source="requested_by.get_full_name", read_only=True)
    subject    = serializers.CharField(source="message.subject", read_only=True)
    body_text  = serializers.CharField(source="message.body_text", read_only=True)
    company    = serializers.CharField(source="conversation.mailbox.company.name", read_only=True)
    category   = serializers.CharField(source="conversation.category", read_only=True)

    class Meta:
        model  = Approval
        fields = ["id","status","requested_by_name","subject","body_text",
                  "company","category","reason","created_at"]


class ApprovalViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApprovalSerializer
    queryset = Approval.objects.select_related(
        "message","conversation__mailbox__company","requested_by"
    ).filter(status="pending")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not request.user.can_approve:
            return Response({"error": "Permission denied"}, status=403)
        a = self.get_object()
        a.status      = "approved"
        a.approved_by = request.user
        a.reason      = request.data.get("note","")
        a.resolved_at = timezone.now()
        a.save()
        a.conversation.status = "replied"
        a.conversation.save(update_fields=["status"])
        from apps.conversations.tasks import send_outbound_email
        send_outbound_email.delay(str(a.message.id))
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        if not request.user.can_approve:
            return Response({"error": "Permission denied"}, status=403)
        a = self.get_object()
        a.status      = "rejected"
        a.approved_by = request.user
        a.reason      = request.data.get("note","")
        a.resolved_at = timezone.now()
        a.save()
        a.conversation.status = "open"
        a.conversation.save(update_fields=["status"])
        return Response({"ok": True})


router = DefaultRouter()
router.register("", ApprovalViewSet, basename="approvals")
urlpatterns = router.urls
