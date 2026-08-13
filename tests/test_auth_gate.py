"""The gate is closed.

The valuable test here is `test_every_route_is_gated_or_declared_public`. The
rest verify individual refusals; that one verifies there is nothing to forget.
It walks the application's real route table, so a route added next year is
covered by a test written today -- which is the only kind of coverage that
survives the thing it protects against.
"""

import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from ops_kit import web_auth

from backend import auth, config
from backend.access_store import AccessStore
from backend.main import app

ALLOWED = "jacob1angulo@gmail.com"

# Routes that answer without a session, restated here rather than imported from
# `auth.PUBLIC_PATHS`. Importing it would make the test agree with the code by
# construction and assert nothing: widening the real list would silently widen
# the expectation too. Someone has to type the address twice.
EXPECTED_PUBLIC = {
    "/login",
    "/access-requested",
    "/api/health",
    "/api/auth/status",
    "/api/auth/start",
    "/api/auth/request-access",
    "/api/auth/callback/google",
}


def walk(routes):
    """Every route in the app, including ones nested inside included routers.

    FastAPI keeps an included router as a single `_IncludedRouter` entry rather
    than flattening its routes into `app.routes`. A walk that missed that would
    quietly skip whole routers, so it unwraps `original_router` -- and
    `test_the_route_walk_sees_data_routes` exists to catch this going stale.
    """
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from walk(nested.routes)
            continue
        if getattr(route, "path", None):
            yield route


