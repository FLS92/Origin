import re
import unicodedata

WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", re.IGNORECASE)
PRICE_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€")


def norm(text):
    n = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", n.lower()).strip()


def parse_grams(text):
    m = WEIGHT_RE.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return int(round(value * 1000 if unit == "kg" else value))


def parse_price_eur(text):
    m = PRICE_RE.search((text or "").replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(1).replace(",", "."))
