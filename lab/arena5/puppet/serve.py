"""Static server for lab/arena5 (the puppet imports ../lipsync) plus one write endpoint for the creation step.

    python3 lab/arena5/puppet/serve.py [port=8791]    then open http://127.0.0.1:8791/puppet/

POST /save?path=chars/<id>/pre/<shape>.png with a PNG body writes that file under puppet/chars/ only (the page's
export mode sends the puppet's own render of each mouth shape there, for gen.py mouths).
"""
import http.server
import pathlib
import re
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHARS = ROOT / "puppet" / "chars"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def do_POST(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        rel = q.get("path", [""])[0]
        if not re.fullmatch(r"chars/[a-z_]+/(pre|shots)/[A-Za-z0-9_.-]+\.(png|json)", rel):
            self.send_error(400, "bad path")
            return
        dest = (ROOT / "puppet" / rel).resolve()
        if CHARS.resolve() not in dest.parents:
            self.send_error(400, "outside chars")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
