import json, logging
import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)
_client = None

def _get_client():
    global _client
    if not _client:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client

# Kept above the 1024-token cache minimum on purpose: a richer system prompt
# both improves classification accuracy AND lets Anthropic cache it across
# calls (90% input-token discount on cache hits — see cache_control below).
SYSTEM = """You are a freight dispatch email classifier for a US trucking company.
Respond ONLY with valid minified JSON — no prose, no markdown fences.

Output shape (exact keys, exact casing):
{"category":"LOAD","priority":"HIGH","summary":"max 10 words","confidence":0.9}

Categories (pick the single best fit):
- LOAD       — rate confirmations, load offers, dispatch instructions, BOLs, pickup/delivery, lumper, detention, TONU, layover, deadhead, lane, drop trailer
- DRIVER     — driver onboarding, CDL/license, orientation, W-9/1099, employment, application, recruiting (only when from a real recruiter)
- BILLING    — invoices, payments, factoring, quickpay, settlements, deductions, comcheck, EFS, fuel advance, remittance, accounts payable
- CLAIMS     — cargo claims, freight claims, damage, loss, shortage
- INSURANCE  — COI, liability, coverage, endorsement, policy, underwriting, certificate requests
- SAFETY     — accidents, violations, drug/alcohol tests, crashes, hazmat, DOT physical, MVR, incident reports
- AUDIT      — FMCSA audit, DOT audit, compliance review, CSA score, inspection, out-of-service
- GENERAL    — anything that does not clearly fit above (real human follow-ups, status checks, etc.)

Priorities:
- HIGH    — same-day action required: rate cons, load offers with deadlines, audits, accidents, OOS, claims under deadline
- MEDIUM  — 24-48h action: invoices, COI requests, driver paperwork, factoring follow-ups
- LOW     — informational only, no action expected

Tie-breakers:
- A LOAD that needs same-day pickup/delivery is HIGH even if the sender is friendly.
- A BILLING reminder with a due date inside 7 days is MEDIUM, not LOW.
- Generic mass-mailers (newsletters, promotional offers, marketing blasts) should be GENERAL/LOW with low confidence — the upstream noise filter usually catches these before you see them.

Summary rules:
- ≤ 10 words, written as a directive ("Confirm pickup Tue 8am Dallas")
- Never echo the subject verbatim
- No quotes, no trailing punctuation"""


