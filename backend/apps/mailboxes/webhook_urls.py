import base64, json, logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.urls import path

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def gmail_push(request):
    try:
        envelope     = json.loads(request.body)
        data_encoded = envelope.get("message", {}).get("data", "")
        if not data_encoded:
            return HttpResponse(status=204)
        data          = json.loads(base64.b64decode(data_encoded))
        email_address = data.get("emailAddress")
        history_id    = str(data.get("historyId", ""))
        if email_address and history_id:
            from apps.mailboxes.tasks import process_gmail_push
            process_gmail_push.delay(email_address, history_id)
    except Exception as e:
        logger.error("gmail_push error: %s", e)
    return HttpResponse(status=200)

urlpatterns = [path("", gmail_push)]
