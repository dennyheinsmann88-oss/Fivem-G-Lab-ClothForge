"""3D-Vorschau: kleiner lokaler Webserver, der Kleidung + Grundkörper an die Browser-Ansicht liefert."""

import base64
import json
import struct
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import editing, naming
from .builder import PLACEHOLDER_YTD, is_placeholder
from .resource import ResourceError, read_ydd, read_ytd

WEB_DIR = Path(__file__).parent / "preview_web"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}


@dataclass
class Item:
    id: str
    source: str            # "addon", "ersatz" oder "basis"
    gender: str
    is_prop: bool
    type_name: str
    number: int
    ydd: Path
    textures: dict = field(default_factory=dict)  # Buchstabe -> Pfad
    dlc: str = ""
    placeholder: bool = False
    resource: Path | None = None   # Resource, zu der das Teil gehört (fürs Löschen)

    def to_json(self):
        return {"id": self.id, "source": self.source, "gender": self.gender, "prop": self.is_prop,
                "type": self.type_name, "typeIndex": naming.PROPS.index(self.type_name) if self.is_prop
                else naming.COMPONENTS.index(self.type_name), "number": self.number, "dlc": self.dlc,
                "label": naming.COMPONENT_LABELS[self.type_name], "file": self.ydd.name,
                "textures": sorted(self.textures), "placeholder": self.placeholder,
                "placeholderTextures": sorted(k for k, p in self.textures.items() if is_placeholder(p, PLACEHOLDER_YTD))}


def _scan_folder(root, source, items, gender=None):
    """Sucht .ydd/.ytd in root; Texturen werden über Ordner + Prefix + Typ + Nummer zugeordnet."""
    ydds, textures = {}, defaultdict(dict)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".ydd", ".ytd"):
            continue
        cf = naming.parse(path, root)
        if cf is None:
            continue
        cf.gender = cf.gender or gender
        if cf.gender is None or cf.alt:
            continue
        key = (path.parent, cf.prefix, cf.gender, cf.is_prop, cf.type_name, cf.number)
        if cf.kind == "ydd":
            ydds[key] = cf
        else:
            textures[key].setdefault(cf.letter, path)
    for key, cf in ydds.items():
        dlc = cf.prefix.split("_freemode_01", 1)[-1].lstrip("_") if cf.prefix else ""
        dlc = "" if dlc == "p" else dlc.removeprefix("p_")
        items.append(Item("", source, cf.gender, cf.is_prop, cf.type_name, cf.number, cf.path,
                          dict(textures.get(key, {})), dlc, source == "addon" and is_placeholder(cf.path)))


def resource_folders(folder):
    """Eine Resource – oder bei einem [gruppen]-Ordner (aufgeteilte Resource) alle Resourcen darin."""
    if not folder or not Path(folder).is_dir():
        return []
    folder = Path(folder)
    if (folder / "fxmanifest.lua").is_file() or (folder / "stream").is_dir():
        return [folder]
    return [p for p in sorted(folder.iterdir()) if p.is_dir() and (p / "fxmanifest.lua").is_file()]


def build_catalog(resource_dir=None, base_dir=None, base_gender=None):
    """Alle Teile aus fertiger Resource (Addon + Ersatz) und Grundkörper-Ordner (Basis)."""
    items = []
    if base_dir and Path(base_dir).is_dir():
        _scan_folder(Path(base_dir), "basis", items, base_gender)
    for resource in resource_folders(resource_dir):
        before = len(items)
        replacements = resource / "stream" / "replacements"
        if replacements.is_dir():
            _scan_folder(replacements, "ersatz", items)
        middle = len(items)
        _scan_folder(resource / "stream" if (resource / "stream").is_dir() else resource, "addon", items)
        items[middle:] = [i for i in items[middle:] if replacements not in i.ydd.parents]
        for item in items[before:]:
            item.resource = resource

    # Ersatzdateien verdecken das Original; ohne eigene Texturen nutzen sie die Original-Texturen
    base = {(i.gender, i.is_prop, i.type_name, i.number, i.dlc): i for i in items if i.source == "basis"}
    result = []
    for item in items:
        k = (item.gender, item.is_prop, item.type_name, item.number, item.dlc)
        if item.source == "ersatz" and k in base:
            if not item.textures:
                item.textures = dict(base[k].textures)
            base.pop(k)
    for item in items:
        k = (item.gender, item.is_prop, item.type_name, item.number, item.dlc)
        if item.source != "basis" or base.get(k) is item:
            result.append(item)
    result.sort(key=lambda i: (i.gender, i.is_prop, i.to_json()["typeIndex"], {"basis": 0, "ersatz": 0}.get(i.source, 1),
                               i.dlc, i.number))
    for n, item in enumerate(result):
        item.id = str(n)
    return result


def _b64(data):
    return base64.b64encode(data).decode("ascii")


