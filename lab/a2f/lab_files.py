"""Round 4 helper on 127.0.0.1:8099: serves the arena inputs (GET /f/<name> from lab/inputs/round4/jasom) and
saves what the arena page records (POST /save/<name> into lab/benchmark/results/round4). Local only.
    python3 lab/a2f/lab_files.py
"""
import http.server, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
IN, OUT = ROOT / "inputs/round4/jasom", ROOT / "benchmark/results/round4"
OUT.mkdir(parents=True, exist_ok=True)
TYPES = {".wav": "audio/wav", ".json": "application/json", ".csv": "text/csv", ".png": "image/png", ".jpg": "image/jpeg"}


class H(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        p = (IN / self.path.removeprefix("/f/")).resolve()
        if not self.path.startswith("/f/") or not p.is_relative_to(IN) or not p.is_file():
            self.send_response(404); self._cors(); self.end_headers(); return
        data = p.read_bytes()
        self.send_response(200); self._cors()
        self.send_header("Content-Type", TYPES.get(p.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_POST(self):
        name = pathlib.Path(self.path.removeprefix("/save/")).name
        data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        (OUT / name).write_bytes(data)
        self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(f"{len(data)}".encode())

    def log_message(self, *a):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 8099), H).serve_forever()
