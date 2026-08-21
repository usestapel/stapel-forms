"""The single authorization choke point for the admin surface.

Every access decision about a form or its responses routes through
:func:`authorize` — there is no second read path. The public respondent
endpoints (§5.1) are deliberately outside it: they are ``AllowAny`` by
design and gated by the abuse ladder instead, which is why the public
presenter is a dedicated envelope and not the admin one with fields
dropped.

``unavailable`` means the workspaces service rendered no verdict — callers
answer 503, never 403 ("a routing 404 is not a verdict", stapel-core
workspaces client canon).

Known limitation, stated rather than papered over: on stapel-core 0.26
``require_capability`` collapses "denied" and "peer unavailable" into the
same ``None`` — it logs the outage and returns, so the branch below can
only fire if a future core raises. Until that core PR lands, a workspaces
outage renders 403 here, the same as in stapel-docs. The branch stays live
because the fix belongs in core, not in a per-module workaround that would
re-implement the capability call and its cache.

The :class:`Principal` form is fixed on day 1 so anonymous-link style
grants later are an additive branch, not a rewrite: ``user_id=None`` means
no session at all; ``is_anonymous`` marks an anonymous ACCOUNT of the auth
axis (which does have a user_id); ``link_token`` carries a presented bearer
token, unused by the admin surface.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

ALLOW = "allow"
DENY = "deny"
UNAVAILABLE = "unavailable"

#: Actions and the workspace capability answering each.
ACTION_CAPABILITIES = {
    "view": "forms.view",
    "manage": "forms.manage",
    "responses.view": "forms.responses.view",
    "responses.manage": "forms.responses.manage",
}

#: Declared in full on day 1 so host role overlays never have to migrate.
#: There is deliberately no separate ``forms.responses.export``: an export
#: is a read, and core's staff mandate grades view/add/change/delete only.
CAPABILITIES = (
    "forms.view",
    "forms.manage",
    "forms.responses.view",
    "forms.responses.manage",
)


@dataclass(frozen=True)
class Principal:
    """Who is asking. Built by the view layer, consumed only here."""

    user_id: Optional[UUID]
    is_anonymous: bool = False
    link_token: Optional[str] = None

    @classmethod
    def from_request(cls, request) -> "Principal":
        user = getattr(request, "user", None)
        user_id = getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
        is_anon = bool(getattr(user, "is_anonymous_account", False))
        return cls(user_id=user_id, is_anonymous=is_anon, link_token=None)


def authorize(*, workspace_id, principal: Principal, action: str) -> str:
    """Decide *action* for *principal* on *workspace_id*.

    Returns ``allow`` | ``deny`` | ``unavailable``.
    """
    if action not in ACTION_CAPABILITIES:
        raise ValueError(f"unknown forms action: {action!r}")

    if principal.user_id is not None:
        from stapel_core.django.workspaces import (
            WorkspaceLookupUnavailable,
            require_capability,
        )

        try:
            membership = require_capability(
                workspace_id, principal.user_id, ACTION_CAPABILITIES[action]
            )
        except WorkspaceLookupUnavailable:
            return UNAVAILABLE
        if membership is not None:
            return ALLOW

    return DENY


__all__ = [
    "ALLOW",
    "DENY",
    "UNAVAILABLE",
    "ACTION_CAPABILITIES",
    "CAPABILITIES",
    "Principal",
    "authorize",
]
