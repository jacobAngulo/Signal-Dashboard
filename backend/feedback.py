"""Authenticated same-origin relay for Ticket Board feedback intake."""

from __future__ import annotations

from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import auth, config

router = APIRouter(prefix="/api", tags=["feedback"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requester(StrictModel):
    name: str | None = Field(default=None, max_length=200)
    contact: str | None = Field(default=None, max_length=320)
    external_id: str | None = Field(default=None, max_length=200)


class Source(StrictModel):
    external_id: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    context: dict[str, Any] | None = None


class Feedback(StrictModel):
    kind: Literal["bug", "feature"]
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    requester: Requester | None = None
    source: Source | None = None


@router.post("/feedback")
async def submit_feedback(body: Feedback, request: Request):
    if not config.TICKET_BOARD_INTAKE_TOKEN:
        raise HTTPException(503, "feedback intake is not configured")

    session = auth.current_session(request)
    if not session:
        raise HTTPException(401, "sign in to continue")

    payload = body.model_dump(mode="json", exclude_none=True)
    supplied_requester = payload.get("requester") or {}
    payload["requester"] = {
        "name": supplied_requester.get("name"),
        "contact": session["email"],
        "external_id": session["subject"],
    }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{config.TICKET_BOARD_URL}/api/intake/{config.TICKET_BOARD_PROJECT_SLUG}",
                json=payload,
                headers={"Authorization": f"Bearer {config.TICKET_BOARD_INTAKE_TOKEN}"},
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, "feedback service is unavailable") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", "feedback was rejected")
        except (ValueError, AttributeError):
            detail = "feedback was rejected"
        raise HTTPException(response.status_code, detail)
    return response.json()
