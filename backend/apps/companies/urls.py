import logging
from rest_framework import serializers, viewsets
from rest_framework.routers import DefaultRouter
from rest_framework.decorators import action
from rest_framework.response import Response
from django.urls import path
from .models import Company

logger = logging.getLogger(__name__)


def _get_slack_client():
    """Get a Slack WebClient using bot token from DB or env."""
    from apps.notifications.tasks import _get_slack_token
    token = _get_slack_token()
    if not token:
        return None
    from slack_sdk import WebClient
    return WebClient(token=token)


def _create_slack_channel(client, name):
    """Create a Slack channel and return its ID, or return existing channel ID."""
    try:
        resp = client.conversations_create(name=name, is_private=False)
        return resp["channel"]["id"]
    except Exception as e:
        err = str(e)
        # Channel already exists — look it up
        if "name_taken" in err:
            try:
                from apps.notifications.tasks import _resolve_channel
                return _resolve_channel(client, name)
            except Exception:
                pass
        logger.warning("Could not create Slack channel %s: %s", name, e)
        return None


def auto_create_company_channels(company):
    """Auto-create load-ops and paperwork-ops Slack channels for a company."""
    client = _get_slack_client()
    if not client:
        return {"load_ops": None, "paperwork_ops": None, "error": "No Slack bot token configured"}

    results = {}
    for suffix, id_field, name_field in [
        ("load-ops", "slack_channel_loads_id", "slack_channel_loads_name"),
        ("paperwork-ops", "slack_channel_paperwork_id", "slack_channel_paperwork_name"),
    ]:
        channel_name = f"{company.slug}-{suffix}"
        channel_id = _create_slack_channel(client, channel_name)
        if channel_id:
            setattr(company, id_field, channel_id)
            setattr(company, name_field, channel_name)
            results[suffix] = {"id": channel_id, "name": channel_name}
        else:
            results[suffix] = None

    company.save(update_fields=[
        "slack_channel_loads_id", "slack_channel_loads_name",
        "slack_channel_paperwork_id", "slack_channel_paperwork_name",
    ])
    return results


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer

    def perform_create(self, serializer):
        company = serializer.save()
        # Auto-create Slack channels for new companies
        try:
            auto_create_company_channels(company)
        except Exception as e:
            logger.warning("Auto-create Slack channels failed for %s: %s", company.name, e)

    @action(detail=True, methods=["post"], url_path="create-slack-channels")
    def create_slack_channels(self, request, pk=None):
        """Manually trigger Slack channel creation for an existing company."""
        company = self.get_object()
        results = auto_create_company_channels(company)
        if "error" in results:
            return Response({"error": results["error"]}, status=400)
        return Response({
            "ok": True,
            "channels": results,
            "load_ops": company.slack_channel_loads_name,
            "paperwork_ops": company.slack_channel_paperwork_name,
        })


router = DefaultRouter()
router.register("", CompanyViewSet, basename="companies")
urlpatterns = router.urls
