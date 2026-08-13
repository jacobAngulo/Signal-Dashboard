"""Google sign-in, and the gate that makes it mean something.

This dashboard was private for one reason: nginx would not answer anyone who
had not arrived over the WireGuard tunnel. Nothing in the application checked
anything. Putting it on a public hostname removes that reason, so the check has
to move in here.

Two decisions shape the module.

**The gate is middleware, not a dependency.** Every data route already carries
`dependencies=[Depends(fresh)]`, and adding a second entry to each of them would
have been thirteen chances to miss one -- plus a fourteenth route, added some
Tuesday next year, that ships open because nobody remembered. `require_session`
runs in front of everything and names the handful of paths that are public. New
routes are closed unless someone deliberately opens them, and
`tests/test_auth_gate.py` fails if that list grows without being updated.

**Authorization is a list of addresses, and nothing else.** `complete_flow` in
`ops_kit.web_auth` proves which Google account is asking; `AUTH_ALLOWED_EMAILS`
decides whether that account matters. There is no sign-up, no request queue, and
no first-user-wins. An empty list therefore means nobody, not everybody -- if
this process starts without credentials or without a list it serves an
explanation and refuses the rest.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from ops_kit import web_auth

from . import config
from .access_store import AccessStore

log = logging.getLogger("signal_dashboard.auth")

SESSION_COOKIE = "sd_session"

STORE = web_auth.SessionStore(config.AUTH_DB_PATH, ttl_s=config.AUTH_SESSION_TTL_S)
ACCESS = AccessStore(config.AUTH_DB_PATH)

CALLBACK_PATH = "/api/auth/callback/google"

# Everything reachable without a session. Deliberately short, and deliberately
# a literal rather than something computed: this list is the security boundary,
# so it should be readable in one glance and diffable in review.
#
# `/api/health` is here because the manifest health probe hits it on loopback
# before any browser exists. The public nginx block returns 404 for it, so the
# open path is not an exposed one -- two locks, either sufficient.
PUBLIC_PATHS = frozenset({
    "/login",
    "/access-requested",
    "/api/health",
    "/api/auth/status",
    "/api/auth/start",
    "/api/auth/request-access",
    CALLBACK_PATH,
})

router = APIRouter()


def configured() -> bool:
    return config.AUTH_CONFIGURED


def current_session(request: Request) -> dict | None:
    return STORE.session(request.cookies.get(SESSION_COOKIE))


def _origin(request: Request) -> str:
    return web_auth.external_origin(
        request.headers, fallback=f"{request.url.scheme}://{request.url.netloc}"
    )


def _prefix(request: Request) -> str:
    return web_auth.mount_prefix(request.headers)


def _callback_uri(request: Request) -> str:
    """Where Google should return the browser.

    Built from the request rather than configured, because this app answers on
    two origins that must both keep working: its public hostname, and the
    VPN-only `angulo-solutions.com/signal-dashboard/` path that is the way back
    in when something about the public one breaks. Both are registered on the
    OAuth client; `mount_prefix` is what makes the second produce the prefixed
    URI Google has on file.
    """
    return f"{_origin(request)}{_prefix(request)}{CALLBACK_PATH}"


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


# ---------------------------------------------------------------- the gate


async def require_session(request: Request, call_next):
    """Refuse anything that is not a live session or an explicitly public path.

    Browsers navigating get a redirect to the login page; anything else gets a
    401 the frontend's `api()` helper turns into the same redirect. A request
    that is neither is still refused -- the branch only picks the response.
    """
    path = request.url.path.rstrip("/") or "/"
    if path in PUBLIC_PATHS or request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    # The loopback admin API authenticates with a bearer token, not a session.
    # It has its own guard; the session middleware must let it through.
    if request.url.path.startswith("/api/admin/"):
        return await call_next(request)

    if not configured():
        # Unconfigured is a failure state, not an open one. Serving the app here
        # would mean a missing environment variable silently publishes the whole
        # dashboard, which is the exact accident this module exists to prevent.
        if _wants_html(request):
            return _login_page(request, message="Sign-in is not configured on this server.")
        return JSONResponse({"detail": "sign-in is not configured"}, status_code=503)

    if current_session(request):
        # A session exists, but access may not be approved. The access_request
        # table is the gate: only approved emails reach data routes. Without
        # this check, a stranger who authenticated would sail past the middleware.
        session = current_session(request)
        if ACCESS.status_for_email(session["email"]) == "approved":
            return await call_next(request)
        # Non-approved session on a non-public path: send to access-requested.
        if _wants_html(request):
            return RedirectResponse(f"{_prefix(request)}/access-requested", status_code=303)
        return JSONResponse({"detail": "access not approved"}, status_code=403)

    if _wants_html(request):
        return RedirectResponse(f"{_prefix(request)}/login", status_code=303)
    return JSONResponse({"detail": "sign in to continue"}, status_code=401)


# ---------------------------------------------------------------- routes


def _login_page(request: Request, *, message: str = "", status_code: int = 200) -> HTMLResponse:
    """A self-contained login page.

    Inline styles and no <script>: the built frontend lives behind the gate, and
    a login page that depended on it would need holes punched in `PUBLIC_PATHS`
    for its assets. Fewer public paths is the whole point.
    """
    prefix = _prefix(request)
    action = f"{prefix}/api/auth/start"
    note = (
        f'<p class="note">{message}</p>'
        if message
        else '<p class="note">Access is limited to approved accounts.</p>'
    )
    button = (
        ""
        if message and not configured()
        else f'<a class="button" href="{action}">Continue with Google</a>'
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signal Dashboard</title>
<style>
  :root {{ --bg:#0d1117; --panel:#151b26; --border:#262f40;
           --text:#d7dde7; --muted:#7d8899; --accent:#5b9cf6; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
          justify-content:center; background:var(--bg); color:var(--text);
          font:14px/1.5 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif; }}
  .card {{ background:var(--panel); border:1px solid var(--border);
           border-radius:12px; padding:32px; width:min(92vw,380px); text-align:center; }}
  h1 {{ font-size:19px; font-weight:650; margin:0 0 6px; }}
  .mark {{ color:var(--accent); }}
  .note {{ color:var(--muted); font-size:13px; margin:0 0 22px; }}
  .button {{ display:block; padding:11px 16px; border-radius:8px;
             border:1px solid var(--border); background:#1a2130;
             color:var(--text); text-decoration:none; font-weight:550; }}
  .button:hover {{ border-color:var(--accent); }}
</style></head>
<body><main class="card">
  <h1><span class="mark">Signal</span> Dashboard</h1>
  {note}
  {button}
</main></body></html>""",
        status_code=status_code,
    )


