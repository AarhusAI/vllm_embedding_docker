"""Tiny bearer-token validator used by nginx auth_request.

Reads /keys/api_keys.txt on every request so add/revoke is live without restart.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KEYS_FILE = Path("/keys/api_keys.txt")
BIND_HOST = "0.0.0.0"
BIND_PORT = 8000


def load_keys() -> set[str]:
    if not KEYS_FILE.exists():
        return set()
    keys = set()
    for line in KEYS_FILE.read_text().splitlines():
        key = line.split("#", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def extract_token(header_value: str) -> str:
    value = (header_value or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


class Handler(BaseHTTPRequestHandler):
    def _verify(self) -> None:
        token = extract_token(self.headers.get("X-Original-Authorization", ""))
        if token and token in load_keys():
            self.send_response(204)
        else:
            self.send_response(401)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.startswith("/verify"):
            self._verify()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        self.do_GET()

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler).serve_forever()
