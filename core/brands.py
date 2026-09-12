"""Brand registry - daftar brand dan kode transaksi yang valid."""

# Daftar kode brand yang valid (bisa ditambah nanti)
BRAND_CODES = {
    "GDC",   # GANDACUAN
    "PKC",   # POKECUAN88
    "EMO",   # EMO78
    "BYT",   # BUAYATOTO
    "OMC",   # OMACUAN
    "MWC",   # MAWARCUAN
    "WPS",   # WOPSLOT
    "AKC",   # AKONGCUAN
    "NGS",   # NAGASPIN99
    "GPS",   # GOPAYSLOT77
    "LKU",   # LIKU88
    "BTS",   # BETSPIN88
    "SEO",   # SEOCUAN
    "JKS",   # JOKISPIN
    "TWS",   # TWINSLOT77
}

# Prefix transaksi yang valid
TXN_PREFIXES = {"DP", "WD", "ST"}


def is_valid_order_id(text: str) -> bool:
    """
    Cek apakah text adalah Order ID yang valid.
    Format: DP/WX/ST + KODE_BRAND + ANGKA
    Minimal panjang: 5 karakter (2 prefix + 3 brand)
    """
    if not text or len(text) < 5:
        return False

    # Ambil 2 huruf pertama (prefix)
    prefix = text[:2].upper()
    if prefix not in TXN_PREFIXES:
        return False

    # Ambil 3 huruf berikutnya (kode brand)
    brand_code = text[2:5].upper()
    if brand_code not in BRAND_CODES:
        return False

    # Sisanya harus mengandung angka
    remaining = text[5:]
    if not remaining or not any(c.isdigit() for c in remaining):
        return False

    return True


def extract_valid_order_ids(text: str) -> list[str]:
    """
    Extract SEMUA Order ID valid dari text.
    Hanya yang cocok dengan daftar brand terdaftar.
    """
    if not text:
        return []

    import re
    tokens = re.findall(r"[A-Za-z0-9-]+", text)

    valid_ids = []
    for token in tokens:
        if is_valid_order_id(token):
            valid_ids.append(token)

    return valid_ids


def get_category_from_prefix(prefix: str) -> str:
    """Dapatkan kategori dari 2 huruf prefix."""
    categories = {
        "DP": "DEPOSIT",
        "WD": "WITHDRAW",
        "ST": "SETTLEMENT",
    }
    return categories.get(prefix.upper(), "UNKNOWN")


def get_brand_name(code: str) -> str:
    """Dapatkan nama brand dari kode (opsional, untuk display)."""
    brand_map = {
        "GDC": "GANDACUAN",
        "PKC": "POKECUAN88",
        "EMO": "EMO78",
        "BYT": "BUAYATOTO",
        "OMC": "OMACUAN",
        "MWC": "MAWARCUAN",
        "WPS": "WOPSLOT",
        "AKC": "AKONGCUAN",
        "NGS": "NAGASPIN99",
        "GPS": "GOPAYSLOT77",
        "LKU": "LIKU88",
        "BTS": "BETSPIN88",
        "SEO": "SEOCUAN",
        "JKS": "JOKISPIN",
        "TWS": "TWINSLOT77",
    }
    return brand_map.get(code.upper(), code)