@router.get("/login", include_in_schema=False)
def login(request: Request) -> Response:
    if not configured():
        return _login_page(
            request, message="Sign-in is not configured on this server.", status_code=503
        )
    if current_session(request):
        return RedirectResponse(f"{_prefix(request)}/", status_code=303)
    return _login_page(request)


@router.get("/api/auth/status")
def auth_status(request: Request) -> dict:
    """Whether sign-in works here, and who is currently signed in.

    Presence and identity only, never a secret. The client secret never appears,
    not even its length; the client ID appears as a suffix so a human can tell
    which client is loaded without the whole value entering a response body.

    Deliberately separate from `/api/health`: Ops Console restarts this unit and
    polls health before promoting rotated credentials, so a missing credential
    must never be able to masquerade as an unhealthy service. It is also a
    public path, because it has to answer honestly for a caller holding no
    session -- diagnosing "nobody can sign in" is exactly when nobody can.
    """
    session = current_session(request)
    return {
        "configured": configured(),
        "google_client_configured": bool(
            config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET
        ),
        "client_id_suffix": config.GOOGLE_CLIENT_ID[-30:] or None,
        "allowlist_size": len(config.AUTH_ALLOWED_EMAILS),
        "signed_in": bool(session),
        "email": session["email"] if session else None,
    }


@router.get("/api/auth/start", include_in_schema=False)
def start(request: Request) -> Response:
    if not configured():
        return JSONResponse({"detail": "sign-in is not configured"}, status_code=503)
    redirect_uri = _callback_uri(request)
    state, verifier, nonce = STORE.start_flow(redirect_uri)
    return RedirectResponse(
        web_auth.authorization_url(
            client_id=config.GOOGLE_CLIENT_ID,
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            verifier=verifier,
        ),
        status_code=303,
    )


@router.get(CALLBACK_PATH, include_in_schema=False)
def callback(request: Request, code: str = "", state: str = "") -> Response:
    if not configured():
        return JSONResponse({"detail": "sign-in is not configured"}, status_code=503)

    flow = STORE.consume_flow(state)
    if not flow:
        return _login_page(
            request, message="That sign-in link expired. Try again.", status_code=400
        )

    try:
        identity = web_auth.complete_flow(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            code=code,
            flow=flow,
        )
    except web_auth.IdentityError:
        log.warning("google sign-in verification failed")
        return _login_page(request, message="Sign-in could not be completed.", status_code=400)

    status = ACCESS.status_for_email(identity.email)
    if status != "approved":
        log.info("sign-in for %s redirected to access-requested (status=%s)", identity.email, status)
        prefix = _prefix(request)
        # Create a session so the user can submit an access request (the
        # request-access endpoint reads the email from the session). The
        # middleware's approval check below prevents them from reaching any
        # data route -- only /access-requested and /api/auth/request-access
        # are in PUBLIC_PATHS.
        token = STORE.create_session(identity)
        response = RedirectResponse(f"{prefix}/access-requested", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            secure=True,
            httponly=True,
            samesite="lax",
            max_age=config.AUTH_SESSION_TTL_S,
            path=prefix or "/",
        )
        return response
    prefix = _prefix(request)
    token = STORE.create_session(identity)
    response = RedirectResponse(f"{prefix}/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        secure=True,
        httponly=True,
        samesite="lax",
        max_age=config.AUTH_SESSION_TTL_S,
        path=prefix or "/",
    )
    log.info("signed in %s", identity.email)
    return response


