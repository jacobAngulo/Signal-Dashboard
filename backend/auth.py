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
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from ops_kit import smtp_mail, web_auth

from . import config
from .access_store import AccessStore

log = logging.getLogger("signal_dashboard.auth")

SESSION_COOKIE = "sd_session"

STORE = web_auth.SessionStore(
    config.AUTH_DB_PATH,
    ttl_s=config.AUTH_SESSION_TTL_S,
    absolute_ttl_s=config.AUTH_SESSION_ABSOLUTE_TTL_S,
)
IDENTITIES = web_auth.IdentityStore(config.AUTH_DB_PATH)
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
    "/api/auth/password/login",
    "/api/auth/password/register",
    "/api/auth/password/forgot",
    "/api/auth/password/reset",
    "/api/auth/password/resend-verification",
    "/api/auth/email/verify",
    "/reset-password",
    "/api/auth/request-access",
    CALLBACK_PATH,
})

router = APIRouter()


def google_configured() -> bool:
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

    session = current_session(request)
    if session:
        # A session exists, but access may not be approved. The access_request
        # table is the gate: only approved emails reach data routes. Without
        # this check, a stranger who authenticated would sail past the middleware.
        if ACCESS.status_for_email(session["email"]) == "approved":
            ACCESS.record_activity(session["email"])
            response = await call_next(request)
            _renew_session_cookie(response, request)
            return response
        # The root is the access-request state page.  Any other browser route
        # returns there, so submitting a request and refreshing after approval
        # never leaves a user stranded on a stale special-purpose URL.
        if path == "/" and _wants_html(request):
            response = _access_requested_page(request)
            _renew_session_cookie(response, request)
            return response
        if _wants_html(request):
            return RedirectResponse(f"{_prefix(request)}/", status_code=303)
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
    google_button = (
        f'<a class="button" href="{action}">Continue with Google</a>'
        if google_configured()
        else ""
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
  .input {{ display:block; width:100%; padding:10px; border-radius:8px;
            border:1px solid var(--border); background:#0d1117; color:var(--text);
            font-size:14px; margin:0 0 10px; }}
  .button {{ display:block; padding:11px 16px; border-radius:8px;
             border:1px solid var(--border); background:#1a2130;
             color:var(--text); text-decoration:none; font-weight:550; }}
  .button:hover {{ border-color:var(--accent); }}
  .divider {{ color:var(--muted); font-size:12px; margin:18px 0; }}
  .quiet {{ background:transparent; margin-top:10px; width:100%; }}
</style></head>
<body><main class="card">
  <h1><span class="mark">Signal</span> Dashboard</h1>
  {note}
  <form method="post" action="{prefix}/api/auth/password/login">
    <input class="input" name="email" type="email" autocomplete="email" placeholder="Email" required>
    <input class="input" name="password" type="password" autocomplete="current-password" placeholder="Password" required>
    <button class="button" type="submit">Sign in with password</button>
  </form>
  <form method="post" action="{prefix}/api/auth/password/register">
    <input class="input" name="email" type="email" autocomplete="email" placeholder="Email" required>
    <input class="input" name="password" type="password" autocomplete="new-password" minlength="12" placeholder="Create a password (12+ characters)" required>
    <button class="button quiet" type="submit">Create password account</button>
  </form>
  <p class="divider"><a href="{prefix}/reset-password" style="color:var(--accent)">Forgot password?</a></p>
  {f'<p class="divider">or</p>{google_button}' if google_button else ''}
</main></body></html>""",
        status_code=status_code,
    )


@router.get("/login", include_in_schema=False)
def login(request: Request) -> Response:
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
        "configured": True,
        "google_client_configured": google_configured(),
        "client_id_suffix": config.GOOGLE_CLIENT_ID[-30:] or None,
        "signed_in": bool(session),
        "email": session["email"] if session else None,
    }


@router.get("/api/auth/start", include_in_schema=False)
def start(request: Request) -> Response:
    if not google_configured():
        return _login_page(request, message="Google sign-in is not configured on this server.", status_code=503)
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
    if not google_configured():
        return JSONResponse({"detail": "Google sign-in is not configured"}, status_code=503)

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

    current = current_session(request)
    try:
        user = IDENTITIES.resolve_google(
            identity,
            current_user_id=current["subject"] if current else None,
        )
    except web_auth.AccountLinkRequired:
        return _login_page(
            request,
            message="An account already uses this email. Sign in with its password first, then continue with Google to link it.",
            status_code=409,
        )
    except web_auth.IdentityConflict:
        return _login_page(request, message="That Google account cannot be linked here.", status_code=409)

    prefix = _prefix(request)
    token = STORE.create_session(web_auth.Identity(subject=user.id, email=user.email))
    response = RedirectResponse(f"{prefix}/", status_code=303)
    _set_session_cookie(response, token, prefix)
    log.info("signed in %s", user.email)
    return response


def _set_session_cookie(response: Response, token: str, prefix: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        secure=True,
        httponly=True,
        samesite="lax",
        max_age=config.AUTH_SESSION_TTL_S,
        path=prefix or "/",
    )


def _renew_session_cookie(response: Response, request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _set_session_cookie(response, token, _prefix(request))


def _same_origin_refusal(request: Request) -> JSONResponse | None:
    if web_auth.is_same_origin(
        request.headers, fallback=f"{request.url.scheme}://{request.url.netloc}"
    ):
        return None
    return JSONResponse({"detail": "same-origin request required"}, status_code=403)


def _email_link(request: Request, path: str, token: str) -> str:
    return f"{_origin(request)}{_prefix(request)}{path}?token={quote(token, safe='')}"


def _send_verification_email(request: Request, user: web_auth.User) -> None:
    token = IDENTITIES.issue_email_token(user.id, "verify", ttl_s=24 * 60 * 60)
    smtp_mail.send_text(
        to=user.email,
        subject="Verify your Signal Dashboard email",
        body=("Verify this email address to finish creating your password account:\n\n"
              f"{_email_link(request, '/api/auth/email/verify', token)}\n\n"
              "This link expires in 24 hours. If you did not create this account, ignore this email."),
    )


def _send_reset_email(request: Request, user: web_auth.User) -> None:
    token = IDENTITIES.issue_email_token(user.id, "reset", ttl_s=60 * 60)
    smtp_mail.send_text(
        to=user.email,
        subject="Reset your Signal Dashboard password",
        body=("Use this link to choose a new password:\n\n"
              f"{_email_link(request, '/reset-password', token)}\n\n"
              "This link expires in one hour. If you did not request it, ignore this email."),
    )


def _reset_page(request: Request, *, token: str = "", message: str = "", status_code: int = 200) -> HTMLResponse:
    prefix = _prefix(request)
    if token and not IDENTITIES.email_token_user(token, "reset"):
        message = "That reset link is invalid or expired. Request a new one."
        token = ""
    form = (
        f'<form method="post" action="{prefix}/api/auth/password/reset">'
        f'<input type="hidden" name="token" value="{token}">'
        '<input class="input" name="password" type="password" autocomplete="new-password" minlength="12" placeholder="New password (12+ characters)" required>'
        '<button class="button" type="submit">Set new password</button></form>'
        if token else
        f'<form method="post" action="{prefix}/api/auth/password/forgot">'
        '<input class="input" name="email" type="email" autocomplete="email" placeholder="Email" required>'
        '<button class="button" type="submit">Email reset link</button></form>'
    )
    note = f'<p class="note">{message}</p>' if message else '<p class="note">Reset your password.</p>'
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Reset password</title><style>body{{background:#0d1117;color:#d7dde7;font:14px sans-serif;display:grid;place-items:center;min-height:100vh;margin:0}}main{{width:min(92vw,380px);padding:32px;border:1px solid #262f40;border-radius:12px;background:#151b26;text-align:center}}.input{{box-sizing:border-box;display:block;width:100%;margin:0 0 10px;padding:10px;background:#0d1117;border:1px solid #262f40;border-radius:8px;color:#d7dde7}}.button{{width:100%;padding:11px;border:1px solid #262f40;border-radius:8px;background:#1a2130;color:#d7dde7}}.note{{color:#9aa7ba}}</style></head><body><main><h1>Signal Dashboard</h1>{note}{form}<p><a style="color:#5b9cf6" href="{prefix}/login">Back to sign in</a></p></main></body></html>''', status_code=status_code)


@router.get("/api/auth/email/verify", include_in_schema=False)
def verify_email(request: Request, token: str = "") -> Response:
    if not IDENTITIES.verify_email_token(token):
        return _login_page(request, message="That verification link is invalid or expired.", status_code=400)
    return _login_page(request, message="Email verified. You can now sign in and request access.")


@router.get("/reset-password", include_in_schema=False)
def reset_password_page(request: Request, token: str = "") -> Response:
    return _reset_page(request, token=token)


@router.post("/api/auth/password/forgot", include_in_schema=False)
async def password_forgot(request: Request) -> Response:
    if refusal := _same_origin_refusal(request):
        return refusal
    user = IDENTITIES.user_for_password_email(str((await request.form()).get("email", "")))
    if user:
        try:
            _send_reset_email(request, user)
        except smtp_mail.MailError:
            log.exception("password reset email delivery failed")
    return _login_page(request, message="If that email has a password account, a reset link is on its way.")


@router.post("/api/auth/password/reset", include_in_schema=False)
async def password_reset(request: Request) -> Response:
    if refusal := _same_origin_refusal(request):
        return refusal
    form = await request.form()
    try:
        user = IDENTITIES.reset_password_from_token(str(form.get("token", "")), str(form.get("password", "")))
    except web_auth.PasswordError as exc:
        return _reset_page(request, token=str(form.get("token", "")), message=str(exc), status_code=400)
    if not user:
        return _reset_page(request, message="That reset link is invalid or expired.", status_code=400)
    return _login_page(request, message="Password updated. Sign in with your new password.")


@router.post("/api/auth/password/resend-verification", include_in_schema=False)
async def resend_verification(request: Request) -> Response:
    if refusal := _same_origin_refusal(request):
        return refusal
    user = IDENTITIES.user_for_password_email(str((await request.form()).get("email", "")))
    if user and not user.email_verified:
        try:
            _send_verification_email(request, user)
        except smtp_mail.MailError:
            log.exception("verification email delivery failed")
    return _login_page(request, message="If that email needs verification, a link is on its way.")


@router.post("/api/auth/password/login", include_in_schema=False)
async def password_login(request: Request) -> Response:
    if refusal := _same_origin_refusal(request):
        return refusal
    form = await request.form()
    user = IDENTITIES.authenticate_password(str(form.get("email", "")), str(form.get("password", "")))
    if not user:
        return _login_page(request, message="Email or password is incorrect.", status_code=401)
    prefix = _prefix(request)
    response = RedirectResponse(f"{prefix}/", status_code=303)
    _set_session_cookie(response, STORE.create_session(web_auth.Identity(user.id, user.email)), prefix)
    return response


@router.post("/api/auth/password/register", include_in_schema=False)
async def password_register(request: Request) -> Response:
    if refusal := _same_origin_refusal(request):
        return refusal
    form = await request.form()
    try:
        user = IDENTITIES.register_password(str(form.get("email", "")), str(form.get("password", "")))
    except (ValueError, web_auth.PasswordError) as exc:
        return _login_page(request, message=str(exc), status_code=400)
    try:
        _send_verification_email(request, user)
    except smtp_mail.MailError:
        log.exception("verification email delivery failed")
        return _login_page(request, message="Your account was created, but we could not send its verification email. Try again shortly.", status_code=503)
    prefix = _prefix(request)
    response = RedirectResponse(f"{prefix}/", status_code=303)
    _set_session_cookie(response, STORE.create_session(web_auth.Identity(user.id, user.email)), prefix)
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
    # Kept for existing bookmarks.  The root now owns the request state so a
    # refresh after approval naturally enters the application.
    return RedirectResponse(f"{_prefix(request)}/", status_code=303)


@router.post("/api/auth/request-access", include_in_schema=False)
async def request_access(request: Request) -> Response:
    if not web_auth.is_same_origin(
        request.headers, fallback=f"{request.url.scheme}://{request.url.netloc}"
    ):
        return JSONResponse({"detail": "same-origin request required"}, status_code=403)
    session = current_session(request)
    if not session:
        return RedirectResponse(f"{_prefix(request)}/login", status_code=303)
    user = IDENTITIES.get_user(session["subject"])
    if user and not user.email_verified:
        return _access_requested_page(request, message="Verify your email before requesting access.", status_code=403)
    email = session["email"]
    form = await request.form()
    note = form.get("note", "").strip()[:500] if form else None
    ACCESS.upsert_request(email, note or None)
    return RedirectResponse(f"{_prefix(request)}/", status_code=303)
