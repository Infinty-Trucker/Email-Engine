"""Match a Message against MailRules and run actions.

Hooked into the ingest pipeline in ``apps/mailboxes/tasks.py`` right after
the classifier. Synchronous for now — keeps things debuggable; if the
action set grows expensive (multi-second HTTP calls), we'll wrap this in a
Celery task instead.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from apps.automations.actions import ACTION_REGISTRY, ActionResult
from apps.automations.models import MailRule, MailRuleExecution
from apps.conversations.models import Message

logger = logging.getLogger(__name__)


def dispatch_message(message: Message) -> list[MailRuleExecution]:
    """Evaluate every enabled rule against this message; run matching ones."""
    rules = _candidate_rules(message)
    executions: list[MailRuleExecution] = []
    for rule in rules:
        if not _matches(rule, message):
            continue
        handler = ACTION_REGISTRY.get(rule.action)
        if handler is None:
            logger.warning(
                "MailRule %s references unknown action %r; skipping.",
                rule.id, rule.action,
            )
            continue

        # Idempotency: already executed for this message?
        existing = MailRuleExecution.objects.filter(
            rule=rule, message=message
        ).first()
        if existing and existing.status == MailRuleExecution.STATUS_SUCCESS:
            continue

        try:
            result: ActionResult = handler(rule, message)
        except Exception as exc:
            logger.exception("Action handler crashed: rule=%s msg=%s", rule.id, message.id)
            result = ActionResult(
                status=MailRuleExecution.STATUS_FAILED,
                error=f"Handler crashed: {type(exc).__name__}: {exc}",
            )

        ex, _ = MailRuleExecution.objects.update_or_create(
            rule=rule, message=message,
            defaults={
                "status": result.status,
                "response_summary": result.summary,
                "error": result.error,
            },
        )
        executions.append(ex)
    return executions


def dispatch_by_message_id(message_id: str) -> None:
    """Used by callers that only have the id (e.g. a Celery task wrapper)."""
    msg = Message.objects.filter(id=message_id).first()
    if msg is None:
        return
    dispatch_message(msg)


# --- matching ---------------------------------------------------------------

def _candidate_rules(message: Message) -> Iterable[MailRule]:
    """Tenant-scoped + global rules, enabled only."""
    mc = message.conversation.mc_number or ""
    qs = MailRule.objects.select_related("company").filter(enabled=True)
    if mc:
        qs = qs.filter(models_Q_or(
            company__isnull=True,
            company__mc_number=mc,
        ))
    else:
        qs = qs.filter(company__isnull=True)
    return list(qs)


def _matches(rule: MailRule, message: Message) -> bool:
    if not _regex_match(rule.sender_pattern, message.sender_email):
        return False
    if rule.subject_pattern and not _regex_match(rule.subject_pattern, message.subject):
        return False
    if rule.require_attachment:
        atts = message.attachments.all()
        if not atts.exists():
            return False
        if rule.attachment_mime_prefix:
            if not atts.filter(mime_type__istartswith=rule.attachment_mime_prefix).exists():
                return False
    return True


def _regex_match(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value or "", re.IGNORECASE) is not None
    except re.error as exc:
        logger.warning("Invalid regex %r in MailRule: %s", pattern, exc)
        return False


# Tiny helper so the Q building above stays readable. Django's Q lives in
# django.db.models — pulled in lazily here to avoid an extra import in the
# module's hot path.
def models_Q_or(**kwargs):
    from django.db.models import Q

    q = Q()
    for k, v in kwargs.items():
        q |= Q(**{k: v})
    return q