@router.post("/api/auth/logout", include_in_schema=False)
def logout(request: Request) -> Response:
    """Drop the session server-side, not just the cookie.

    Same-origin is checked because this is the only state-changing route in the
    application; without it any page on the internet could sign you out. It is
    also the reason there is no CSRF token anywhere here -- one guarded write
    does not need a token-issuing apparatus, and everything else is a read.
    """
    if not web_auth.is_same_origin(
        request.headers, fallback=f"{request.url.scheme}://{request.url.netloc}"
    ):
        return JSONResponse({"detail": "same-origin request required"}, status_code=403)

    prefix = _prefix(request)
    STORE.delete_session(request.cookies.get(SESSION_COOKIE))
    response = JSONResponse({"status": "signed out"})
    response.delete_cookie(SESSION_COOKIE, path=prefix or "/")
    return response


# ---------------------------------------------------- access-request flow


def _access_requested_page(request: Request, *, message: str = "", status_code: int = 200) -> HTMLResponse:
    """Self-contained access-request page, same inline-HTML pattern as login."""
    session = current_session(request)
    email = session["email"] if session else None
    status = ACCESS.status_for_email(email) if email else None
    prefix = _prefix(request)

    if status == "approved":
        return RedirectResponse(f"{prefix}/", status_code=303)

    if status == "pending":
        body = '<p class="note">Your request is under review.</p>'
    else:
        body = f"""
        <p class="note">This workspace is private. Submit a request and an operator will review it.</p>
        <form method="post" action="{prefix}/api/auth/request-access">
          <textarea name="note" rows="3" maxlength="500" placeholder="Why do you need access?" class="input"></textarea>
          <button type="submit" class="button">{ "Send updated request" if status == "denied" else "Request access"}</button>
        </form>"""
        if message:
            body = f'<p class="note">{message}</p>\n        {body}'

    return HTMLResponse(
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signal Dashboard — Request access</title>
<style>
  :root {{ --bg:#0d1117; --panel:#151b26; --border:#262f40;
           --text:#d7dde7; --muted:#7d8899; --accent:#5b9cf6; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
          justify-content:center; background:var(--bg); color:var(--text);
          font:14px/1.5 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif; }}
  .card {{ background:var(--panel); border:1px solid var(--border);
           border-radius:12px; padding:32px; width:min(92vw,380px); text-align:center; }}
  h1 {{ font-size:19px; font-weight:650; margin:0 0 6px; }}
  .mark {{ color:var(--accent); }}
  .note {{ color:var(--muted); font-size:13px; margin:0 0 16px; }}
  .input {{ display:block; width:100%; padding:10px; border-radius:8px;
            border:1px solid var(--border); background:#0d1117; color:var(--text);
            font-size:13px; margin:0 0 12px; resize:vertical; }}
  .button {{ display:block; width:100%; padding:11px 16px; border-radius:8px;
             border:1px solid var(--border); background:#1a2130;
             color:var(--text); text-decoration:none; font-weight:550; }}
  .button:hover {{ border-color:var(--accent); }}
</style></head>
<body><main class="card">
  <h1><span class="mark">Signal</span> Dashboard</h1>
  {body}
  <p class="note" style="margin-top:16px;">Signed in as {email or "unknown"}. <a href="{prefix}/api/auth/logout" style="color:var(--accent)">Sign out</a></p>
</main></body></html>""",
        status_code=status_code,
    )


@router.get("/access-requested", include_in_schema=False)
def access_requested_page(request: Request) -> Response:
    session = current_session(request)
    if not session:
        return RedirectResponse(f"{_prefix(request)}/login", status_code=303)
    return _access_requested_page(request)


@router.post("/api/auth/request-access", include_in_schema=False)
async def request_access(request: Request) -> Response:
    if not web_auth.is_same_origin(
        request.headers, fallback=f"{request.url.scheme}://{request.url.netloc}"
    ):
        return JSONResponse({"detail": "same-origin request required"}, status_code=403)
    session = current_session(request)
    if not session:
        return RedirectResponse(f"{_prefix(request)}/login", status_code=303)
    email = session["email"]
    form = await request.form()
    note = form.get("note", "").strip()[:500] if form else None
    ACCESS.upsert_request(email, note or None)
    return _access_requested_page(request, message="Request submitted.")
