# qris-api

QRIS static → dynamic converter + HTTP API. Python stdlib murni, 0 dependency.

## Cara kerja

Sama seperti converter client-side pada umumnya: parse TLV EMVCo → buang tag `54/55/56/57/63` → tag `01` jadi `12` (dynamic) → sisip `53` (bila absen) + `54` nominal + fee opsional `55/56` (fixed) atau `55/57` (persen) sebelum `58` → hitung ulang CRC16-CCITT-FALSE.

> Catatan: modifikasi string lokal, bukan dynamic QRIS sesungguhnya (tidak ada NMID dinamis / callback acquirer). Penerimaan nominal pre-fill tergantung app pembayaran.

## Jalankan

```bash
python3 qris_api.py          # serve 127.0.0.1:8000 (env: HOST, PORT)
python3 qris_api.py --test   # self-check
```

## API

`POST /convert`

```bash
curl -X POST http://127.0.0.1:8000/convert -H 'Content-Type: application/json' \
  -d '{"qr":"000201...","amount":15750,"fee":{"type":"fixed","value":500}}'
# {"ok":true,"data":{"payload":"000201010212...6304XXXX"}}
```

`fee` opsional: `{"type":"fixed","value":500}` atau `{"type":"percent","value":2.5}`

`POST /parse` — `{"qr":"000201..."}` → breakdown semua tag.

CORS terbuka (`*`) — siap dipanggil dari web client; render QR di client (mis. qrcode.js).

Error balik HTTP 400 + `{"ok":false,"error":"..."}` (CRC mismatch, bukan QRIS, dst).
