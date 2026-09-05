"""Inti konversi QRIS static->dynamic. Murni stdlib, tanpa dependency.

convert(qr, amount, fee) -> payload dinamis baru (string)
parse(qr) -> [(tag, value), ...] top-level, CRC tervalidasi
crc16(s) -> CRC-16/CCITT-FALSE (init 0xFFFF, poly 0x1021), hex uppercase
generate_api_key() -> (key, sha256hex) untuk server/API access
"""
import hashlib
import secrets

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


def generate_api_key():
    """Return (key, sha256hex). Key mentah hanya tampil sekali ke operator;
    yang disimpan/dipakai di server hanya hash-nya."""
    key = "qris_" + secrets.token_hex(24)
    return key, hashlib.sha256(key.encode("utf-8")).hexdigest()


def selftest():
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

    key, h = generate_api_key()
    assert key.startswith("qris_") and len(h) == 64
    print("SELF-TEST PASS")
