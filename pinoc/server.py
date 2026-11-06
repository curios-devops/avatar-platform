"""PINOC asset broker + static server for the splat-character demo.

The browser never sees a Viggle credential or a signed URL: it talks only to this server, which
calls the documented Viggle REST API (https://docs.viggle.ai/v1) with VIGLE_K_API_KEY from
avatar-platform/backend/.env and streams the files back. Asset access lives here; rendering lives in
web/, which only knows the /api/* routes below. MEYA can swap this file for its own backend route.

    python pinoc/server.py [port]          → http://127.0.0.1:8770/

Routes (all GET, all free in Viggle's pricing: list, get and export cost 0 credits):
    /api/status                     key present? valid? credit balance
    /api/characters                 GET /v1/characters (newest 100)
    /api/characters/<id>            GET /v1/characters/<id>
    /api/characters/<id>/vsplat     GET /v1/characters/<id>/export?download_type=vsplat → bytes
    /api/motions                    GET /v1/motions (newest 100)
    /api/motion-templates           GET /v1/motion-templates (official catalogue)
    /api/motions/<id>/glb?rig=metahuman|metahuman_body|mixamo
                                    GET /v1/motions/<id>/export?download_type=glb → bytes
    /api/local                      files dropped in pinoc/assets/ (e.g. fetched through the MCP)
    /assets/<file>                  those files
Anything else is served from web/ and node_modules/. Every upstream call is logged to
pinoc/logs/broker.log (method, path, status, ms, request id; never the key or signed URLs).
"""
import http.server
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
WEB, MODULES, ASSETS, CACHE, LOGS = (HERE / d for d in ("web", "node_modules", "assets", "cache", "logs"))
ENV = pathlib.Path("/Users/mac/Documents/avatar-platform/backend/.env")
API = "https://apis.viggle.ai/v1"
KEY_NAMES = ("VIGLE_K_API_KEY", "VIGGLE_API_KEY")  # the first is the name used in backend/.env
RIGS = {"metahuman": "metahuman_url", "metahuman_body": "metahuman_body_url", "mixamo": "mixamo_url"}


def api_key():
    if not ENV.exists():
        return None
    for line in ENV.read_text().splitlines():
        for name in KEY_NAMES:
            if line.startswith(name + "="):
                value = line.split("=", 1)[1].strip().strip('"')
                if value:
                    return value
    return None


def log(**row):
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / "broker.log", "a") as f:
        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), **row}) + "\n")


class Upstream(Exception):
    def __init__(self, status, body):
        super().__init__(status)
        self.status, self.body = status, body


def viggle(path):
    """GET a documented Viggle endpoint; returns parsed JSON or raises Upstream with its error."""
    key = api_key()
    if not key:
        raise Upstream(401, {"error": {"code": "MISSING_KEY", "message": "VIGLE_K_API_KEY is not set in backend/.env",
                                       "remediation": "create a key at https://portal.viggle.ai/keys"}})
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {key}", "X-Viggle-Source": "meya-poc"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
            log(call=f"GET {path}", status=r.status, ms=int((time.time() - t0) * 1000))
            return body
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"error": {"code": f"HTTP_{e.code}", "message": raw[:300].decode(errors="replace")}}
        log(call=f"GET {path}", status=e.code, ms=int((time.time() - t0) * 1000),
            code=(body.get("error") or {}).get("code"), request_id=(body.get("error") or {}).get("request_id"))
        raise Upstream(e.code, body)
    except urllib.error.URLError as e:
        log(call=f"GET {path}", status=0, error=str(e.reason))
        raise Upstream(502, {"error": {"code": "UPSTREAM_UNREACHABLE", "message": str(e.reason)}})