@lru_cache(maxsize=64)
def _model_json(path, mtime):
    drawables = read_ydd(Path(path).read_bytes())
    geoms = []
    for d in drawables[:1]:
        for model in d.best_lod():
            for g in model:
                if not g.indices:
                    continue
                geoms.append({
                    "positions": _b64(struct.pack(f"<{len(g.positions)}f", *g.positions)),
                    "uvs": _b64(struct.pack(f"<{len(g.uvs)}f", *g.uvs)) if g.uvs else None,
                    "indices": _b64(struct.pack(f"<{len(g.indices)}H", *g.indices)),
                })
    return json.dumps({"geometries": geoms}).encode()


@lru_cache(maxsize=64)
def _texture_json(path, mtime):
    textures = read_ytd(Path(path).read_bytes())
    if not textures:
        raise ResourceError("keine Textur in der Datei")
    t = textures[0]
    return json.dumps({"name": t.name, "width": t.width, "height": t.height, "format": t.format,
                       "data": _b64(t.data)}).encode()


class PreviewServer:
    """Startet den Server einmal; Ordner können später geändert werden."""

    def __init__(self):
        self.items = []
        self.resource_dir = None
        self.base_dir = None
        self.httpd = None
        self.lock = threading.Lock()
        self.undo_stack = []
        self.base_gender = None

    def set_folders(self, resource_dir, base_dir, base_gender=None):
        self.resource_dir, self.base_dir, self.base_gender = resource_dir, base_dir, base_gender
        self.items = build_catalog(resource_dir, base_dir, base_gender)
        self.undo_stack = []

    def edit(self, action, item=None, letter=None):
        """Löschen / Rückgängig; danach wird der Katalog neu eingelesen."""
        with self.lock:
            if not self.resource_dir:
                raise editing.EditError("Keine fertige Resource gewählt")
            if action == "undo":
                if not self.undo_stack:
                    raise editing.EditError("Nichts zum Rückgängigmachen")
                resource, change = self.undo_stack.pop()
                editing.undo(resource, change)
                message = f"Rückgängig: {change.message}"
            else:
                if item is None or item.source not in ("addon", "ersatz"):
                    raise editing.EditError("Nur Teile aus der fertigen Resource können gelöscht werden")
                if letter:
                    if letter not in item.textures:
                        raise editing.EditError("Textur nicht gefunden")
                    change = editing.delete_texture(item.resource, item.textures[letter])
                else:
                    change = editing.delete_drawable(item.resource, item.ydd)
                self.undo_stack.append((item.resource, change))
                message = change.message
            stack = self.undo_stack
            _model_json.cache_clear()
            _texture_json.cache_clear()
            self.items = build_catalog(self.resource_dir, self.base_dir, self.base_gender)
            self.undo_stack = stack
            return {"ok": True, "message": message, "canUndo": bool(stack)}

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/" if self.httpd else None

    def start(self, port=0):
        if self.httpd:
            return self.url
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, body, ctype="application/json", status=200):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def error(self, message, status=400):
                self.send(json.dumps({"error": message}).encode(), status=status)

            def item(self, query):
                try:
                    return server.items[int(query.get("id", ["-1"])[0])]
                except (ValueError, IndexError):
                    return None

            def do_POST(self):
                url = urlparse(self.path)
                # Nur die eigene Vorschau-Seite darf ändern: eigener Header erzwingt bei fremden Seiten eine
                # CORS-Vorabfrage, die dieser Server nie beantwortet.
                origin = self.headers.get("Origin")
                if self.headers.get("X-ClothTool") != "1" or (origin and origin.rstrip("/") != server.url.rstrip("/")):
                    return self.error("nicht erlaubt", 403)
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if url.path == "/api/delete":
                        item = self.item({"id": [str(body.get("id", "-1"))]})
                        result = server.edit("delete", item, body.get("letter") or None)
                    elif url.path == "/api/undo":
                        result = server.edit("undo")
                    else:
                        return self.error("nicht gefunden", 404)
                    return self.send(json.dumps(result).encode())
                except editing.EditError as exc:
                    return self.error(str(exc), 409)
                except (OSError, ValueError) as exc:
                    return self.error(f"Fehler: {exc}", 500)

            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                try:
                    if url.path == "/api/catalog":
                        body = {"items": [i.to_json() for i in server.items],
                                "resource": str(server.resource_dir or ""), "base": str(server.base_dir or "")}
                        return self.send(json.dumps(body).encode())
                    if url.path == "/api/model":
                        item = self.item(query)
                        if not item:
                            return self.error("unbekanntes Teil", 404)
                        return self.send(_model_json(str(item.ydd), item.ydd.stat().st_mtime))
                    if url.path == "/api/texture":
                        item = self.item(query)
                        letter = query.get("letter", [""])[0]
                        if not item or letter not in item.textures:
                            return self.error("Textur nicht gefunden", 404)
                        path = item.textures[letter]
                        return self.send(_texture_json(str(path), path.stat().st_mtime))
                    rel = url.path.lstrip("/") or "index.html"
                    path = (WEB_DIR / rel).resolve()
                    if WEB_DIR.resolve() not in path.parents or not path.is_file():
                        return self.error("nicht gefunden", 404)
                    return self.send(path.read_bytes(), CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
                except (ResourceError, OSError, struct.error, ValueError) as exc:
                    return self.error(str(exc), 500)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.url

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
