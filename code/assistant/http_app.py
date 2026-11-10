# Showcase excerpt from a private project - not runnable on its own. See ../../README.md and LICENSE.
"""MCP über HTTP (Streamable HTTP) für den Fernzugriff, z. B. über einen Cloudflare-Tunnel.

Schutz in drei Schichten (außen nach innen):
1. `McpGate`: Zugang nur mit geheimem Token (`Authorization: Bearer …`, konstanter Zeitvergleich) oder – wenn der
   Konnektor keinen Header setzen kann – über einen geheimen URL-Pfad (`MCP_PATH_SECRET`). Sonst 401 ohne Details.
   Dazu eine einfache Begrenzung der Anfragen pro Minute und der Fehlversuche.
2. DNS-Rebinding-Schutz des SDK: nur der Hostname aus `MCP_ALLOWED_HOST` (und localhost) wird angenommen.
3. Die Werkzeuge selbst (Entwürfe, Stopp-Fenster, Protokoll `ToolCall`) – dieselben wie im stdio-Modus.

Token und Pfad-Geheimnis werden nie geloggt oder ausgegeben (auch kein Zugriffsprotokoll von uvicorn).

Diagnose (`MCP_DEBUG`, B-049): Mit `debug=True` schreibt die Schranke für jede abgelehnte Anfrage (Status 400 und höher) eine Logzeile mit
Grund, Statuscode, Methode, Pfad und Host-Name. Nie ins Log: Token, Pfad-Geheimnis, Authorization-Header, Query-Werte, Cookies (der Pfad
erscheint ohne Geheimnis-Anteil, dafür „***“). Ohne `debug` entsteht keine zusätzliche Logzeile.
"""
import hashlib
import hmac
import logging
import re
import time
from collections import deque

from mcp.server.transport_security import TransportSecuritySettings

from .server import build_server

MIN_SECRET_LENGTH = 32
MCP_PATH = "/mcp"
debug_log = logging.getLogger("apps.assistant.mcp_debug")


class McpConfigError(Exception):
    """Fernzugriff ist nicht sicher genug eingerichtet – Text ist lesbar, enthält nie das Geheimnis."""


