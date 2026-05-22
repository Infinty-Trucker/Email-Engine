# automations — Mail-rule automations

A tiny rule engine that watches inbound mail and runs a named action when a
message matches sender + subject + (optionally) attachment pattern. Today
there is one production rule — **Phoenix Capital factoring schedule
auto-import** — and the framework is intentionally small so adding the next
rule is just (a) a regex row in DB, (b) a function in `actions.py`.

The classifier (`apps/classifier`) already does *post-hoc* AI categorization
of every inbound message. This app is different: it's *triggered* —
specific patterns fire deterministic side effects (HTTP calls, file
forwards, DB writes) rather than categorize content.

---

## Lifecycle

```
Gmail Pub/Sub push  →  apps/mailboxes/tasks.py:ingest_from_settings
                              │
                              │   Message + Attachment rows committed
                              │   Classifier runs (post-hoc AI categorize)
                              ▼
                       dispatch_message(msg)         ← apps/automations/dispatcher.py
                              │
                              ├── filter MailRule.objects.filter(enabled=True)
                              ├── regex-match sender + subject
                              ├── require_attachment + mime check
                              ▼
                       ACTION_REGISTRY[rule.action](rule, msg)
                              │
                              ▼
                       MailRuleExecution row written (success / failed / skipped)
```

The hook lives at the tail of `ingest_from_settings()` in
`apps/mailboxes/tasks.py`. Exceptions in the dispatcher are logged but do
not unwind the ingest — the message is already persisted by the time we
get here, and a missed automation is a soft failure (the user can re-run
it from the admin or upload the PDF manually).

---

## Data model

* **`MailRule`** — `(company, name, sender_pattern, subject_pattern,
  require_attachment, attachment_mime_prefix, action, action_config,
  enabled)`. `company=NULL` means a *global* rule that applies to every
  tenant's mailboxes. Per-tenant rules are scoped via the conversation's
  denormalized `mc_number`.
* **`MailRuleExecution`** — append-only audit log: one row per
  (rule, message) attempt. `unique_together(rule, message)` makes retries
  idempotent (re-running just updates the existing row).

---

## Adding a new rule

1. Add an entry to `MailRule.ACTION_CHOICES` (slug, label).
2. Implement the handler in `actions.py`:
   ```python
   def my_new_action(rule: MailRule, message: Message) -> ActionResult:
       ...
       return ActionResult(status=MailRuleExecution.STATUS_SUCCESS, summary="...")
   ```
3. Register it in `ACTION_REGISTRY`.
4. Create the rule row — either via Django admin, an API POST, or a data
   migration (see `0002_seed_phoenix_capital_rule.py` for the data-migration
   pattern).

The dispatcher uses `re.IGNORECASE`; sender pattern is matched against the
full email, subject against the full subject. Both are `re.search`, not
`re.fullmatch` — anchor with `^…$` if you want strict matching (the
seeded Phoenix Capital rule does).

---

## The Phoenix Capital rule (seeded)

Migration `0002_seed_phoenix_capital_rule.py` plants one **global** rule:

| field                      | value                                                   |
| -------------------------- | ------------------------------------------------------- |
| `sender_pattern`           | `^mailrelay@phoenixcapitalgroup\.com$`                  |
| `subject_pattern`          | `^\s*Schedule\s*#\s*\d+\s*$`                            |
| `require_attachment`       | `True`                                                  |
| `attachment_mime_prefix`   | `application/pdf`                                       |
| `action`                   | `phoenix_capital_schedule`                              |
| `enabled`                  | `True`                                                  |

The matching action (`actions.py:phoenix_capital_schedule`) does:

1. Resolve the tenant `mc_no` (rule.company first, falling back to the
   message's conversation `mc_number`).
2. Pick the first PDF attachment on the message. Lazy-download from Gmail
   if it hasn't been downloaded locally yet — same pattern as
   `apps/conversations/urls.py:attachment_download`.
3. POST the bytes to TMS-Backend at
   `POST {TMS_BACKEND_URL}/factoring/api/v1/ingest-email/` with:
   * `X-Service-Token: <shared secret>` (see below)
   * `mc_no`, `message_id` form fields
   * `file` multipart part
4. Persist a `MailRuleExecution` row with TMS's reported summary
   (`matched / unmatched / short_paid / exceptions`).

---

## `FACTORING_INGEST_TOKEN` — what it is, why it exists

The TMS endpoint we POST to has no user session — it's a Celery worker
reaching across services, not a person clicking a button. The standard
`X-Session-Token + X-Tenant` auth used everywhere else doesn't apply.

Instead, both services hold the **same shared secret**, and Email-Engine
sends it as `X-Service-Token`. TMS-Backend compares it constant-time
against its own `settings.FACTORING_INGEST_TOKEN`:

* match → request proceeds, schedule is parsed and applied
* mismatch / missing → TMS returns 403, the action handler records
  `failed` with the response body in `MailRuleExecution.error`

This is a deliberate keep-it-simple choice over a full OAuth client-credentials
flow: the call only ever happens between two services we own, the secret
is rotated by env redeploy on both sides, and the gates are auditable
(every attempt produces a row in `MailRuleExecution`).

### Setup checklist

1. Generate a value:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. Set it in **both** `.env` files (must be byte-identical):
   * `Email-Engine/.env` → `FACTORING_INGEST_TOKEN=…`
   * `TMS-Backend/.env`  → `FACTORING_INGEST_TOKEN=…`
3. Set `TMS_BACKEND_URL` in `Email-Engine/.env` so the dispatcher knows
   where to POST. Defaults to `http://localhost:8000`.
4. Restart both services.

### Failure modes

| condition                                        | result                                                    |
| ------------------------------------------------ | --------------------------------------------------------- |
| `FACTORING_INGEST_TOKEN` unset on Email-Engine   | Handler short-circuits, logs `not configured`, records `failed`. |
| `FACTORING_INGEST_TOKEN` unset on TMS-Backend    | Every POST returns 403. Look in `MailRuleExecution.error`.|
| Values differ between services                   | Same as above — 403.                                      |
| `TMS_BACKEND_URL` wrong / unreachable            | `requests.RequestException`, recorded with the URL in error. |
| PDF can't be downloaded from Gmail               | `MailRuleExecution.status = failed` with Gmail error.     |
| Schedule PDF doesn't parse (wrong format)        | TMS returns 400 with parser error in `detail`. Logged.    |

Every failure has a row to debug from. Surface them in Django admin under
**Mail rule executions** filtered by `status = failed`.

---

## Rotating

Set the new value on both services at once. There is a brief window
(seconds) during a rolling restart where one service has the new token
and the other has the old — inbound emails during that window will
record `failed` rows. Resolve by either:

* Re-running the rule from Django admin (TODO — admin action not yet
  wired; for now the easiest path is to upload the PDF manually from
  the consolidated UI at `/factoring/schedules`).
* Re-importing the email (Gmail keeps it; just delete the
  `MailRuleExecution` row and re-process).

---

## Why this lives in its own app

The classifier categorizes; this app *acts*. Keeping them split means:

* the classifier stays a pure-text concern (cheap, idempotent),
* automations stay an integration concern (HTTP calls, retries, env vars),
* a misbehaving rule never blocks ingest or classification.

If automations grows to >5 rules with shared concerns (rate limiting,
retries, scheduling), promote `dispatch_message` to a Celery task and
move the action handlers behind an interface. For now, synchronous calls
keep debugging trivial.