def fetch_signed(url, dest):
    """Download a signed asset URL once into cache/ (the URL expires in 1 h; the bytes are ours)."""
    t0 = time.time()
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    CACHE.mkdir(exist_ok=True)
    dest.write_bytes(data)
    log(call="download signed asset", file=dest.name, bytes=len(data), ms=int((time.time() - t0) * 1000))
    return data


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript",
                      ".mjs": "text/javascript", ".vsplat": "application/octet-stream", ".glb": "model/gltf-binary"}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def translate_path(self, path):
        p = urllib.parse.urlparse(path).path
        if p.startswith("/node_modules/"):
            return str(MODULES / p[len("/node_modules/"):])
        if p.startswith("/assets/"):
            return str(ASSETS / pathlib.Path(p).name)
        return super().translate_path(path)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if not u.path.startswith("/api/"):
            return super().do_GET()
        q = urllib.parse.parse_qs(u.query)
        try:
            self.route(u.path[len("/api"):], q)
        except Upstream as e:
            self.send_json(e.status, e.body)
        except Exception as e:  # surface, never hide
            log(call=u.path, status=500, error=repr(e))
            self.send_json(500, {"error": {"code": "BROKER_ERROR", "message": repr(e)}})

    def route(self, p, q):
        if p == "/status":
            if not api_key():
                return self.send_json(200, {"key": "missing", "hint": "set VIGLE_K_API_KEY in backend/.env (https://portal.viggle.ai/keys)"})
            try:
                return self.send_json(200, {"key": "valid", "credits": viggle("/credits")})
            except Upstream as e:
                return self.send_json(200, {"key": "rejected", "upstream": e.status, "error": e.body.get("error")})
        if p == "/local":
            files = sorted(f.name for f in ASSETS.glob("*") if f.suffix in (".vsplat", ".glb", ".bin"))
            return self.send_json(200, {"data": files})
        if p == "/characters":
            return self.send_json(200, viggle("/characters"))
        if p == "/motions":
            return self.send_json(200, viggle("/motions"))
        if p == "/motion-templates":
            return self.send_json(200, viggle("/motion-templates"))
        m = re.fullmatch(r"/characters/(char_[\w-]+)(/vsplat)?", p)
        if m:
            cid = m.group(1)
            if not m.group(2):
                return self.send_json(200, viggle(f"/characters/{cid}"))
            dest = CACHE / f"{cid}.vsplat"
            if dest.exists():
                return self.send_bytes(dest.read_bytes(), "application/octet-stream")
            exp = viggle(f"/characters/{cid}/export?download_type=vsplat")
            if not exp.get("vsplat_url"):
                raise Upstream(409, {"error": {"code": "NO_VSPLAT", "message": f"character export status={exp.get('status')}",
                                               "export": exp}})
            return self.send_bytes(fetch_signed(exp["vsplat_url"], dest), "application/octet-stream")
        m = re.fullmatch(r"/motions/(mot_[\w-]+)/glb", p)
        if m:
            mid, rig = m.group(1), q.get("rig", ["metahuman"])[0]
            if rig not in RIGS:
                raise Upstream(400, {"error": {"code": "BAD_RIG", "message": f"rig must be one of {list(RIGS)}"}})
            dest = CACHE / f"{mid}.{rig}.glb"
            if dest.exists():
                return self.send_bytes(dest.read_bytes(), "model/gltf-binary")
            exp = viggle(f"/motions/{mid}/export?download_type=glb")
            url = exp.get(RIGS[rig])
            if not url:
                raise Upstream(409, {"error": {"code": "NO_GLB", "message": f"motion export has no {RIGS[rig]} (status={exp.get('status')})",
                                               "export": {k: v for k, v in exp.items() if not k.endswith("_url")}}})
            return self.send_bytes(fetch_signed(url, dest), "model/gltf-binary")
        raise Upstream(404, {"error": {"code": "NO_ROUTE", "message": p}})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    ASSETS.mkdir(exist_ok=True)
    print(f"http://127.0.0.1:{port}/  key={'set' if api_key() else 'missing'}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