def check_secrets(token: str, path_secret: str = "") -> None:
    if len(token or "") < MIN_SECRET_LENGTH:
        raise McpConfigError(f"MCP_TOKEN fehlt oder ist zu kurz (mindestens {MIN_SECRET_LENGTH} Zeichen). "
                             "Erzeugen z. B. mit: python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    if path_secret:
        if len(path_secret) < MIN_SECRET_LENGTH:
            raise McpConfigError(f"MCP_PATH_SECRET ist zu kurz (mindestens {MIN_SECRET_LENGTH} Zeichen).")
        if not all(c.isalnum() or c in "-_" for c in path_secret):
            raise McpConfigError("MCP_PATH_SECRET darf nur Buchstaben, Ziffern, „-“ und „_“ enthalten.")
        if path_secret == token:
            raise McpConfigError("MCP_PATH_SECRET und MCP_TOKEN müssen verschieden sein.")


def _digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def _equal(a: bytes, b: bytes) -> bool:
    """Konstanter Zeitvergleich, auch unabhängig von der Länge (beide vorher gehasht)."""
    return hmac.compare_digest(_digest(a), _digest(b))


class _Window:
    """Zählt Ereignisse der letzten 60 Sekunden."""

    def __init__(self, limit: int, clock):
        self.limit, self.clock, self.events = limit, clock, deque()

    def _trim(self) -> None:
        cutoff = self.clock() - 60
        while self.events and self.events[0] <= cutoff:
            self.events.popleft()

    def exceeded(self) -> bool:
        self._trim()
        return len(self.events) >= self.limit

    def add(self) -> None:
        self._trim()
        self.events.append(self.clock())


class McpGate:
    """ASGI-Schranke vor dem MCP-Server: prüft Token oder Pfad-Geheimnis und begrenzt die Anfragen."""

    def __init__(self, app, token: str, path_secret: str = "", requests_per_minute: int = 120,
                 failures_per_minute: int = 20, clock=time.monotonic, debug: bool = False):
        check_secrets(token, path_secret)
        self.app = app
        self.debug = debug
        self._token = token.encode()
        self._path_secret = path_secret.encode()
        self._requests = _Window(max(1, requests_per_minute), clock)
        self._failures = _Window(max(1, failures_per_minute), clock)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # lifespan (Start/Ende) durchreichen
            await self.app(scope, receive, send)
            return
        path = self._authorized_path(scope)
        if path is None:
            if self._failures.exceeded():
                self._debug(scope, 429, "Begrenzung der Fehlversuche pro Minute")
                await self._reply(send, 429, [(b"retry-after", b"60")])
            else:
                self._failures.add()
                self._debug(scope, 401, self._reject_reason(scope))
                await self._reply(send, 401, [(b"www-authenticate", b"Bearer")])
            return
        if self._requests.exceeded():
            self._debug(scope, 429, "Begrenzung der Anfragen pro Minute")
            await self._reply(send, 429, [(b"retry-after", b"60")])
            return
        self._requests.add()
        inner = {**scope, "path": path, "raw_path": path.encode()}
        if not self.debug:
            await self.app(inner, receive, send)
            return
        seen = []

        async def spy(message):
            if message["type"] == "http.response.start":
                seen.append(message["status"])
            await send(message)

        await self.app(inner, receive, spy)
        if seen and seen[0] >= 400:   # vom MCP-Server selbst abgelehnt (Host, Pfad, Methode, Accept-Header)
            self._debug(scope, seen[0], self._inner_reason(seen[0]))

    # ---- Diagnose (nur mit debug) ----

    def _debug(self, scope, status: int, reason: str) -> None:
        if not self.debug:
            return
        headers = dict(scope.get("headers") or [])
        raw = headers.get(b"host", b"").decode("latin-1")
        host = raw.split("]")[0] + "]" if raw.startswith("[") else raw.rsplit(":", 1)[0]   # nur der Host-Name, ohne Port
        host = self._redact(host)
        host = host if re.fullmatch(r"[A-Za-z0-9.\-\[\]:*]{1,100}", host) else "?"
        method = re.sub(r"[^A-Z]", "?", str(scope.get("method", "?")).upper())[:10]
        debug_log.warning("MCP abgelehnt: %s – Status %s – %s %s – Host %s", reason, status, method, self._safe_path(scope.get("path", "")), host)

    def _redact(self, text: str) -> str:
        """Token und Pfad-Geheimnis in einem Text (Pfad, Host-Name) durch „***“ ersetzen."""
        for secret in (self._path_secret.decode(), self._token.decode()):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _safe_path(self, path: str) -> str:
        """Pfad für das Log: Token und Pfad-Geheimnis durch „***“ ersetzt, bei /<irgendwas>/mcp der erste Teil (er könnte ein Fehlversuch am
        Geheimnis sein), nur druckbare Zeichen, höchstens 120 Zeichen. Die Query gehört nie dazu."""
        path = self._redact(path)
        parts = path.split("/")
        if self._path_secret and len(parts) == 3 and parts[2] == MCP_PATH.lstrip("/"):
            parts[1] = "***"
        return re.sub(r"[^\x21-\x7e]", "?", "/".join(parts))[:120]

    def _reject_reason(self, scope) -> str:
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"")
        path = scope.get("path", "")
        parts = path.strip("/").split("/")
        if not auth:
            if self._path_secret and len(parts) == 2 and parts[1] == MCP_PATH.lstrip("/"):
                reason = "Pfad-Geheimnis falsch"
            else:
                reason = "Token fehlt"
        else:
            scheme, _, credential = auth.partition(b" ")
            if scheme.lower() != b"bearer":
                reason = "Authorization ist kein Bearer-Token"
            elif not credential.strip():
                reason = "Token leer"
            else:
                reason = "Token falsch"
        if path.startswith("/.well-known/"):
            reason += " (Erkennungsadresse /.well-known/…)"
        elif not self._path_secret and path != MCP_PATH:
            reason += " (Pfad ist nicht /mcp)"
        elif self._path_secret and len(parts) == 2 and parts[1] != MCP_PATH.lstrip("/"):
            reason += " (Pfad ist nicht …/mcp)"
        return reason

    @staticmethod
    def _inner_reason(status: int) -> str:
        return {
            421: "Host nicht erlaubt (MCP_ALLOWED_HOST prüfen)", 403: "Origin oder Host nicht erlaubt", 400: "Anfrage ungültig (Host oder Origin)",
            404: "Pfad nicht vorhanden (der Server kennt nur /mcp)", 405: "Methode nicht erlaubt",
            406: "Accept-Header passt nicht (application/json und text/event-stream nötig)",
        }.get(status, "vom MCP-Server abgelehnt")

    def _authorized_path(self, scope) -> str | None:
        """Pfad für den inneren Server, wenn der Zugriff erlaubt ist; sonst None."""
        path = scope["path"]
        if self._path_secret:
            parts = path.strip("/").split("/")
            if len(parts) == 2 and parts[1] == MCP_PATH.lstrip("/") and _equal(parts[0].encode(), self._path_secret):
                return MCP_PATH  # /<geheimnis>/mcp → /mcp
        headers = dict(scope.get("headers") or [])
        scheme, _, credential = headers.get(b"authorization", b"").partition(b" ")
        if scheme.lower() == b"bearer" and _equal(credential.strip(), self._token):
            return path
        return None

    @staticmethod
    async def _reply(send, status: int, headers: list) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-length", b"0"), *headers]})
        await send({"type": "http.response.body", "body": b""})


def build_http_app(token: str, path_secret: str = "", allowed_host: str = "", requests_per_minute: int = 120,
                   clock=time.monotonic, debug: bool = False):
    """ASGI-App: Schranke → MCP-Server (Streamable HTTP unter /mcp, ohne Sitzungszustand)."""
    check_secrets(token, path_secret)
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    if allowed_host:
        hosts += [allowed_host, f"{allowed_host}:*"]
        origins += [f"https://{allowed_host}"]
    server = build_server(
        stateless_http=True, json_response=True, streamable_http_path=MCP_PATH,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins),
    )
    return McpGate(server.streamable_http_app(), token, path_secret, requests_per_minute, clock=clock, debug=debug)
