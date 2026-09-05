"""HTTP server + API key middleware.

Jalankan:
  python -m qris.server                  # serve (env: QRIS_HOST, QRIS_PORT)
  python -m qris.server --gen-key        # cetak API key baru + sha256 hash-nya

API key (mode jual akses):
  - QRIS_API_KEYS = daftar sha256 hex, dipisah koma. Kosong = mode terbuka (dev lokal).
  - Client kirim header X-API-Key (atau Authorization: Bearer).
  - Salah/hilang -> 401. Lewat QRIS_RATE_LIMIT permintaan/menit per key -> 429.
  - Server TIDAK menyimpan key mentah — cuma hash. Revoke = hapus hash dari env.
  ponytail: rate limit window 60 detik in-memory + tanpa usage log; naik ke
  DB/Redis atau API gateway (Kong/CF) saat jual beneran + butuh billing.
"""
import argparse
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import NAMES, convert, generate_api_key, parse

HOST = os.environ.get("QRIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("QRIS_PORT", "8000"))
RATE_PER_MIN = int(os.environ.get("QRIS_RATE_LIMIT", "60"))

_buckets = {}  # ident -> (window_menit, count)


def _key_hashes():
    raw = os.environ.get("QRIS_API_KEYS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _allow(ident: str) -> bool:
    win = int(time.time() // 60)
    w, c = _buckets.get(ident, (0, 0))
    if w != win:
        w, c = win, 0
    c += 1
    _buckets[ident] = (w, c)
    return c <= RATE_PER_MIN


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization")
        self.end_headers()

    def _check_auth(self):
        """Return ident untuk bucket/rate-limit, atau None bila ditolak (response terkirim).
        ident = 12 hex pertama dari hash key — key mentah tidak pernah disimpan/di-log."""
        hashes = _key_hashes()
        if not hashes:
            return "open:" + self.client_address[0]
        key = self.headers.get("X-API-Key")
        if not key:
            auth = self.headers.get("Authorization", "")
            key = auth[7:].strip() if auth.startswith("Bearer ") else None
        if key:
            h = hashlib.sha256(key.encode("utf-8")).hexdigest()
            for stored in hashes:
                if hmac.compare_digest(h, stored):
                    return "key:" + h[:12]
        self._json(401, {"ok": False, "error": "API key hilang atau salah (header X-API-Key)"})
        return None

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/health"):
            self._json(200, {"ok": True, "service": "qris-static2dynamic",
                             "auth": bool(_key_hashes()),
                             "rate_limit_per_min": RATE_PER_MIN,
                             "endpoints": ["POST /convert", "POST /parse"]})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/convert", "/parse"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        ident = self._check_auth()
        if ident is None:
            return
        if not _allow(ident):
            self._json(429, {"ok": False, "error": f"rate limit {RATE_PER_MIN} permintaan/menit"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > 8192:
            self._json(413, {"ok": False, "error": "body terlalu besar (max 8KB)"})
            return
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "JSON tidak valid"})
            return
        try:
            if path == "/parse":
                self._json(200, {"ok": True, "data": {"tags": [
                    {"tag": t, "name": NAMES.get(t), "value": v} for t, v in parse(req.get("qr"))]}})
            else:
                self._json(200, {"ok": True, "data": {
                    "payload": convert(req.get("qr"), req.get("amount"), req.get("fee"))}})
        except ValueError as e:
            self._json(400, {"ok": False, "error": str(e)})

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(description="QRIS converter API server")
    ap.add_argument("--gen-key", action="store_true",
                    help="cetak API key baru + sha256 hash untuk QRIS_API_KEYS")
    a = ap.parse_args()
    if a.gen_key:
        key, h = generate_api_key()
        print("API key (simpan sekarang, tidak ditampilkan lagi):")
        print(key)
        print("sha256 hash (taruh di QRIS_API_KEYS, dipisah koma bila lebih dari satu):")
        print(h)
        return
    mode = "ON" if _key_hashes() else "OFF (dev)"
    print(f"qris api on {HOST}:{PORT} | auth={mode} | rate={RATE_PER_MIN}/menit")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
