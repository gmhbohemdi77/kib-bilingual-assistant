"""
Entra ID (Azure AD) authentication for the Streamlit app — Phase 5.3 + 5.4.

Uses MSAL's authorization-code-with-PKCE flow:
  1. Streamlit app shows a "Sign in with Microsoft" link.
  2. User authenticates with KIB Entra ID, comes back with `?code=...`.
  3. We exchange the code for an access token + ID token.
  4. We read the user's group membership from the ID token claims to decide
     their role: AI Trainer (sees the admin panel) vs Regular Employee.

Notes for the App Registration in Entra ID:
  * Platform: "Web", redirect URI = your Streamlit URL (e.g.
    https://kib-assistant.azurewebsites.net/ for prod, http://localhost:8501/
    for local dev).
  * API permissions: Microsoft Graph -> User.Read (delegated). That's enough.
  * Token configuration: add an optional claim of type "groups" with
    "Group ID" so the ID token carries `groups`.
  * Create a security group called "KIB AI Trainers" in Entra ID and put
    its Object ID in the AI_TRAINER_GROUP_IDS env var.

If you can't get groups added (e.g. tenant has too many groups, the token
falls back to a `_claim_names` overage), this module also accepts an
explicit AI_TRAINER_USER_OIDS env var as a comma-separated allow-list.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import msal

from .config import settings


# Roles —----------------------------------------------------------------------

ROLE_AI_TRAINER = "ai_trainer"
ROLE_EMPLOYEE = "employee"

_GRAPH_SCOPE = ["User.Read"]


@dataclass
class AuthenticatedUser:
    oid: str          # Entra ID object ID — stable across name changes
    email: str
    display_name: str
    role: str         # ROLE_AI_TRAINER or ROLE_EMPLOYEE
    raw_claims: dict[str, Any]

    @property
    def is_trainer(self) -> bool:
        return self.role == ROLE_AI_TRAINER


# MSAL helpers ----------------------------------------------------------------


def _msal_app() -> msal.ConfidentialClientApplication:
    if not (settings.tenant_id and settings.client_id and settings.client_secret):
        raise RuntimeError(
            "Entra ID is not configured. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, "
            "and AZURE_CLIENT_SECRET in your environment."
        )
    authority = f"https://login.microsoftonline.com/{settings.tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=settings.client_id,
        client_credential=settings.client_secret,
        authority=authority,
    )


def build_login_url(state: str) -> str:
    app = _msal_app()
    return app.get_authorization_request_url(
        scopes=_GRAPH_SCOPE,
        state=state,
        redirect_uri=settings.redirect_uri,
    )


def exchange_code(code: str) -> AuthenticatedUser | None:
    app = _msal_app()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=_GRAPH_SCOPE,
        redirect_uri=settings.redirect_uri,
    )
    if "id_token_claims" not in result:
        return None

    claims = result["id_token_claims"]
    return _user_from_claims(claims)


# Role resolution -------------------------------------------------------------


def _trainer_group_ids() -> set[str]:
    raw = settings.ai_trainer_group_ids or ""
    return {gid.strip() for gid in raw.split(",") if gid.strip()}


def _trainer_user_oids() -> set[str]:
    raw = os.getenv("AI_TRAINER_USER_OIDS", "")
    return {oid.strip() for oid in raw.split(",") if oid.strip()}


def _resolve_role(claims: dict[str, Any]) -> str:
    user_oid = claims.get("oid", "")
    if user_oid in _trainer_user_oids():
        return ROLE_AI_TRAINER

    user_groups = set(claims.get("groups") or [])
    if user_groups & _trainer_group_ids():
        return ROLE_AI_TRAINER

    # If the token uses an "app role" claim instead, also accept that
    roles = set(claims.get("roles") or [])
    if "AITrainer" in roles or "ai_trainer" in roles:
        return ROLE_AI_TRAINER

    return ROLE_EMPLOYEE


def _user_from_claims(claims: dict[str, Any]) -> AuthenticatedUser:
    return AuthenticatedUser(
        oid=claims.get("oid", ""),
        email=claims.get("preferred_username") or claims.get("email", ""),
        display_name=claims.get("name", ""),
        role=_resolve_role(claims),
        raw_claims=claims,
    )


# Test / dev shim -------------------------------------------------------------


def dev_user(*, trainer: bool = False) -> AuthenticatedUser:
    """A fake user for local development when Entra ID isn't configured yet.

    Activated when the env var KIB_DEV_AUTH=1 is set.
    """
    return AuthenticatedUser(
        oid="dev-user-0001",
        email="dev@example.com",
        display_name="Dev User (Trainer)" if trainer else "Dev User (Employee)",
        role=ROLE_AI_TRAINER if trainer else ROLE_EMPLOYEE,
        raw_claims={"dev": True},
    )
