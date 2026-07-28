#!/usr/bin/env python3
"""serve.py [port] — static server for the HUD that refuses to leak dotfiles.

    python3 backend/serve.py            # port 40911, all interfaces
    python3 backend/serve.py 8000

Same as `python -m http.server` (serves the repo root so the page can reach
../clips, ../timelines, ../comments) except it 404s .env, .git and every other
dotfile, and it does not render directory listings. Use this rather than
http.server when anyone else is on your network.
"""
import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCKED = {".env", ".git", ".venv", ".ssh", ".aws", ".DS_Store"}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def _blocked(self) -> bool:
        parts = Path(self.path.split("?")[0]).parts
        return any(p in BLOCKED or p.startswith(".") for p in parts if p != "/")

    def send_head(self):
        if self._blocked():
            self.send_error(404, "Not Found")
            return None
        return super().send_head()

    def list_directory(self, path):            # no directory listings
        self.send_error(404, "Not Found")
        return None


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 40911
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", port), Handler) as httpd:
        print(f"serving {ROOT} on http://0.0.0.0:{port}  (dotfiles blocked)")
        print(f"  demo:  http://localhost:{port}/frontend/index.html?demo=1")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
