#!/usr/bin/env python3
"""QRIS static->dynamic converter + HTTP API. Stdlib only.

Jalankan:
  python3 qris_api.py            # serve di HOST:PORT (default 127.0.0.1:8000)
  python3 qris_api.py --test     # self-check

Endpoint:
  POST /convert {"qr": "<string QRIS>", "amount": 15750, "fee": {"type":"fixed|percent","value":...}}
  POST /parse   {"qr": "<string QRIS>"}
Logika identik verssache/qris-dinamis: drop 54/55/56/57/63, tag 01 -> "12",
sisip 53(bila absen)+54(+fee 55/56 atau 55/57) sebelum 58, CRC16-CCITT-FALSE.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

NAMES = {
    "00": "Payload Format Indicator", "01": "Point of Initiation Method",
    "26": "Merchant Account Information", "52": "Merchant Category Code",
    "53": "Transaction Currency", "54": "Transaction Amount",
    "55": "Tip or Convenience Indicator", "56": "Value of Convenience Fee (Fixed)",
    "57": "Value of Convenience Fee (%)", "58": "Country Code",
    "59": "Merchant Name", "60": "Merchant City", "61": "Postal Code",
    "62": "Additional Data Field", "63": "CRC",
}


def crc16(s: str) -> str:
    crc = 0xFFFF
    for ch in s:
        crc ^= ord(ch) << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def parse(qr: str):
    """Validasi + parse TLV top-level. ponytail: tanpa rekursi template 26/62;
    tambahkan saat perlu edit isi tag 26 (mis. ganti NMID)."""
    if not isinstance(qr, str) or len(qr) < 20:
        raise ValueError("QR string kosong atau terlalu pendek")
    if not qr.startswith("000201"):
        raise ValueError("bukan QRIS: payload harus mulai '000201'")
    if any(not (0x20 <= ord(c) <= 0x7E) for c in qr):
        raise ValueError("karakter non-printable-ASCII ditolak")
    body, crc = qr[:-4], qr[-4:]
    got = crc16(body)
    if got != crc.upper():
        raise ValueError(f"CRC mismatch: hitung {got}, dapat {crc}")
    tags, i = [], 0
    while i < len(body):
        if i + 4 > len(body):
            raise ValueError("TLV terpotong (header)")
        tag = body[i:i + 2]
        if tag == "63":
            break  # tag CRC: value-nya 4 char paling akhir, sudah divalidasi terpisah
        if not body[i + 2:i + 4].isdigit():
            raise ValueError(f"panjang non-numerik di tag {tag}")
        n = int(body[i + 2:i + 4])
        if i + 4 + n > len(body):
            raise ValueError(f"TLV terpotong (value tag {tag})")
        tags.append((tag, body[i + 4:i + 4 + n]))
        i += 4 + n
    if not tags:
        raise ValueError("TLV kosong")
    return tags


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise ValueError(f"value tag {tag} lebih dari 99 karakter")
    return f"{tag}{len(value):02d}{value}"


def convert(qr: str, amount, fee=None) -> str:
    tags = parse(qr)
    if isinstance(amount, str) and amount.isdigit():
        amount = int(amount)
    if isinstance(amount, bool) or not isinstance(amount, int) or not (0 < amount <= 999_999_999):
        raise ValueError("amount harus integer 1..999999999")
    fixed = pct = None
    if fee is not None:
        if not isinstance(fee, dict):
            raise ValueError("fee harus object {type,value}")
        t, v = fee.get("type"), fee.get("value")
        if t == "fixed":
            if isinstance(v, str) and v.isdigit():
                v = int(v)
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise ValueError("fee.value fixed harus integer >0")
            fixed = v
        elif t == "percent":
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 < v <= 99):
                raise ValueError("fee.value percent harus 0<v<=99")
            pct = v
        else:
            raise ValueError("fee.type harus 'fixed' atau 'percent'")

    out, injected = [], False
    has53 = any(t == "53" for t, _ in tags)

    def inject():
        nonlocal injected
        if not has53:
            out.append(("53", "360"))
        out.append(("54", str(amount)))
        if fixed is not None:
            out.append(("55", "02"))
            out.append(("56", str(fixed)))
        elif pct is not None:
            out.append(("55", "03"))
            out.append(("57", f"{pct:g}"))
        injected = True

    for t, v in tags:
        if t in ("54", "55", "56", "57", "63"):
            continue
        if t == "01":
            out.append(("01", "12"))
            continue
        if t == "58" and not injected:
            inject()
        out.append((t, v))
    if not injected:
        inject()
    s = "".join(_tlv(t, v) for t, v in out) + "6304"
    return s + crc16(s)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/health"):
            self._json(200, {"ok": True, "service": "qris-static2dynamic",
                             "endpoints": ["POST /convert", "POST /parse"],
                             "example": {"qr": "<string QRIS mulai 000201>", "amount": 15750,
                                         "fee": {"type": "fixed", "value": 500}}})
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/convert", "/parse"):
            self._json(404, {"ok": False, "error": "not found"})
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


def _selftest():
    assert crc16("123456789") == "29B1", "CRC-16/CCITT-FALSE vector gagal"
    body = "".join(_tlv(t, v) for t, v in [
        ("00", "01"), ("01", "11"),
        ("26", "0015ID.CO.QRIS.WWW0216936009147048108021"),
        ("52", "4511"), ("53", "360"), ("58", "ID"),
        ("59", "KOPI KENANGAN H8"), ("60", "JAKARTA"), ("62", "0502OK"),
    ]) + "6304"
    static = body + crc16(body)

    dyn = convert(static, 15750, {"type": "fixed", "value": 500})
    d = dict(parse(dyn))
    assert dyn.startswith("000201") and d["01"] == "12"
    assert d["53"] == "360" and d["54"] == "15750"
    assert d["55"] == "02" and d["56"] == "500"
    assert d["59"] == "KOPI KENANGAN H8"
    assert dyn.index("540515750") < dyn.index("5802ID")

    d2 = dict(parse(convert(static, 100000, {"type": "percent", "value": 2.5})))
    assert d2["54"] == "100000" and d2["55"] == "03" and d2["57"] == "2.5"
    d3 = dict(parse(convert(static, "999", None)))
    assert d3["54"] == "999" and "55" not in d3

    for bad_call in (lambda: convert(static[:-4] + "FFFF", 1000),
                     lambda: convert("12345678901234567890", 1000),
                     lambda: convert(static, -5),
                     lambda: convert(static, 1000, {"type": "tips", "value": 1})):
        try:
            bad_call()
            raise AssertionError("error input lolos validasi")
        except ValueError:
            pass
    print("SELF-TEST PASS")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _selftest()
    else:
        print(f"qris api on {HOST}:{PORT}")
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
