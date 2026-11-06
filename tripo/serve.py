"""Static server for tripo/viewer (plus /specs/ → tripo/specs) with POST /save?name=… to keep the
renders and GLB exports the pages make. Saved files go to .triage/tripo_capy/llm/ in the main repo.

    python tripo/serve.py [port]
"""
import http.server
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
VIEWER, SPECS = HERE / "viewer", HERE / "specs"
OUT = pathlib.Path("/Users/mac/Documents/avatar-platform/.triage/tripo_capy/llm")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(VIEWER), **kw)

    def translate_path(self, path):
        p = urllib.parse.urlparse(path).path
        if p.startswith("/specs/"):
            return str(SPECS / pathlib.Path(p[len("/specs/"):]).name)
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        name = urllib.parse.parse_qs(u.query).get("name", [""])[0]
        if u.path != "/save" or not name or "/" in name or name.startswith("."):
            self.send_error(400)
            return
        OUT.mkdir(parents=True, exist_ok=True)
        data = self.rfile.read(int(self.headers["Content-Length"]))
        (OUT / name).write_bytes(data)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"{len(data)}".encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
