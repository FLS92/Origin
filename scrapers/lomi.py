"""One-off scraper for lomi.cafe. Its storefront is a Next.js app whose pages
are server-side rendered with the full page data embedded in a
'__NEXT_DATA__' JSON script tag — including a Swell/schema.io commerce
backend's product objects, nested under category -> subcategories -> products.
No public REST API is exposed, so this is the only non-fragile way in: read
the same JSON payload the page itself hydrates from, no JS execution needed.
"""
import json
import re

from .common.http import session, get
from .common.parsing import parse_grams
from .common.schema import RawProduct, apply_products, save

CATEGORY_URL = "https://lomi.cafe/categories/cafes"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

NON_WEIGHT_HINTS = ("capsule", "pod", "dosette")


def _collect_products(category):
    products = list(category.get("products") or [])
    for sub in category.get("subcategories") or []:
        products.extend(_collect_products(sub))
    return products


def _smallest_weight_g(contenant_values):
    grams = []
    for v in contenant_values or []:
        if any(h in v.lower() for h in NON_WEIGHT_HINTS):
            continue
        g = parse_grams(v)
        if g:
            grams.append(g)
    return min(grams) if grams else None


def to_raw_product(p, site_name):
    variants = (p.get("variants") or {}).get("results") or []
    prices = [v["price"] for v in variants if v.get("price") is not None]
    price = min(prices) if prices else p.get("price")
    price_note = "à partir de" if len(prices) > 1 else None

    contenant = (p.get("attributes") or {}).get("contenant", {}).get("value")
    weight_g = _smallest_weight_g(contenant)

    images = p.get("images") or []
    image_url = None
    if images:
        f = images[0].get("file", {})
        image_url = f.get("url")

    retailer = {
        "site": site_name,
        "url": f"https://lomi.cafe/products/{p['slug']}",
        "price": price,
        "currency": p.get("currency", "EUR"),
        "unitWeightG": weight_g,
        "priceNote": price_note,
        "inStock": p.get("stockStatus") != "out_of_stock",
        "stockStatus": "instock" if p.get("stockStatus") != "out_of_stock" else "outofstock",
    }
    content = p.get("content") or {}
    extracted = {
        "process": content.get("processing"),
        "flavors": [n.strip() for n in (content.get("aromaticNotes") or "").split("•") if n.strip()] or None,
    }
    extracted = {k: v for k, v in extracted.items() if v}
    return RawProduct(
        slug=p["slug"],
        name=p.get("name") or (p.get("content") or {}).get("subtitle") or p["slug"],
        retailers=[retailer],
        raw_description_html=p.get("description"),
        image_url=image_url,
        extracted=extracted,
    )


def scrape(roaster_meta):
    s = session()
    resp = get(s, CATEGORY_URL)
    resp.raise_for_status()
    m = NEXT_DATA_RE.search(resp.text)
    if not m:
        raise RuntimeError("lomi.cafe: __NEXT_DATA__ block not found — page structure may have changed")
    data = json.loads(m.group(1))
    category = data["props"]["pageProps"]["category"]
    products = _collect_products(category)

    raw_products = [to_raw_product(p, roaster_meta["name"]) for p in products]
    data_out, summary = apply_products(roaster_meta, raw_products)
    save(roaster_meta["id"], data_out)
    return summary
