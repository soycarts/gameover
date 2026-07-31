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
BLOCKED = {".env", ".git", ".venv", ".ssh", ".aws", ".DS_Store",
           # The same three .vercelignore keeps off the public site. This server
           # binds 0.0.0.0, so "local dev" means everyone on the wifi — and
           # COMPLIANCE.md in particular states in writing that the footage is
           # unlicensed and lists what is not yet fixed. Not dotfiles, so the
           # rule above does not reach them.
           "CLAUDE.md", "HANDOVER.md", "COMPLIANCE.md", "transcripts"}


class _Slice:
    """A file object that stops after `remaining` bytes, so copyfile() writes
    exactly the requested range and nothing past it."""

    def __init__(self, fp, remaining: int):
        self._fp, self._left = fp, remaining

    def read(self, size: int = -1) -> bytes:
        if self._left <= 0:
            return b""
        if size is None or size < 0:
            size = self._left
        chunk = self._fp.read(min(size, self._left))
        self._left -= len(chunk)
        return chunk

    def close(self):
        self._fp.close()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    # The same rewrites vercel.json declares. Kept in step ON PURPOSE: a route
    # that exists in production and 404s in dev is how the sprites.js path bug
    # survived — it worked perfectly locally and was broken on the public site.
    # Here it would be the reverse, and the takedown page is the last thing that
    # should be discovered broken.
    REWRITES = {"/": "/frontend/index.html",
                "/about": "/frontend/about.html",
                "/takedown": "/frontend/takedown.html"}

    def _rewrite(self) -> None:
        path, sep, query = self.path.partition("?")
        dest = self.REWRITES.get(path.rstrip("/") or "/")
        if dest:
            self.path = dest + sep + query      # the query survives, as on Vercel

    def _blocked(self) -> bool:
        parts = Path(self.path.split("?")[0]).parts
        return any(p in BLOCKED or p.startswith(".") for p in parts if p != "/")

    def list_directory(self, path):            # no directory listings
        self.send_error(404, "Not Found")
        return None

    # ---- HTTP Range ------------------------------------------------------
    # SimpleHTTPRequestHandler ignores the Range header and answers 200 with the
    # whole file. Browsers need 206 to seek inside an mp4, so without this you
    # cannot scrub the clip: currentTime snaps straight back to 0. Vercel serves
    # ranges already, so this only ever bit local dev — which is where demos get
    # rehearsed.
    def send_head(self):
        self._rewrite()
        if self._blocked():
            self.send_error(404, "Not Found")
            return None
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()

        path = self.translate_path(self.path)
        if not Path(path).is_file():
            return super().send_head()
        try:
            units, _, span = rng.partition("=")
            if units.strip() != "bytes":
                raise ValueError(rng)
            first, _, last = span.partition("-")
            size = Path(path).stat().st_size
            start = int(first) if first else None
            if start is None:                       # suffix form: "bytes=-500"
                start, end = max(0, size - int(last)), size - 1
            else:
                end = int(last) if last else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                raise ValueError(rng)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{Path(path).stat().st_size}")
            self.end_headers()
            return None

        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        return _Slice(f, end - start + 1)


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
