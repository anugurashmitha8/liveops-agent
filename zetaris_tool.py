"""Run SQL through Zetaris and get rows back as dicts.

Uses the Zetaris web app's SQL endpoint with a login token. Zetaris tokens last
about 15 minutes, and on this endpoint an expired token can come back as 400
(not only 401), so the token is refreshed before it gets old, and a 400/401 gets
one fresh login before anything else. Brief Zetaris errors are retried twice.
"""

import base64
import json
import os
import time
import uuid
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

from logger import log

load_dotenv()

BASE = "http://localhost:3000/api"
TOKEN_MAX_AGE_S = 10 * 60  # refresh well before the ~15 minute expiry

_token = None
_token_at = 0.0


def _find_token(obj):
    found = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and v.startswith("eyJ"):
                    found[k.lower()] = v
                else:
                    walk(v)

    walk(obj)
    for key in ("accesstoken", "idtoken", "token"):
        if key in found:
            return found[key]
    return next((v for k, v in found.items() if "refresh" not in k), None)


def login():
    global _token, _token_at
    r = requests.post(f"{BASE}/auth/login", timeout=30, json={
        "username": os.environ["ZETARIS_USER"],
        "password": os.environ["ZETARIS_PASSWORD"]})
    r.raise_for_status()
    try:
        _token = _find_token(r.json())
    except ValueError:
        _token = None
    if not _token and "idToken" in r.cookies:
        _token = base64.b64decode(unquote(r.cookies["idToken"])).decode()
    if not _token:
        raise RuntimeError("Login OK but no token found. Response keys: "
                           + str(list(r.json().keys()) if r.text.startswith("{") else r.text[:100]))
    _token_at = time.time()
    return _token


def _post(sql, limit):
    headers = {"Authorization": f"Bearer {_token}", "x-org-id": "1",
               "Content-Type": "application/json", "Accept": "text/plain"}
    body = {"queryId": str(uuid.uuid4()), "sql": sql,
            "source": "SqlEditor", "limit": limit, "chunkSize": 10000}
    return requests.post(f"{BASE}/proxy/sql-editor/sqls/run-stream",
                         json=body, headers=headers, timeout=120)


def _run_once(sql, limit):
    if not _token or time.time() - _token_at > TOKEN_MAX_AGE_S:
        login()
    r = _post(sql, limit)
    if r.status_code in (400, 401):
        # Often just an expired token: log in once more and try again.
        log("zetaris", "relogin", {"status": r.status_code})
        login()
        r = _post(sql, limit)
    if r.status_code >= 400:
        raise RuntimeError(f"Zetaris {r.status_code}: {r.text[:500]}")
    lines = []
    for line in r.text.splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    if not lines:
        return []
    cols, *rows = lines
    return [dict(zip(cols, row)) for row in rows]


def run_sql(sql, limit=100):
    """Rows as dicts. Retries brief Zetaris errors (400/5xx, network) twice."""
    for attempt in range(1, 4):
        try:
            return _run_once(sql, limit)
        except (RuntimeError, requests.ConnectionError, requests.Timeout) as err:
            brief = (not isinstance(err, RuntimeError)
                     or str(err).startswith(("Zetaris 400", "Zetaris 5")))
            if not brief or attempt == 3:
                raise
            log("zetaris", "retry", {"attempt": attempt, "error": str(err)[:200]})
            time.sleep(2 * attempt)


if __name__ == "__main__":
    rows = run_sql("SELECT * FROM riverside.UNITS LIMIT 5")
    print("Rows:", len(rows))
    print(rows[0] if rows else "(no rows)")