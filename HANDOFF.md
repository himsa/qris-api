# HANDOFF — qris-dynamic

Dokumen integrasi untuk developer. Package = library Python + HTTP API server. Stdlib only, 0 dependency, Python ≥3.9.

## 1. Apa yang dilakukan & batasannya

- Input: string QRIS statis (mulai `000201`). Output: string QRIS dengan nominal (`54`) + fee opsional (`55/56` fixed atau `55/57` persen) + tag `01` = `12` + CRC16-CCITT-FALSE baru.
- **Bukan** dynamic QRIS sejati: tanpa NMID dinamis, tanpa callback acquirer, tanpa tracking. Nominal pre-fill diterima atau tidak tergantung app pembayaran (umumnya diterima antar app QRIS).
- Server stateless: tidak simpan/log data apa pun.
- Input wajib: mulai `000201`, CRC valid, printable ASCII, panjang ≥20. Selain itu → `ValueError` / HTTP 400 dengan pesan penyebab.

## 2. Install

```bash
pip install "qris-dynamic @ git+https://github.com/himsa/qris-api.git"
```

Dev lokal: `git clone` → `cd qris-api` → `pip install -e .`
Verifikasi: `python -m qris` → harus cetak `SELF-TEST PASS`.

## 3. Library (dipakai di project)

```python
from qris import convert, parse

payload = convert(qr_string, 15750)                                # tanpa fee
payload = convert(qr_string, 15750, {"type": "fixed", "value": 500})   # fee tetap
payload = convert(qr_string, 15750, {"type": "percent", "value": 2.5}) # fee persen

tags = parse(qr_string)   # [(tag, value), ...], CRC tervalidasi
```

Semua input invalid melempar `ValueError` dengan pesan jelas (CRC mismatch, bukan QRIS, amount salah, dll). Tangkap di caller.

## 4. Server

```bash
python -m qris.server        # atau: qris-server
```

Environment:

| Env | Default | Keterangan |
|---|---|---|
| `QRIS_HOST` | `127.0.0.1` | bind address |
| `QRIS_PORT` | `8000` | port |
| `QRIS_API_KEYS` | *(kosong)* | sha256 hash key, dipisah koma. Kosong = tanpa auth (khusus dev lokal) |
| `QRIS_RATE_LIMIT` | `60` | max permintaan per menit per key/IP |

API key (opsional):

```bash
python -m qris.server --gen-key   # -> key utk customer + sha256 utk env server
```

Server hanya menyimpan **hash**, bukan key mentah. Revoke = hapus hash dari env.

## 5. Kontrak API

| Endpoint | Method | Keterangan |
|---|---|---|
| `/health` | GET | status + info auth/rate |
| `/convert` | POST | `{"qr": "...", "amount": 15750, "fee": {...}}` → `{"ok":true,"data":{"payload":"..."}}` |
| `/parse` | POST | `{"qr": "..."}` → `{"ok":true,"data":{"tags":[{"tag","name","value"}]}}` |

Header: `Content-Type: application/json` + (jika auth aktif) `X-API-Key: qris_...`.

Status code:

| Kode | Arti |
|---|---|
| 200 | sukses |
| 400 | input invalid — baca `error` (pesan spesifik) |
| 401 | API key hilang/salah |
| 404 | path salah |
| 413 | body > 8KB |
| 429 | lewat rate limit |

CORS terbuka (`*`) — bisa dipanggil langsung dari browser.

## 6. Contoh integrasi web (JS)

```js
const res = await fetch("https://api.contoh.com/convert", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": "qris_...",            // hapus jika auth OFF
  },
  body: JSON.stringify({
    qr: staticQrString,                 // hasil decode QR statis (mis. html5-qrcode)
    amount: 15750,
    fee: { type: "fixed", value: 500 }, // opsional
  }),
});
const body = await res.json();
if (!res.ok) throw new Error(body.error);
renderQr(body.data.payload);            // render pakai qrcode.js / qr-code-styling
```

Catatan: server balik **string** — render QR image di sisi client.

## 7. Contoh client Python

```python
import requests

r = requests.post("http://host:8000/convert",
                  json={"qr": qr_string, "amount": 15750},
                  headers={"X-API-Key": "qris_..."}, timeout=10)
r.raise_for_status()
payload = r.json()["data"]["payload"]
```

## 8. Ops — checklist deploy

- Jangan expose server polos ke internet. Taruh di belakang reverse proxy TLS (nginx/Cloudflare/Caddy).
- Contoh systemd (`/etc/systemd/system/qris.service`):

```ini
[Unit]
Description=qris-dynamic API
After=network.target

[Service]
User=qris
ExecStart=/usr/bin/python3 -m qris.server
Environment=QRIS_API_KEYS=<sha256-hash>
Environment=QRIS_RATE_LIMIT=60
Environment=QRIS_PORT=8000
Restart=always

[Install]
WantedBy=multi-user.target
```

- nginx: `location / { proxy_pass http://127.0.0.1:8000; }` + sertifikat TLS (mis. certbot).
- Health check monitoring: `GET /health` tiap menit.

## 9. Troubleshooting

- `CRC mismatch` → string terpotong/ada spasa/salah copy. Decode ulang QR asli.
- `bukan QRIS: payload harus mulai '000201'` → QR itu bukan QRIS (mis. QR GoPay personal berupa URL).
- Nominal tidak muncul saat scan → app pembayaran mengabaikan tag `54` atau merchant tidak lolos validasi; coba app pembayaran lain sebelum lapor bug.
- `429` → kena rate limit; naikkan `QRIS_RATE_LIMIT` atau cache hasil convert.
- Self-test gagal setelah modifikasi → `python -m qris` untuk reproduksi sebelum push.
