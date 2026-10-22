import os, uuid, json, base64, requests
from urllib.parse import unquote
from dotenv import load_dotenv
load_dotenv()

BASE = "http://localhost:3000/api"
_token = None

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
    global _token
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
    return _token

def run_sql(sql, limit=100, _retry=True):
    if not _token:
        login()
    headers = {"Authorization": f"Bearer {_token}", "x-org-id": "1",
               "Content-Type": "application/json", "Accept": "text/plain"}
    body = {"queryId": str(uuid.uuid4()), "sql": sql,
            "source": "SqlEditor", "limit": limit, "chunkSize": 10000}
    r = requests.post(f"{BASE}/proxy/sql-editor/sqls/run-stream",
                      json=body, headers=headers, timeout=120)
    if r.status_code == 401 and _retry:      # token expired → log in again
        login()
        return run_sql(sql, limit, _retry=False)
    r.raise_for_status()
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

if __name__ == "__main__":
    rows = run_sql("SELECT * FROM NY_TAXI.customers LIMIT 5")
    print("Rows:", len(rows))
    print(rows[0])