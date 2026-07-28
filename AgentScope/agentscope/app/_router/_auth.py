# -*- coding: utf-8 -*-
"""Authentication endpoints for the AgentScope management WebUI."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from .._auth import (
    AgentScopeAuthConfig,
    issue_management_token,
    verify_management_credentials,
)


auth_router = APIRouter(prefix="/auth", tags=["Authentication"])


class ManagementLoginRequest(BaseModel):
    """Credentials for the independent AgentScope management account."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ManagementLoginResponse(BaseModel):
    """Bearer token returned after a successful management login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str


@auth_router.post(
    "/login",
    response_model=ManagementLoginResponse,
    summary="Log in to the AgentScope management console",
)
async def login(
    body: ManagementLoginRequest,
    request: Request,
) -> ManagementLoginResponse:
    """Authenticate the management account without creating a data owner."""
    config: AgentScopeAuthConfig | None = getattr(
        request.app.state,
        "auth_config",
        None,
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Management authentication is not configured.",
        )
    if not verify_management_credentials(
        config,
        body.username.strip(),
        body.password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = issue_management_token(config)
    return ManagementLoginResponse(
        access_token=token.access_token,
        expires_in=token.expires_in,
        username=config.admin_username,
    )
