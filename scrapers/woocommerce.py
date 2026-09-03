"""Scraper for WooCommerce stores via the public Store API
(/wp-json/wc/store/v1/products) — no auth needed, this is the same API
the store's own cart/checkout UI uses.

Some WooCommerce stores expose rich custom product attributes (Producteur,
Variété, Process, Score, Torréfaction...). When an attribute's label matches
a known synonym we fill the matching schema field; anything else is left
null rather than guessed, per the schema's own instructions not to
precompute categorization.
"""
import html
import json as json_module
import re
import time
import unicodedata

from .common.http import session, get, decode_json_body
from .common.schema import RawProduct, apply_products, save

ATTR_SYNONYMS = {
    "producer": {"producteur", "producteurs", "productrice", "ferme", "cooperative", "cooperatives"},
    "variety": {"variete", "varietes", "cultivar"},
    "process": {"process", "procede", "traitement"},
    "origin_country": {"origine", "pays", "pays d origine"},
    "score": {"score", "score sca", "note sca"},
    "method": {"torrefaction", "methode", "extraction"},
    "weight": {"poids", "format", "conditionnement", "contenance", "grammage"},
}

WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", re.IGNORECASE)

COFFEE_CATEGORY_ALLOW = {
    "cafes", "cafe", "coffee", "nos-cafes", "cafes-de-specialite",
    "cafe-en-grain", "cafes-en-grain", "grains-de-cafe", "nos-cafes-de-specialite",
    "cafes-specialty", "origines", "single-origin", "single-origins",
}

# Used only as a broader second pass, and only for products already excluded
# by the exact allowlist above — a category slug/name containing one of these
# tokens is almost always tea, equipment or an accessory, not coffee beans,
# even though some also contain "cafe" as a substring (e.g. "filtres-a-cafe").
NON_COFFEE_TOKENS = {
    "machine", "moulin", "grinder", "tasse", "carafe", "balance", "tamper",
    "dripper", "accessoire", "entretien", "cafetiere", "hario", "jura",
    "commandante", "filtre", "the", "infusion", "chocolat", "capsule",
}


def _category_tokens(p):
    tokens = set()
    for c in p.get("categories") or []:
        tokens.add(_norm(c.get("slug", "")).replace(" ", "-"))
        tokens.add(_norm(c.get("name", "")))
    return tokens


def _is_coffee_exact(p):
    return bool(_category_tokens(p) & COFFEE_CATEGORY_ALLOW)


def _is_coffee_loose(p):
    for cat in p.get("categories") or []:
        words = _norm(cat.get("name", "")).split() + _norm(cat.get("slug", "").replace("-", " ")).split()
        if any(w in NON_COFFEE_TOKENS for w in words):
            continue
        if any(w.startswith("cafe") or w == "coffee" for w in words):
            return True
    return False


def filter_coffee_products(products):
    """Two passes, each stricter than falling back to 'everything': an exact
    allowlist match first, then a looser substring match (excluding known
    non-coffee categories) if that finds nothing at all. Only if neither pass
    finds a single coffee product do we give up and keep everything — better
    than silently dropping a whole catalog because its taxonomy doesn't match
    ours, but a real fallback of last resort, not the common case."""
    exact = [p for p in products if _is_coffee_exact(p)]
    if exact:
        return exact, False
    loose = [p for p in products if _is_coffee_loose(p)]
    if loose:
        return loose, False
    return products, True


def _norm(label):
    n = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", n.lower()).strip()


def _match_field(label):
    n = _norm(label)
    for field, synonyms in ATTR_SYNONYMS.items():
        if n in synonyms:
            return field
    return None


def _parse_grams(text):
    m = WEIGHT_RE.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    grams = value * 1000 if unit == "kg" else value
    return int(round(grams))


def _extract_attributes(attributes):
    out = {}
    for attr in attributes or []:
        field = _match_field(attr.get("name", ""))
        if not field:
            continue
        terms = attr.get("terms") or []
        if not terms:
            continue
        if field == "weight":
            default_term = next((t for t in terms if t.get("default")), terms[0])
            out["weight_g"] = _parse_grams(default_term.get("name", ""))
        elif field == "score":
            names = [t["name"] for t in terms]
            try:
                val = float(names[0].replace(",", "."))
                out["score"] = int(val) if val.is_integer() else val
            except ValueError:
                out["score"] = names[0]
        else:
            names = [t["name"] for t in terms]
            out[field] = ", ".join(names) if len(names) > 1 else names[0]
    return out


def fetch_all_products(domain):
    s = session()
    products = []
    page = 1
    while True:
        url = f"https://{domain}/wp-json/wc/store/v1/products?per_page=100&page={page}"
        resp = get(s, url)
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        try:
            batch = decode_json_body(resp)
        except json_module.JSONDecodeError:
            time.sleep(2)
            resp = get(s, url)
            resp.raise_for_status()
            batch = decode_json_body(resp)
        if not batch:
            break
        products.extend(batch)
        page += 1
        if page > 50:
            break
    return products


def to_raw_product(p, site_name):
    prices = p.get("prices") or {}
    minor_unit = prices.get("currency_minor_unit", 2)
    divisor = 10 ** minor_unit
    price_raw = prices.get("price")
    price = float(price_raw) / divisor if price_raw not in (None, "") else None

    price_range = prices.get("price_range") or {}
    is_range = p.get("type") == "variable" and price_range.get("min_amount") != price_range.get("max_amount")

    attrs = _extract_attributes(p.get("attributes"))
    images = p.get("images") or []
    image_url = images[0]["src"] if images else None
    available = p.get("is_in_stock", True)

    retailer = {
        "site": site_name,
        "url": p.get("permalink", ""),
        "price": price,
        "currency": prices.get("currency_code", "EUR"),
        "unitWeightG": attrs.get("weight_g"),
        "priceNote": "à partir de" if is_range else None,
        "inStock": bool(available),
        "stockStatus": "instock" if available else "outofstock",
    }
    slug = p.get("slug") or p.get("permalink", "").rstrip("/").rsplit("/", 1)[-1] or f"id-{p['id']}"
    raw = RawProduct(
        slug=slug,
        name=html.unescape(p["name"]),
        retailers=[retailer],
        raw_description_html=p.get("short_description") or p.get("description"),
        image_url=image_url,
    )
    raw.extracted = {k: v for k, v in attrs.items() if k != "weight_g"}
    return raw


def scrape(roaster_meta):
    domain = roaster_meta["domain"]
    products = fetch_all_products(domain)
    coffee_products, filter_fallback = filter_coffee_products(products)
    raw_products = [to_raw_product(p, roaster_meta["name"]) for p in coffee_products]
    data, summary = apply_products(roaster_meta, raw_products)
    if filter_fallback:
        summary["warning"] = (
            "aucune catégorie café reconnue — tous les produits du catalogue ont été "
            "gardés (thés/machines/accessoires possiblement inclus)"
        )

    # Backfill structured fields extracted from WooCommerce attributes, for
    # newly-created product entries only (apply_products doesn't know about
    # this platform-specific extraction step).
    by_slug = {rp.slug: rp for rp in raw_products}
    for prod in data["products"]:
        slug = prod["id"][len(roaster_meta["id"]) + 1:]
        rp = by_slug.get(slug)
        if not rp or not getattr(rp, "extracted", None):
            continue
        for field, value in rp.extracted.items():
            key = {"origin_country": "originCountry"}.get(field, field)
            if prod.get(key) is None:
                prod[key] = value

    save(roaster_meta["id"], data)
    return summary
