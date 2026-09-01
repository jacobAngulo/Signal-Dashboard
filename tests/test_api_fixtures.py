"""The recorded frontend fixtures must keep describing this API.

`frontend/fixtures/api` is a snapshot of real responses, served to the vite dev
server by `frontend/fixtures/plugin.js` so the UI can run where the producer
data does not. A snapshot rots quietly: rename a route and the fixture for the
old path still loads, so the frontend keeps developing against a shape the
backend stopped returning, and nothing says so until someone deploys.

So these walk the real route table, the same way `test_auth_gate.py` does. They
need no producer data -- they read the committed manifest and compare it with
the app's own routes.
"""

import json
import re
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from backend import main

FIXTURES = Path(__file__).resolve().parent.parent / "frontend" / "fixtures" / "api"
INDEX = FIXTURES / "index.json"


def manifest():
    return json.loads(INDEX.read_text())


def route_matchers():
    """Every GET route the app serves, as a regex over its path.

    Path parameters become a permissive segment: the fixtures record concrete
    tickers and dates, and the point here is that the *route* still exists.
    """
    matchers = []
    for route in main.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        if not path or "GET" not in methods:
            continue
        pattern = re.sub(r"\{[^}]+\}", "[^/]+", re.escape(path)
                         .replace(r"\{", "{").replace(r"\}", "}"))
        matchers.append((path, re.compile(f"^{pattern}$")))
    return matchers


@unittest.skipUnless(INDEX.exists(), "fixtures have not been recorded")
class ApiFixtureTests(unittest.TestCase):
    def test_every_recorded_response_has_its_file(self):
        for record in manifest()["responses"]:
            with self.subTest(record["file"]):
                self.assertTrue((FIXTURES / record["file"]).exists())

    def test_recorded_files_are_valid_json(self):
        for record in manifest()["responses"]:
            with self.subTest(record["file"]):
                json.loads((FIXTURES / record["file"]).read_text())

    def test_keys_and_files_are_unique(self):
        records = manifest()["responses"]
        keys = [r["key"] for r in records]
        files = [r["file"] for r in records]
        self.assertEqual(len(keys), len(set(keys)), "two records share a key")
        self.assertEqual(len(files), len(set(files)), "two records share a file")

    def test_every_recorded_path_is_still_a_route(self):
        """The check that actually catches drift: a renamed or deleted route."""
        matchers = route_matchers()
        for record in manifest()["responses"]:
            path = urlsplit(record["key"].split(" ", 1)[1]).path
            with self.subTest(path):
                self.assertTrue(
                    any(pattern.match(path) for _, pattern in matchers),
                    f"{path} is recorded but no GET route serves it any more. "
                    "Re-record with scripts/capture_api_fixtures.py.",
                )

    def test_keys_are_normalized_the_way_the_dev_server_reads_them(self):
        """Sorted, non-empty query parameters -- see `canon()` in plugin.js.

        The plugin re-normalizes what it loads, so a stray key would not break
        it, but a manifest that disagrees with the recorder means the two have
        drifted apart and matching is no longer predictable.
        """
        for record in manifest()["responses"]:
            method, url = record["key"].split(" ", 1)
            parts = urlsplit(url)
            with self.subTest(record["key"]):
                self.assertEqual(method, "GET")
                if not parts.query:
                    continue
                # parse_qsl decodes, so re-encoding reproduces the recorder's
                # own urlencode(sorted(...)) -- signal ids are colon-delimited
                # and arrive percent-encoded.
                pairs = parse_qsl(parts.query, keep_blank_values=True)
                self.assertEqual(parts.query, urlencode(sorted(pairs)))
                self.assertTrue(all(value for _, value in pairs),
                                "empty values are never sent by src/api.js")


if __name__ == "__main__":
    unittest.main()
