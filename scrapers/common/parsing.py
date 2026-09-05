import re
import unicodedata

WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", re.IGNORECASE)
PRICE_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€")


def norm(text):
    n = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-z0-9 ]", " ", n.lower())
    return re.sub(r"\s+", " ", n).strip()


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


def normalize_method(value):
    """Maps free text explicitly naming a brewing method to the schema's one
    of "Filtre"/"Espresso"/"Omni" — used wherever a platform's own field
    (WooCommerce/PrestaShop attribute, Shopify product_type or variant
    option) or a description sentence states this explicitly. Both words
    present (or "omni" itself) means the roaster sells/roasts it for either,
    i.e. Omni. Returns None rather than guessing when neither word is found."""
    v = norm(value)
    has_espresso = "espresso" in v or "expresso" in v
    has_filtre = "filtre" in v
    if "omni" in v or (has_espresso and has_filtre):
        return "Omni"
    if has_espresso:
        return "Espresso"
    if has_filtre:
        return "Filtre"
    return None
