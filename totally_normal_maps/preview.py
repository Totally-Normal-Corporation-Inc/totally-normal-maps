"""Read-only loopback preview; only generated display artifacts are served."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .catalogue import CatalogueError, PROVINCES
from .web_security import MAP_CSP


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory, **kwargs):
        self.preview_directory = Path(directory).resolve()
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        self.do_HEAD(body=True)

    def do_HEAD(self, body=False):
        port = self.server.server_port
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self.send_error(403)
            return
        name = unquote(urlsplit(self.path).path).removeprefix("/") or "index.html"
        allowed = {"index.html", "preview.js", "preview.css", "leaflet.js", "leaflet.css", "catalogue.json", "provinces.geojson"} | {f"{key}.geojson" for key in PROVINCES} | {f"regions-{key}.geojson" for key in PROVINCES} | {f"city-areas-{key}.geojson" for key in PROVINCES} | {f"electoral-{key}.geojson" for key in PROVINCES} | {f"municipal-{key}.geojson" for key in PROVINCES}
        path = self.preview_directory / name
        if name not in allowed or path.is_symlink() or not path.is_file():
            self.send_error(404)
            return
        self.path = "/" + name
        stream = super().send_head()
        if stream:
            try:
                if body:
                    self.copyfile(stream, self.wfile)
            finally:
                stream.close()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", MAP_CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()


def make_server(run, port):
    root = (Path(run) / "preview").resolve()
    if not (root / "catalogue.json").is_file():
        raise CatalogueError("Build a catalogue before starting the preview.")
    if not 0 <= port <= 65535:
        raise CatalogueError("Invalid preview port.")
    return ThreadingHTTPServer(("127.0.0.1", port), partial(PreviewHandler, directory=root))