def sample_path(route):
    """A concrete path for a route, with any path parameters filled in."""
    return (
        route.path
        .replace("{date}", "2026-07-20")
        .replace("{producer}", "lstm")
        .replace("{ticker}", "AAPL")
    )


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = web_auth.SessionStore(f"{self.tmp.name}/auth.sqlite3", ttl_s=1800)
        access = AccessStore(f"{self.tmp.name}/auth.sqlite3")

        # A configured server with one allowed address is the state every test
        # here cares about; the unconfigured case gets its own class below.
        patches = [
            patch.object(auth, "STORE", store),
            patch.object(auth, "ACCESS", access),
            patch.object(config, "AUTH_CONFIGURED", True),
            patch.object(config, "GOOGLE_CLIENT_ID", "test-client-id"),
            patch.object(config, "GOOGLE_CLIENT_SECRET", "test-client-secret"),
            patch.object(config, "AUTH_ALLOWED_EMAILS", frozenset({ALLOWED})),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        self.store = store
        self.access = access
        self.client = TestClient(app)

    def sign_in(self, email=ALLOWED):
        token = self.store.create_session(web_auth.Identity(subject="sub-1", email=email))
        self.client.cookies.set(auth.SESSION_COOKIE, token)
        # Pre-approve so the middleware's access check lets the session through.
        with self.access.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO access_request (id, email, status, decided_by, created_at) "
                "VALUES (?, ?, 'approved', 'test', ?)",
                (str(__import__("uuid").uuid4()), email, int(__import__("time").time() * 1000))
            )
        return token

    # ------------------------------------------------------------------ the one that matters

    def test_every_route_is_gated_or_declared_public(self):
        for route in walk(app.routes):
            if route.path in EXPECTED_PUBLIC:
                continue
            # Admin routes bypass the session middleware via a prefix check;
            # they have their own bearer-token guard.
            if route.path.startswith("/api/admin/"):
                continue
            with self.subTest(route=route.path):
                response = self.client.get(sample_path(route), follow_redirects=False)
                self.assertEqual(
                    response.status_code, 401,
                    f"{route.path} answered {response.status_code} without a session. "
                    "Add it to auth.PUBLIC_PATHS and to EXPECTED_PUBLIC here if that "
                    "is deliberate.",
                )

    def test_the_route_walk_sees_data_routes(self):
        """Canary for `walk`. If it silently returns nothing, the test above passes."""
        found = {route.path for route in walk(app.routes)}
        self.assertIn("/api/signals", found)
        self.assertIn("/api/analytics", found)
        self.assertIn("/api/ticker/{ticker}/chart", found)
        # And the nested router really is being unwrapped.
        self.assertIn("/api/auth/status", found)

    def test_public_paths_are_exactly_what_the_test_expects(self):
        self.assertEqual(set(auth.PUBLIC_PATHS), EXPECTED_PUBLIC)

    def test_the_application_itself_is_gated(self):
        """The SPA is a static mount, not a route, so the walk above cannot see it."""
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------ sessions

    def test_a_valid_session_is_admitted(self):
        self.sign_in()
        response = self.client.get("/api/auth/status")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["signed_in"])
        self.assertEqual(response.json()["email"], ALLOWED)

    def test_an_expired_session_is_refused(self):
        token = self.sign_in()
        with self.store.connect() as db:
            db.execute(
                "UPDATE sessions SET expires_at=? WHERE token_hash=?",
                (time.time() - 1, web_auth.token_hash(token)),
            )
        self.assertEqual(self.client.get("/api/tickers").status_code, 401)

    def test_a_forged_cookie_is_refused(self):
        self.client.cookies.set(auth.SESSION_COOKIE, "not-a-real-token")
        self.assertEqual(self.client.get("/api/tickers").status_code, 401)

    def test_logout_drops_the_session_server_side(self):
        token = self.sign_in()
        response = self.client.post(
            "/api/auth/logout", headers={"origin": "http://testserver"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.store.session(token))

    def test_logout_refuses_a_cross_origin_caller(self):
        token = self.sign_in()
        response = self.client.post(
            "/api/auth/logout", headers={"origin": "https://elsewhere.example"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(self.store.session(token))

    # ------------------------------------------------------------------ browsers vs. fetches

    def test_a_browser_is_redirected_to_the_login_page(self):
        response = self.client.get(
            "/api/overview", headers={"accept": "text/html"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")

    def test_the_login_page_is_served_without_a_session(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Continue with Google", response.text)

    def test_the_login_page_carries_no_external_assets(self):
        """It is served from a public path, so it must not need more public paths."""
        response = self.client.get("/login")
        self.assertNotIn("<script", response.text)
        self.assertNotIn("/assets/", response.text)

    # ------------------------------------------------------------------ access requests

    def test_a_stranger_is_sent_to_access_requested(self):
        _, _, nonce = self.store.start_flow("https://example.test/api/auth/callback/google")
        state = self._last_state()
        identity = web_auth.Identity(subject="sub-2", email="stranger@gmail.com")
        with patch.object(web_auth, "complete_flow", return_value=identity):
            response = self.client.get(
                f"/api/auth/callback/google?code=x&state={state}", follow_redirects=False
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/access-requested", response.headers["location"])
        # A session is created so the stranger can submit a request, but the
        # middleware's access check prevents them from reaching data routes.
        self.assertIn(auth.SESSION_COOKIE, response.cookies)

    def test_a_stranger_with_a_session_cannot_reach_data_routes(self):
        token = self.store.create_session(
            web_auth.Identity(subject="sub-2", email="stranger@gmail.com")
        )
        self.client.cookies.set(auth.SESSION_COOKIE, token)
        response = self.client.get("/api/tickers", follow_redirects=False)
        self.assertEqual(response.status_code, 403)

    def test_a_stranger_with_a_session_is_redirected_from_html_routes(self):
        token = self.store.create_session(
            web_auth.Identity(subject="sub-2", email="stranger@gmail.com")
        )
        self.client.cookies.set(auth.SESSION_COOKIE, token)
        response = self.client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/access-requested", response.headers["location"])

    def test_an_approved_address_receives_a_session_and_access(self):
        state = self._new_flow()
        identity = web_auth.Identity(subject="sub-1", email=ALLOWED)
        with patch.object(web_auth, "complete_flow", return_value=identity):
            response = self.client.get(
                f"/api/auth/callback/google?code=x&state={state}", follow_redirects=False
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn(auth.SESSION_COOKIE, response.cookies)

    def test_a_stale_or_unknown_state_is_refused(self):
        with patch.object(web_auth, "complete_flow") as complete:
            response = self.client.get(
                "/api/auth/callback/google?code=x&state=never-issued",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 400)
        complete.assert_not_called()

    def test_a_state_cannot_be_replayed(self):
        state = self._new_flow()
        identity = web_auth.Identity(subject="sub-1", email=ALLOWED)
        with patch.object(web_auth, "complete_flow", return_value=identity):
            first = self.client.get(
                f"/api/auth/callback/google?code=x&state={state}", follow_redirects=False
            )
            second = self.client.get(
                f"/api/auth/callback/google?code=x&state={state}", follow_redirects=False
            )
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 400)

    def _new_flow(self):
        state, _, _ = self.store.start_flow("https://example.test/api/auth/callback/google")
        return state

    def _last_state(self):
        return self._new_flow()


class UnconfiguredTests(unittest.TestCase):
    """A server missing its credentials or its allowlist refuses everyone.

    This is the accident the module exists to prevent: an environment variable
    that failed to load must not be the difference between a private dashboard
    and a public one.
    """

    def setUp(self):
        self.tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patches = [
            patch.object(auth, "STORE", web_auth.SessionStore(f"{self.tmp.name}/a.sqlite3")),
            patch.object(auth, "ACCESS", AccessStore(f"{self.tmp.name}/a.sqlite3")),
            patch.object(config, "AUTH_CONFIGURED", False),
            patch.object(config, "AUTH_ALLOWED_EMAILS", frozenset()),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = TestClient(app)

    def test_data_routes_refuse_rather_than_open(self):
        response = self.client.get("/api/signals", follow_redirects=False)
        self.assertEqual(response.status_code, 503)

    def test_the_application_refuses_rather_than_opens(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 503)

    def test_the_login_page_says_so_instead_of_offering_a_dead_button(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.text)
        self.assertNotIn("Continue with Google", response.text)

    def test_status_still_answers_so_the_fault_is_diagnosable(self):
        response = self.client.get("/api/auth/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["configured"])
        self.assertEqual(response.json()["allowlist_size"], 0)


if __name__ == "__main__":
    unittest.main()
