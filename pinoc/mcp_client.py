"""Minimal client for the PINOC MCP server (https://pinoc.mcp.viggle.ai/mcp), read-only.

    python pinoc/mcp_client.py login [scopes]   OAuth 2.1 + PKCE in the browser (default scope pinoc:read;
                                                pass "pinoc:read pinoc:generate" to allow paid generation)
    python pinoc/mcp_client.py tools            list the server's tools and their input schemas
    python pinoc/mcp_client.py call <tool> '<json args>'   call one tool, print its result

The flow is the one the server advertises: protected-resource metadata → auth.viggle.ai,
dynamic client registration, authorization code with S256 PKCE and a loopback redirect, token
exchange with the MCP URL as `resource`. The token goes to pinoc/.mcp_token.json (mode 600,
gitignored) and is never printed. Every call is logged to pinoc/logs/mcp.log without the token.
"""
import base64
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
TOKEN, LOGS = HERE / ".mcp_token.json", HERE / "logs"
MCP = "https://pinoc.mcp.viggle.ai/mcp"
AUTH = "https://auth.viggle.ai"
PORT, SCOPE = 8771, "pinoc:read"
UA = {"User-Agent": "meya-pinoc-poc/0.1 (+python)"}  # auth.viggle.ai answers 403 to the urllib default
REDIRECT = f"http://127.0.0.1:{PORT}/callback"


def log(**row):
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / "mcp.log", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), **row}) + "\n")


def post(url, data, headers=None, form=False):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    h = {**UA, "Content-Type": "application/x-www-form-urlencoded" if form else "application/json", **(headers or {})}
    req = urllib.request.Request(url, body, h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def login(scope=SCOPE):
    meta = json.loads(urllib.request.urlopen(urllib.request.Request(f"{AUTH}/.well-known/oauth-authorization-server", headers=UA), timeout=30).read())
    status, _, raw = post(meta["registration_endpoint"], {
        "client_name": "MEYA PINOC PoC (local)", "redirect_uris": [REDIRECT], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none", "scope": scope})
    if status >= 300:
        raise SystemExit(f"client registration failed: HTTP {status} {raw[:300]!r}")
    client_id = json.loads(raw)["client_id"]
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": scope, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": MCP})
    got = {}

    class Cb(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            ok = "code" in got and got.get("state") == state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<h2>PINOC: acceso concedido, puedes cerrar esta pestaña.</h2>" if ok
                              else f"<h2>PINOC: error {got.get('error', 'state')}</h2>").encode())

    srv = http.server.HTTPServer(("127.0.0.1", PORT), Cb)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Abre esta URL si el navegador no se abre solo:\n" + url, flush=True)
    subprocess.run(["open", url], check=False)
    t0 = time.time()
    while not got and time.time() - t0 < 600:
        time.sleep(0.5)
    srv.shutdown()
    if "code" not in got or got.get("state") != state:
        raise SystemExit(f"authorization failed: {got.get('error')} {got.get('error_description', '')}")
    status, _, raw = post(meta["token_endpoint"], {
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT, "client_id": client_id,
        "code_verifier": verifier, "resource": MCP}, form=True)
    if status >= 300:
        raise SystemExit(f"token exchange failed: HTTP {status} {raw[:300]!r}")
    tok = json.loads(raw)
    tok.update(client_id=client_id, token_endpoint=meta["token_endpoint"], obtained=time.time())
    TOKEN.write_text(json.dumps(tok))
    os.chmod(TOKEN, 0o600)
    log(event="login", scope=tok.get("scope"), expires_in=tok.get("expires_in"))
    print(f"ok: token saved (scope={tok.get('scope')}, expires_in={tok.get('expires_in')})")


def access_token():
    if not TOKEN.exists():
        raise SystemExit("no token: run `login` first")
    tok = json.loads(TOKEN.read_text())
    if tok.get("expires_in") and time.time() > tok["obtained"] + tok["expires_in"] - 60 and tok.get("refresh_token"):
        status, _, raw = post(tok["token_endpoint"], {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                                      "client_id": tok["client_id"], "resource": MCP}, form=True)
        if status < 300:
            tok.update(json.loads(raw), obtained=time.time())
            TOKEN.write_text(json.dumps(tok))
            log(event="refresh")
    return tok["access_token"]


class Session:
    """JSON-RPC over the streamable HTTP transport (JSON or SSE answers)."""

    def __init__(self):
        self.auth, self.sid, self.n = access_token(), None, 0

    def rpc(self, method, params=None, notify=False):
        h = {"Authorization": f"Bearer {self.auth}", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": "2025-06-18"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            self.n += 1
            msg["id"] = self.n
        t0 = time.time()
        status, headers, raw = post(MCP, msg, h)
        log(call=method, tool=(params or {}).get("name"), status=status, ms=int((time.time() - t0) * 1000))
        self.sid = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id") or self.sid
        if notify:
            return None
        if status >= 300:
            raise SystemExit(f"{method}: HTTP {status} {raw[:400].decode(errors='replace')}")
        text = raw.decode()
        if "text/event-stream" in (headers.get("Content-Type") or headers.get("content-type") or ""):
            datas = [l[5:].strip() for l in text.splitlines() if l.startswith("data:")]
            replies = [json.loads(d) for d in datas if d]
            text = json.dumps(next((r for r in replies if r.get("id") == msg["id"]), replies[-1] if replies else {}))
        reply = json.loads(text)
        if reply.get("error"):
            raise SystemExit(f"{method}: {reply['error']}")
        return reply["result"]

    def open(self):
        info = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "meya-pinoc-poc", "version": "0.1"}})
        self.rpc("notifications/initialized", notify=True)
        return info


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        return login(sys.argv[2] if len(sys.argv) > 2 else SCOPE)
    s = Session()
    info = s.open()
    if cmd == "tools":
        print(json.dumps({"server": info.get("serverInfo"), "instructions": (info.get("instructions") or "")[:1500]}, indent=1))
        for t in s.rpc("tools/list").get("tools", []):
            ann = t.get("annotations") or {}
            print(f"\n## {t['name']}  readOnly={ann.get('readOnlyHint')} destructive={ann.get('destructiveHint')}")
            print((t.get("description") or "")[:600])
            print("input:", json.dumps(t.get("inputSchema", {}).get("properties", {}))[:600])
    elif cmd == "call":
        res = s.rpc("tools/call", {"name": sys.argv[2], "arguments": json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}})
        print(json.dumps(res, indent=1)[:12000])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
