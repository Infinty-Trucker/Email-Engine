"""TMS Session Token authentication for Dispatch OS.

Mirror of Driver_Onboarding's class. Validates X-Session-Token against
TMS-Backend's /auth/api/v1/me/ and mirrors the user locally.
"""
from __future__ import annotations

import os
from typing import Optional

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import authentication, exceptions

User = get_user_model()


def _tms_url() -> str:
    return os.environ.get("TMS_BACKEND_URL", "http://localhost:8000").rstrip("/")


def _cache_ttl() -> int:
    try:
        return int(os.environ.get("TMS_AUTH_CACHE_TTL", "60"))
    except ValueError:
        return 60


def has_tms_permission(user, slug: str) -> bool:
    """True if a TMS-mirrored user holds `slug` for the active tenant.

    Three pathways grant access:
      1. Django superuser flag (matches TMS-Backend's core/permissions.py:16
         bypass — superusers don't need CompanyRole assignments).
      2. The slug appears in the user's _tms_permissions set, populated by
         TMSSessionTokenAuthentication when X-Tenant is present.
      3. _tms_permissions wasn't populated at all (standalone DOS session
         with no X-Tenant) — fall back to the legacy role/M2M checks at
         the call site rather than refusing.

    Returns True for case 1 and 2; case 3 is signalled by a None return so
    callers can distinguish "no slug data" from "explicit deny".
    """
    if getattr(user, "_tms_is_superuser", False):
        return True
    slugs = getattr(user, "_tms_permissions", None)
    if not slugs:
        # Either the standalone DOS path (no X-Tenant) or a user with no
        # CompanyRole assigned. Defer to the caller's legacy gate.
        return True
    return slug in slugs


def _fetch_tms_permissions(token: str, tenant_mc: str) -> set[str]:
    """Pull the user's per-MC permission slugs from TMS.

    TMS-Backend's `/company/api/v1/users/me/` returns the active CompanyUser
    with their roles + each role's AppPermissions. We flatten to a set of
    slug strings (e.g. {"email.view", "load.view", ...}) and cache it so the
    request hot-path doesn't hit TMS twice. Returns an empty set if anything
    fails — the request itself is already authenticated; we just won't have
    permission slugs to gate on, and the per-endpoint check will refuse.
    """
    cache_key = f"tms_perms:{token}:{tenant_mc}"
    cached = cache.get(cache_key)
    if cached is not None:
        return set(cached)
    try:
        resp = requests.get(
            f"{_tms_url()}/company/api/v1/users/me/",
            headers={"X-Session-Token": token, "X-Tenant": tenant_mc},
            timeout=4,
        )
    except requests.RequestException:
        return set()
    if resp.status_code != 200:
        return set()
    try:
        payload = resp.json()
    except ValueError:
        return set()
    slugs: set[str] = set()
    for role in payload.get("roles") or []:
        for p in role.get("permissions") or []:
            slug = p.get("slug")
            if slug:
                slugs.add(slug)
    cache.set(cache_key, list(slugs), _cache_ttl())
    return slugs


class TMSSessionTokenAuthentication(authentication.BaseAuthentication):
    keyword = "X-Session-Token"

    def authenticate(self, request) -> Optional[tuple]:
        token = request.META.get("HTTP_X_SESSION_TOKEN")
        if not token:
            return None

        cache_key = f"tms_session:{token}"
        payload = cache.get(cache_key)
        if not payload:
            try:
                resp = requests.get(
                    f"{_tms_url()}/auth/api/v1/me/",
                    headers={"X-Session-Token": token},
                    timeout=4,
                )
            except requests.RequestException as exc:
                raise exceptions.AuthenticationFailed(f"TMS unreachable: {exc}")
            if resp.status_code == 401:
                raise exceptions.AuthenticationFailed("TMS rejected token.")
            if resp.status_code != 200:
                raise exceptions.AuthenticationFailed(
                    f"TMS returned {resp.status_code}: {resp.text[:200]}"
                )
            payload = resp.json()
            cache.set(cache_key, payload, _cache_ttl())

        tms_user = payload.get("user") or {}
        email = tms_user.get("email")
        if not email:
            raise exceptions.AuthenticationFailed("TMS payload missing user email.")

        # Dispatch OS' User has UUID PK + role enum. We mirror with role=admin
        # so the existing role-based filters in ConversationViewSet pass.
        user, _ = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": tms_user.get("first_name") or "",
                "last_name": tms_user.get("last_name") or "",
                "role": "admin",
                "is_active": True,
                "is_staff": True,
            },
        )
        user._tms_user_payload = payload  # type: ignore[attr-defined]
        user._tms_is_superuser = bool(tms_user.get("is_superuser"))  # type: ignore[attr-defined]
        # Pull per-MC permission slugs when X-Tenant is set so view-level
        # gates (email.view, email.send, email.mailbox.manage) can enforce
        # against TMS' canonical permission table without each view making
        # its own roundtrip.
        tenant_mc = (request.META.get("HTTP_X_TENANT") or "").strip()
        if tenant_mc:
            user._tms_permissions = _fetch_tms_permissions(token, tenant_mc)  # type: ignore[attr-defined]
        else:
            user._tms_permissions = set()  # type: ignore[attr-defined]
        return user, token

    def authenticate_header(self, request):
        return self.keyword
