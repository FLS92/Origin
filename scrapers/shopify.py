"""Scraper for Shopify storefronts, using the public /products.json endpoint
(no auth needed — this is the standard storefront product feed every Shopify
store exposes)."""
import json as json_module
import re
import time
import unicodedata

from .common.http import session, get, decode_json_body
from .common.schema import RawProduct, apply_products, save

COFFEE_TYPE_ALLOW = {"cafe", "coffee", "cafes", "grain", "grains", "origine", "origines", "single origin"}


def _norm(text):
    n = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", n.lower()).strip()


def filter_coffee_products(products):
    coffee = [p for p in products if _norm(p.get("product_type", "")) in COFFEE_TYPE_ALLOW]
    return coffee if coffee else products


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
    return RawProduct(
        slug=p["handle"],
        name=p["title"],
        retailers=[retailer],
        raw_description_html=p.get("body_html"),
        image_url=image_url,
    )


def scrape(roaster_meta):
    domain = roaster_meta["domain"]
    products = fetch_all_products(domain)
    products = filter_coffee_products(products)
    site_name = roaster_meta["name"]
    raw_products = []
    for p in products:
        p["_shop_display_name"] = site_name
        p["_product_url"] = f"https://{domain}/products/{p['handle']}"
        p["_currency"] = "EUR"
        raw_products.append(to_raw_product(p))
    data, summary = apply_products(roaster_meta, raw_products)
    save(roaster_meta["id"], data)
    return summary
