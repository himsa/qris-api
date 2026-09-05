# qris-dynamic

QRIS static → dynamic converter: **package Python** (library) + **HTTP API server**. Murni stdlib, 0 dependency, Python ≥3.9. Distribusi gratis; API key opsional, **default OFF**.

Dokumen integrasi lengkap (kontrak API, contoh JS/Python, deploy, troubleshooting): [HANDOFF.md](HANDOFF.md)

## Cara kerja

Parse TLV EMVCo → buang tag `54/55/56/57/63` → tag `01` jadi `12` (dynamic) → sisip `53` (bila absen) + `54` nominal + fee opsional `55/56` (fixed) atau `55/57` (persen) sebelum `58` → CRC16-CCITT-FALSE baru.

> Modifikasi string lokal, bukan dynamic QRIS sesungguhnya (tanpa NMID dinamis / callback acquirer). Nominal pre-fill diterima atau tidak tergantung app pembayaran.

## Install

```bash
pip install "qris-dynamic @ git+https://github.com/himsa/qris-api.git"
```

Repo saat ini private — yang punya akses (diundang) bisa install langsung. Bisa dibuka publik / ke PyPI nanti.

## Sebagai library di project

```python
from qris import convert

payload = convert(qr_string, amount=15750, fee={"type": "fixed", "value": 500})
# "000201010212...6304XXXX"

from qris import parse
parse(qr_string)  # [(tag, value), ...], CRC tervalidasi
```

Jalanin self-check: `python -m qris`

## Sebagai API server

```bash
python -m qris.server            # atau: qris-server (entry point)
# env: QRIS_HOST (default 127.0.0.1), QRIS_PORT (8000)
```

Default **tanpa API key** — semua request lolos tanpa header. Aktifkan hanya kalau butuh.

### API key (opsional, default OFF)

```bash
python -m qris.server --gen-key
# API key  : qris_<48 hex>   <- berikan ke customer, simpan sekali
# sha256   : <64 hex>        <- taruh di env server, BUKAN key mentahnya

QRIS_API_KEYS=hash1,hash2 QRIS_RATE_LIMIT=60 python -m qris.server
```

- Client: header `X-API-Key: qris_...` (atau `Authorization: Bearer qris_...`)
- Key hilang/salah → `401`; lewat `QRIS_RATE_LIMIT`/menit per key → `429`
- Server hanya simpan **hash**; verifikasi `hmac.compare_digest`; key mentah tidak pernah di-log
- Revoke = hapus hash dari env. Rotasi = gen key baru + hapus lama
- Produksi wajib HTTPS di depan (nginx / Cloudflare)

### Endpoint

```bash
curl -X POST http://127.0.0.1:8000/convert \
  -H 'Content-Type: application/json' -H 'X-API-Key: qris_...' \
  -d '{"qr":"000201...","amount":15750,"fee":{"type":"fixed","value":500}}'
# {"ok":true,"data":{"payload":"000201010212..."}}

curl -X POST http://127.0.0.1:8000/parse -H 'X-API-Key: qris_...' \
  -H 'Content-Type: application/json' -d '{"qr":"000201..."}'
```

CORS terbuka — render QR di client (mis. qrcode.js). Error balik 400 + `{"ok":false,"error":"..."}`.

## Status & catatan

- Gratis, belum di-host. Infra API key + rate limit sudah siap tapi default OFF — tinggal isi `QRIS_API_KEYS` kalau nanti butuh.
- Kalau suatu saat mau jual akses: hosted API, rate limit per key = tier harga, billing via RapidAPI/API gateway (jangan dibikin sendiri).
