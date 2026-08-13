"""Loopback-only admin API for ops-console Product Ops.

Guards the access-request decision endpoint with a bearer token. The token is
read from ADMIN_API_TOKEN and must be >=32 chars; unset or short disables the
surface entirely (fail-closed).
"""

from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import config
from .access_store import AccessStore

router = APIRouter(prefix="/api/admin")
ACCESS = AccessStore(config.AUTH_DB_PATH)


def _verify_admin_token(request: Request) -> bool:
    expected = config.ADMIN_API_TOKEN
    if not expected or len(expected) < 32:
        return False
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return False
    presented = header[7:]
    return hmac.compare_digest(
        hashlib.sha256(presented.encode()).digest(),
        hashlib.sha256(expected.encode()).digest(),
    )


@router.post("/access-requests/{request_id}/decision", include_in_schema=False)
async def decide(request: Request, request_id: str) -> JSONResponse:
    if not _verify_admin_token(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    decision = body.get("decision") if body else None
    if decision not in ("approve", "deny"):
        return JSONResponse({"error": "decision must be 'approve' or 'deny'"}, status_code=400)
    operator = body.get("operator")
    if isinstance(operator, str):
        operator = operator[:320]
    else:
        operator = None
    result = ACCESS.decide(request_id, decision, operator)
    if result is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"id": request_id, "status": result})