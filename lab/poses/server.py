"""Pose session (lab): the guided recording of a person's own body clips, the same five moments the call uses
(listen, greet, explain, emphasis, think). Serves record.html, Jin's round 3 clips as the demonstration, the local face
model for the live checks, and saves every take.

    backend/.venv/bin/python lab/poses/server.py        ->  http://localhost:8770
    backend/.venv/bin/python lab/poses/prepare.py <name> (afterwards: crop, cut and the voice sample)

Takes land in lab/inputs/poses/<name>/raw/<pose>.<webm|mp4>; media stays out of git. Localhost only: the camera needs a
secure origin, and localhost counts as one.
"""
import json
import pathlib
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = pathlib.Path(__file__).parent
LAB = HERE.parent
DEMO = LAB / "inputs/round3/jin/clips"
OUT = LAB / "inputs/poses"
MODEL = pathlib.Path.home() / ".cache/mediapipe/face_landmarker.task"
POSES = ("listen", "greet", "explain", "emphasis", "think")
PORT = 8770
SAFE = re.compile(r"^[a-z0-9_-]{1,40}$")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: pathlib.Path, ctype: str):
        if not path.is_file():
            return self._send(404, b"not found", "text/plain")
        data = path.read_bytes()
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d+)-(\d*)", rng)):  # video elements seek and loop with ranges
            start, end = int(m[1]), int(m[2] or len(data) - 1)
            chunk = data[start:end + 1]
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/record.html"):
            return self._file(HERE / "record.html", "text/html; charset=utf-8")
        if m := re.fullmatch(r"/demo/(\w+)\.mp4", url.path):
            return self._file(DEMO / f"{m[1]}.mp4", "video/mp4") if m[1] in POSES else self._send(404, b"", "text/plain")
        if url.path == "/model/face_landmarker.task":
            return self._file(MODEL, "application/octet-stream")
        if url.path == "/takes":
            name = parse_qs(url.query).get("name", [""])[0]
            raw = OUT / name / "raw"
            done = sorted(p.stem for p in raw.glob("*.*") if p.suffix in (".webm", ".mp4")) if SAFE.match(name) and raw.is_dir() else []
            return self._send(200, json.dumps(done).encode(), "application/json")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        name, pose = q.get("name", [""])[0], q.get("pose", [""])[0]
        if url.path != "/save" or not SAFE.match(name) or pose not in POSES:
            return self._send(400, b"bad request", "text/plain")
        ext = "mp4" if "mp4" in (self.headers.get("Content-Type") or "") else "webm"
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size < 200_000_000:
            return self._send(400, b"bad size", "text/plain")
        raw = OUT / name / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        for old in raw.glob(f"{pose}.*"):
            old.unlink()  # a retake replaces the take
        (raw / f"{pose}.{ext}").write_bytes(self.rfile.read(size))
        checks = q.get("checks", ["{}"])[0]
        (raw / f"{pose}.checks.json").write_text(checks)
        print(f"saved {name}/{pose}.{ext} ({size / 1e6:.1f} MB) checks={checks}", flush=True)
        self._send(200, b'{"ok":true}', "application/json")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    print(f"Pose session on http://localhost:{PORT}  (takes -> {OUT})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
