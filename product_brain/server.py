"""Local web server for the office UI: python -m product_brain serve

Serves web/ as static files plus a tiny JSON API over the run outputs:
    GET /api/runs        every run under runs/, newest first
    GET /api/runs/<id>   one run's run.json
"""
from __future__ import annotations

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .viewer_export import _label

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def run_index(runs_root: Path) -> list[dict]:
    out = []
    for path in runs_root.glob("*/run.json"):
        try:
            run = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue  # a run that is still being written
        meta = run["meta"]
        out.append({"id": path.parent.name, "label": _label(meta), "mode": meta["mode"], "seed": meta["seed"],
                    "days": meta["days"], "extract": meta["extract"], "product": meta["product"],
                    "agent_model": meta.get("agent_model"), "updated": path.stat().st_mtime,
                    "has_agents": bool(run["days"]) and "agents" in run["days"][0], "summary": run["summary"]})
    return sorted(out, key=lambda r: r["updated"], reverse=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, runs_root: Path, **kwargs):
        self.runs_root = runs_root
        super().__init__(*args, directory=str(WEB), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/runs":
            return self._send(200, json.dumps(run_index(self.runs_root)).encode())
        if path.startswith("/api/runs/"):
            rid = unquote(path.removeprefix("/api/runs/"))
            target = (self.runs_root / rid / "run.json").resolve()
            if "/" in rid or rid.startswith(".") or not target.is_file() or self.runs_root.resolve() not in target.parents:
                return self._send(404, b'{"error": "no such run"}')
            return self._send(200, target.read_bytes())
        return super().do_GET()

    def _send(self, code: int, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # always show the latest runs and code
        super().end_headers()

    def log_message(self, *args):
        pass


def serve(port: int = 8000, runs_root: str = "runs"):
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, runs_root=Path(runs_root)))
    print(f"Product Brain office: http://localhost:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