def run_classification(from_email, subject, body):
    if not settings.ANTHROPIC_API_KEY:
        return _fallback(subject, body, from_email)

    # Token savings — never spend an LLM call on obvious marketing/auto-mail.
    # `is_noise` already handles List-Unsubscribe headers, marketing keyword
    # subjects, and noreply@-style senders.
    if is_noise(from_email, subject, body):
        return _fallback(subject, body, from_email)

    user_prompt = (
        f"From: {from_email}\n"
        f"Subject: {subject}\n\n"
        f"Body:\n{(body or '')[:600]}"
    )
    try:
        msg = _get_client().messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=160,
            # System as a content block with cache_control so the (large) instructions
            # block is cached across the inbox burst and we only pay for the per-email
            # user turn after the first call.
            system=[
                {
                    "type": "text",
                    "text": SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        r = json.loads(raw)
        r["category"]   = r.get("category", "GENERAL").upper()
        r["priority"]   = r.get("priority", "MEDIUM").upper()
        r["summary"]    = r.get("summary", subject)[:120]
        r["confidence"] = float(r.get("confidence", 0.9))
        r["model"]      = settings.ANTHROPIC_MODEL
        if r["category"] not in ("LOAD", "DRIVER", "BILLING", "CLAIMS", "INSURANCE", "SAFETY", "AUDIT", "GENERAL"):
            r["category"] = "GENERAL"
        if r["priority"] not in ("HIGH", "MEDIUM", "LOW"):
            r["priority"] = "MEDIUM"
        return r
    except Exception as e:
        logger.warning("classify error: %s", e)
        return _fallback(subject, body, from_email)

def generate_draft(from_email, subject, snippet, company_name, mc_number, instruction=""):
    if not settings.ANTHROPIC_API_KEY:
        return f"Dear {from_email},\n\nThank you for your email regarding \"{subject}\". We will review and respond shortly.\n\nBest regards,\n{company_name} ({mc_number})"
    prompt = f"Company: {company_name} ({mc_number})\nReply to: {from_email}\nSubject: {subject}\nContext: {snippet}\nInstruction: {instruction or 'Write a professional reply.'}\n\nWrite only the email body, no subject line."
    try:
        msg = _get_client().messages.create(
            # Drafts use the bigger model — writing a reply needs more care than
            # picking a category. Override via ANTHROPIC_DRAFT_MODEL env.
            model=getattr(settings, "ANTHROPIC_DRAFT_MODEL", settings.ANTHROPIC_MODEL),
            max_tokens=600,
            system="You are a professional freight dispatcher. Write concise professional email replies.",
            messages=[{"role":"user","content":prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.error("draft error: %s", e)
        raise

NOISE_SUBJECT_KEYWORDS = [
    "unsubscribe", "newsletter", "promotion", "promo code", "special offer",
    "webinar", "download our", "free trial", "join us", "save up to",
    "% off", "discount", "marketing", "announcing", "introducing",
    "whitepaper", "ebook", "case study", "recruiting",
    "now recruiting", "apply now", "job opening", "we're hiring",
    "home upgrades", "renew your standard carrier",
    "time to renew", "your account is renewing",
    # Insurance/service spam
    "agents are standing by", "standing by to help save",
    "affordable trucking insurance", "lower your truck insurance",
    "dependable trucking coverage", "without breaking the",
    "start your policy with just", "activate your policy",
    "does your trucking insurance", "trucking is our business",
    "policy on renewal", "insurance you can count on",
    "get faster commercial insurance", "renewal quot",
    "save 20% on your coverage", "let's lower your",
    "pre-approved for a line of credit",
    # Safety/audit spam
    "want to learn ways to lower", "free driver safety course",
    "fleets are cutting accidents", "crash-for-cash scams",
    "new checks. bigger risks", "are your driver files audit",
    # General marketing
    "clearance", "biggest savings inside", "deals are live",
    "don't miss this", "you're invited",
    "making some changes to our", "legal agreement",
    "turn heads every time", "get show-ready",
    "zero emission vehicle workshop", "inside mats",
    "is back september", "relaycon",
    "habits of the most fuel-efficient",
    "group health coverage",
    "the math on fleet accidents",
    "fuel costs are rising",
    "not happy with your current factor",
    "get booked faster",
    "question tsegai", "question debretsion",
    # Billing spam (factoring/finance marketing)
    "fuel prices are out of your hands",
    "apex makes factoring simple",
    "need your certificate of insurance? get it online",
    # Rate report / market updates (informational, not actionable)
    "next day rate report",
    "q1 2026 trucking market update",
    "available loads",  # generic "available loads" blast emails
    "booking loads on tfx",
    "power only auctions update",
]

NOISE_FROM_PATTERNS = [
    "noreply", "no-reply", "donotreply", "do-not-reply",
    "marketing@", "newsletter@", "news@", "updates@",
    "notifications@", "notify@", "info@", "announce@",
    "offers@", "deals@", "promo@", "hello@", "team@",
    "mailer-daemon", "postmaster@",
]


def is_noise(from_email, subject, body=""):
    """Return True if the email is promotional/noise and should be ignored for alerts."""
    f = (from_email or "").lower()
    s = (subject or "").lower()
    if any(p in f for p in NOISE_FROM_PATTERNS):
        return True
    if any(k in s for k in NOISE_SUBJECT_KEYWORDS):
        return True
    # List-Unsubscribe body indicator (common in marketing emails)
    if "unsubscribe" in (body or "").lower()[:2000] and "view in browser" in (body or "").lower()[:2000]:
        return True
    return False


def _fallback(subject, body="", from_email=""):
    """Keyword-based classification — free, instant, no API call."""
    if is_noise(from_email, subject, body):
        return {"category":"NOISE","priority":"LOW","summary":subject[:80],"confidence":0.9,"model":"keyword"}
    s = (subject + " " + body[:500]).lower()
    if any(k in s for k in ["rate conf","rate confirmation","load offer","load #","load board",
        "pickup","delivery","bol","bill of lading","freight","dispatch","truck order",
        "load tracking","shipment","carrier packet","broker","deadhead","lane",
        "drop trailer","lumper","detention","tonu","layover"]): cat,pri = "LOAD","HIGH"
    elif any(k in s for k in ["audit","fmcsa","dot audit","compliance review","csa score",
        "inspection","out of service","oos"]): cat,pri = "AUDIT","HIGH"
    elif any(k in s for k in ["safety","accident","violation","incident","drug test",
        "alcohol test","crash","hazmat","dot physical","mvr"]): cat,pri = "SAFETY","HIGH"
    elif any(k in s for k in ["claim","damage","cargo claim","freight claim","loss",
        "shortage"]): cat,pri = "CLAIMS","MEDIUM"
    elif any(k in s for k in ["invoice","payment","billing","accounts payable","remittance",
        "factoring","quickpay","pay stub","settlement","deduction","comcheck",
        "efs","fuel advance"]): cat,pri = "BILLING","MEDIUM"
    elif any(k in s for k in ["insurance","certificate","coi","liability","coverage",
        "endorsement","policy","underwriting"]): cat,pri = "INSURANCE","MEDIUM"
    elif any(k in s for k in ["driver","cdl","license","onboarding","orientation",
        "application","w-9","1099","employment"]): cat,pri = "DRIVER","LOW"
    else: cat,pri = "GENERAL","LOW"
    return {"category":cat,"priority":pri,"summary":subject[:80],"confidence":0.7,"model":"keyword"}


def classify_fast(from_email, subject, body=""):
    """Instant keyword-based classification — no API cost, no async delay."""
    return _fallback(subject, body, from_email)
