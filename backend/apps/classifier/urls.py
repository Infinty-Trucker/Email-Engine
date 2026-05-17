from django.urls import path
from rest_framework import serializers, generics
from .models import ComplianceScan
from apps.conversations.models import Message


class ComplianceScanSerializer(serializers.ModelSerializer):
    subject     = serializers.CharField(source="message.subject", read_only=True)
    sender      = serializers.CharField(source="message.sent_by.get_full_name", read_only=True)
    company     = serializers.CharField(source="message.conversation.mailbox.company.name", read_only=True)
    body_preview = serializers.SerializerMethodField()

    def get_body_preview(self, obj):
        return obj.message.body_text[:300]

    class Meta:
        model  = ComplianceScan
        fields = ["id","subject","sender","company","risk_level","flags",
                  "recommendation","is_clean","scanned_at","body_preview"]


class ComplianceScanList(generics.ListAPIView):
    serializer_class = ComplianceScanSerializer

    def get_queryset(self):
        return ComplianceScan.objects.select_related(
            "message__sent_by",
            "message__conversation__mailbox__company",
        ).order_by("-scanned_at")


urlpatterns = [
    path("", ComplianceScanList.as_view()),
]
