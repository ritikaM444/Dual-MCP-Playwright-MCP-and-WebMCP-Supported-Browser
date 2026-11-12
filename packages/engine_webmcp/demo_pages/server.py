#!/usr/bin/env python3
"""
Zero-dependency static file server for the WebMCP demo pages -- pure
standard library (http.server), so there's nothing to pip install for
this piece either. Run with:

    python packages/engine_webmcp/demo_pages/server.py
"""
from __future__ import annotations

import http.server
import os
import socketserver
from pathlib import Path

ROOT = Path(__file__).parent
POLYFILL_PATH = ROOT.parent / "polyfill" / "webmcp-polyfill.js"
PORT = int(os.environ.get("PORT", "4173"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming convention)
        if self.path == "/webmcp-polyfill.js":
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.end_headers()
            self.wfile.write(POLYFILL_PATH.read_bytes())
            return
        super().do_GET()


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    """One thread per connection.

    Must be threaded. A single-threaded server serves one connection at a
    time, and browsers open spare connections in advance that send nothing
    for a while; until that idle connection closes, every other request
    waits. With the Agent Street pages (7 files per page instead of 2) that
    showed up as 15-20 s page loads and failed navigations in a benchmark
    run (Nov 2026). Python's own `python -m http.server` is threaded for the
    same reason.
    """
    allow_reuse_address = True
    daemon_threads = True   # Ctrl+C stops the server without waiting on open connections


def main() -> None:
    with ReusableTCPServer(("", PORT), Handler) as httpd:
        print(f"Demo pages serving on http://localhost:{PORT}")
        print(f"  - http://localhost:{PORT}/todo-app/")
        print(f"  - http://localhost:{PORT}/product-search/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
