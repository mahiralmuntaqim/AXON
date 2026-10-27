"""Tiny stdlib server for the visualizer (SEGMENT 17) — read-only, decoupled from the agent.

Two roles, no agent coupling:

* serves ``index.html`` and static files;
* ``/stream`` is a Server-Sent-Events channel. On connect it first sends the current snapshot
  (the first SNAPSHOT event in the log) so a late viewer starts from a known base graph, then
  streams subsequent events as they are appended to the log (replay-as-live tailing).

The Python side only *emits* events (the engagement loop writes the JSONL log) and serves them
here. It never reads anything back from the viewer.

Usage:
    python -m viz.serve --events events.jsonl --port 8765
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    events_path = "events.jsonl"

    def log_message(self, *_a):  # quiet
        return

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/stream"):
            return self._stream()
        name = "index.html" if self.path in ("/", "") else self.path.lstrip("/")
        f = HERE / name
        if not f.is_file():
            self.send_error(404)
            return
        body = f.read_bytes()
        ctype = "text/html" if f.suffix == ".html" else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        path = Path(self.events_path)
        sent = 0
        snapshot_sent = False
        try:
            while True:
                if path.is_file():
                    lines = path.read_text(encoding="utf-8").splitlines()
                    # Ensure the snapshot goes first even if the viewer connected late.
                    if not snapshot_sent and lines:
                        for ln in lines:
                            if ln.strip() and json.loads(ln).get("type") == "snapshot":
                                self._send(ln)
                                snapshot_sent = True
                                break
                    for ln in lines[sent:]:
                        if ln.strip():
                            self._send(ln)
                    sent = len(lines)
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _send(self, line: str) -> None:
        self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
        self.wfile.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="events.jsonl")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    Handler.events_path = args.events
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"viz server: http://127.0.0.1:{args.port}/  (streaming {args.events})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
