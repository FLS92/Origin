"""Scraper for Shopify storefronts, using the public /products.json endpoint
(no auth needed — this is the standard storefront product feed every Shopify
store exposes)."""
import json as json_module
import re
import time
import unicodedata

from .common.http import session, get, decode_json_body
from .common.parsing import normalize_method
from .common.schema import RawProduct, apply_products, save

COFFEE_TYPE_ALLOW = {"cafe", "coffee", "cafes", "grain", "grains", "origine", "origines", "single origin"}
NON_COFFEE_TOKENS = {
    "machine", "moulin", "grinder", "tasse", "carafe", "balance", "tamper",
    "dripper", "accessoire", "entretien", "cafetiere", "the", "infusion",
    "chocolat", "capsule", "livre", "carte", "textile", "formation",
}


def _norm(text):
    n = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", n.lower()).strip()


def _is_coffee_loose(product_type):
    words = product_type.split()
    if any(w in NON_COFFEE_TOKENS for w in words):
        return False
    return any(w.startswith("cafe") or w == "coffee" for w in words)


def filter_coffee_products(products):
    """Two passes on product_type before giving up on that field — see
    woocommerce.filter_coffee_products for why an unconditional fallback to
    'everything' is the wrong default. A third pass (fetch_coffee_collection)
    covers the common case this can't: product_type left blank storewide."""
    exact = [p for p in products if _norm(p.get("product_type", "")) in COFFEE_TYPE_ALLOW]
    if exact:
        return exact, False
    loose = [p for p in products if _is_coffee_loose(_norm(p.get("product_type", "")))]
    if loose:
        return loose, False
    return products, True


COFFEE_COLLECTION_ALLOW = {
    "cafes", "cafe", "coffee", "nos-cafes", "tous-nos-cafes", "cafe-de-specialite",
    "cafes-de-specialite", "cafe-en-grain", "cafes-en-grain", "grains-de-cafe",
    "nos-cafes-de-specialite", "origines",
}


def _collection_is_coffee(handle, title):
    h = _norm(handle).replace(" ", "-")
    if h in COFFEE_COLLECTION_ALLOW:
        return True
    words = _norm(title).split() + _norm(handle.replace("-", " ")).split()
    if any(w in NON_COFFEE_TOKENS for w in words):
        return False
    return any(w.startswith("cafe") or w == "coffee" for w in words)


def fetch_coffee_collection_products(domain):
    """Used when product_type is unreliable (often blank storewide) — finds a
    collection that looks like the coffee-beans one and fetches just that,
    rather than falling back to the whole undifferentiated catalog."""
    s = session()
    resp = get(s, f"https://{domain}/collections.json?limit=250")
    if resp.status_code != 200:
        return []
    try:
        collections = decode_json_body(resp).get("collections", [])
    except json_module.JSONDecodeError:
        return []

    handles = [c["handle"] for c in collections if _collection_is_coffee(c["handle"], c.get("title", ""))]
    seen_ids = set()
    products = []
    for handle in handles:
        page = 1
        while True:
            url = f"https://{domain}/collections/{handle}/products.json?limit=250&page={page}"
            resp = get(s, url)
            if resp.status_code != 200:
                break
            try:
                batch = decode_json_body(resp).get("products", [])
            except json_module.JSONDecodeError:
                break
            if not batch:
                break
            for p in batch:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    products.append(p)
            page += 1
            if page > 20:
                break
    return products


def fetch_all_products(domain):
    s = session()
    products = []
    page = 1
    while True:
        url = f"https://{domain}/products.json?limit=250&page={page}"
        resp = get(s, url)
        resp.raise_for_status()
        try:
            batch = decode_json_body(resp).get("products", [])
        except json_module.JSONDecodeError:
            time.sleep(2)
            resp = get(s, url)
            resp.raise_for_status()
            batch = decode_json_body(resp).get("products", [])
        if not batch:
            break
        products.extend(batch)
        page += 1
        if page > 50:  # sanity cap
            break
    return products


def _extract_method(p, variants):
    """Two Shopify-native signals, checked before ever touching free text:
    the shop's own product_type ("Café Filtre") is the roaster's explicit
    categorization already used for the coffee/not-coffee filter above, and
    a variant option ("Filtre" / "Espresso" as a grind choice) is equally
    explicit. If different variants of the same product carry both, the
    roaster sells/roasts it for either -- that's Omni, not a guess."""
    method = normalize_method(p.get("product_type", ""))
    if method:
        return method

    found = set()
    for v in variants:
        for key in ("option1", "option2", "option3"):
            m = normalize_method(v.get(key) or "")
            if m:
                found.add(m)
    if "Omni" in found or {"Filtre", "Espresso"} <= found:
        return "Omni"
    if found:
        return next(iter(found))
    return None


def to_raw_product(p):
    variants = p.get("variants") or []
    priced = [v for v in variants if v.get("price") is not None]
    variant = min(priced, key=lambda v: float(v["price"])) if priced else (variants[0] if variants else {})

    price = float(variant["price"]) if variant.get("price") is not None else None
    grams = variant.get("grams") or None
    available = bool(variant.get("available", True))
    images = p.get("images") or []
    image_url = images[0]["src"] if images else None

    retailer = {
        "site": p.get("_shop_display_name", ""),
        "url": p.get("_product_url", ""),
        "price": price,
        "currency": p.get("_currency", "EUR"),
        "unitWeightG": grams,
        "priceNote": "à partir de" if len(priced) > 1 else None,
        "inStock": available,
        "stockStatus": "instock" if available else "outofstock",
    }
    method = _extract_method(p, variants)
    return RawProduct(
        slug=p["handle"],
        name=p["title"],
        retailers=[retailer],
        raw_description_html=p.get("body_html"),
        image_url=image_url,
        extracted={"method": method} if method else None,
    )


def scrape(roaster_meta):
    domain = roaster_meta["domain"]
    products = fetch_all_products(domain)
    products, filter_fallback = filter_coffee_products(products)
    warning = None
    if filter_fallback:
        collection_products = fetch_coffee_collection_products(domain)
        if collection_products:
            products = collection_products
            filter_fallback = False
        else:
            warning = (
                "aucun product_type ni collection café reconnu — tous les produits du "
                "catalogue ont été gardés (thés/machines/accessoires possiblement inclus)"
            )
    site_name = roaster_meta["name"]
    raw_products = []
    for p in products:
        p["_shop_display_name"] = site_name
        p["_product_url"] = f"https://{domain}/products/{p['handle']}"
        p["_currency"] = "EUR"
        raw_products.append(to_raw_product(p))
    data, summary = apply_products(roaster_meta, raw_products)
    if warning:
        summary["warning"] = warning
    save(roaster_meta["id"], data)
    return summary
