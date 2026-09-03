"""Scraper for Squarespace Commerce, using the documented '?format=json' trick
on a shop/collection page — no auth needed, Squarespace serves the same data
that hydrates the page's own JS."""
import re

from .common.http import session, get
from .common.schema import RawProduct, apply_products, save

WEIGHT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", re.IGNORECASE)


def _parse_grams(text):
    m = WEIGHT_RE.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return int(round(value * 1000 if unit == "kg" else value))


def fetch_items(shop_url):
    s = session()
    sep = "&" if "?" in shop_url else "?"
    resp = get(s, f"{shop_url}{sep}format=json")
    resp.raise_for_status()
    return resp.json().get("items", [])


def to_raw_product(item, base_url, site_name):
    variants = item.get("variants") or []
    priced = [v for v in variants if v.get("price")]
    variant = min(priced, key=lambda v: v["price"]) if priced else (variants[0] if variants else {})

    price = (variant.get("price") or 0) / 100 if variant.get("price") else None
    weight_g = None
    for opt in variant.get("optionValues") or variant.get("attributes", {}).values():
        label = opt.get("value") if isinstance(opt, dict) else str(opt)
        weight_g = _parse_grams(label)
        if weight_g:
            break

    url = f"{base_url.rstrip('/')}/{item.get('urlId', '')}"
    assets = item.get("items") or item.get("assetUrl")
    image_url = item.get("assetUrl") or None
    available = not variant.get("unlimited") and variant.get("qtyInStock", 1) != 0 if variant else True

    retailer = {
        "site": site_name,
        "url": url,
        "price": price,
        "currency": "EUR",
        "unitWeightG": weight_g,
        "priceNote": "à partir de" if len(priced) > 1 else None,
        "inStock": bool(available),
        "stockStatus": "instock" if available else "outofstock",
    }
    return RawProduct(
        slug=item.get("urlId", item.get("id")),
        name=item.get("title", ""),
        retailers=[retailer],
        raw_description_html=item.get("body") or item.get("excerpt"),
        image_url=image_url,
    )


def scrape(roaster_meta):
    shop_url = roaster_meta["url"]
    items = fetch_items(shop_url)
    raw_products = [to_raw_product(it, roaster_meta["url"], roaster_meta["name"]) for it in items]
    data, summary = apply_products(roaster_meta, raw_products)
    save(roaster_meta["id"], data)
    return summary
