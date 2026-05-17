from django.urls import path
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(["GET"])
def slack_config(request):
    return Response({
        "bot_token_set": bool(settings.SLACK_BOT_TOKEN),
        "channels": {
            "safety_alerts": settings.SLACK_CHANNEL_SAFETY_ALERTS,
            "approvals":     settings.SLACK_CHANNEL_APPROVALS,
            "compliance":    settings.SLACK_CHANNEL_COMPLIANCE,
            "system":        settings.SLACK_CHANNEL_SYSTEM,
        }
    })


@api_view(["POST"])
def test_connection(request):
    if not settings.SLACK_BOT_TOKEN:
        return Response({"ok": False, "error": "No bot token configured"}, status=400)
    try:
        from slack_sdk import WebClient
        client = WebClient(token=settings.SLACK_BOT_TOKEN)
        result = client.auth_test()
        return Response({"ok": True, "team": result.get("team"), "bot": result.get("user")})
    except Exception as e:
        return Response({"ok": False, "error": str(e)}, status=400)


@api_view(["POST"])
def test_channel(request):
    from apps.notifications.tasks import post_to_slack
    key = request.data.get("channel_key")
    channel_map = {
        "safetyAlerts": settings.SLACK_CHANNEL_SAFETY_ALERTS,
        "approvals":    settings.SLACK_CHANNEL_APPROVALS,
        "compliance":   settings.SLACK_CHANNEL_COMPLIANCE,
        "system":       settings.SLACK_CHANNEL_SYSTEM,
    }
    ch = channel_map.get(key)
    if not ch:
        return Response({"ok": False, "error": "Channel not configured"}, status=400)
    ok = post_to_slack(ch, "✅ Test message from Dispatch OS")
    return Response({"ok": ok})


urlpatterns = [
    path("config/",          slack_config),
    path("test_connection/", test_connection),
    path("test_channel/",    test_channel),
]
