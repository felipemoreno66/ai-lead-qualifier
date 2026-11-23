"""Bearer-token authentication for the admin and internal routers."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header

from lead_qualifier.domain.errors import Forbidden, Unauthorized
from lead_qualifier.http.deps import SettingsDep


def _check(authorization: str | None, expected: str) -> None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("Missing bearer token.", headers={"WWW-Authenticate": "Bearer"})
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise Forbidden("Invalid token.")


def _dependency(secret_name: str) -> Callable[..., None]:
    def dependency(
        settings: SettingsDep, authorization: Annotated[str | None, Header()] = None
    ) -> None:
        _check(authorization, getattr(settings, secret_name))

    return dependency


require_admin = Depends(_dependency("admin_api_token"))
require_n8n = Depends(_dependency("n8n_api_token"))
