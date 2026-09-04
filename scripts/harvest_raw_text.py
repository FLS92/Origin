#!/usr/bin/env python3
"""One-time harvest: re-fetch every product's raw description text (the same
text scrapers already pull, normally fed to the LLM extraction step) and dump
it to a JSONL file for manual review, bypassing the Anthropic API entirely.

Only dumps products whose key fields (score/producer/process/variety/method/
flavors) are ALL still null AND that have non-empty raw text to work with --
no point re-processing what's already filled in, or products with no
description on the site at all.

Usage: python3 scripts/harvest_raw_text.py [roaster_id ...]
Output: scratch/raw_text_dump.jsonl (one {id, roaster, name, url, text} per line)
"""
import json
import os
import sys

sys.path.insert(0, ".")
from scrapers import shopify, woocommerce, prestashop, odoo, squarespace, wizishop, magento, lomi  # noqa: E402
from scrapers.common.paraphrase import strip_html  # noqa: E402

FIELDS_TO_CHECK = ["score", "producer", "process", "variety", "method", "flavors"]
OUT_PATH = "scratch/raw_text_dump.jsonl"


def needs_enrichment(product):
    return all(product.get(f) is None for f in FIELDS_TO_CHECK)


def harvest_shopify(meta):
    products = shopify.fetch_all_products(meta["domain"])
    products, _ = shopify.filter_coffee_products(products)
    out = {}
    for p in products:
        out[p["handle"]] = strip_html(p.get("body_html"))
    return out


def harvest_woocommerce(meta):
    products = woocommerce.fetch_all_products(meta["domain"])
    coffee, _ = woocommerce.filter_coffee_products(products)
    out = {}
    for p in coffee:
        slug = p.get("slug") or p.get("permalink", "").rstrip("/").rsplit("/", 1)[-1] or f"id-{p['id']}"
        out[slug] = strip_html(p.get("short_description") or p.get("description"))
    return out


def harvest_magento(meta):
    # Magento's listing has no description field captured; nothing to harvest.
    return {}


def harvest_lomi(meta):
    from scrapers.common.http import session, get
    s = session()
    resp = get(s, lomi.CATEGORY_URL)
    m = lomi.NEXT_DATA_RE.search(resp.text)
    if not m:
        return {}
    data = json.loads(m.group(1))
    category = data["props"]["pageProps"]["category"]
    products = lomi._collect_products(category)
    return {p["slug"]: strip_html(p.get("description")) for p in products}


def _crawl_category(meta, find_cat_fn):
    """Homepage -> coffee category URL, shared by PrestaShop and Wizishop."""
    from bs4 import BeautifulSoup
    from scrapers.common.http import session, get
    domain = meta["domain"]
    if meta["platform"] == "wizishop" and not domain.startswith("www."):
        domain = f"www.{domain}"
    base_url = f"https://{domain}/"
    s = session()
    resp = get(s, base_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return s, base_url, find_cat_fn(soup, base_url)


def harvest_prestashop(meta):
    from bs4 import BeautifulSoup
    from scrapers.common.http import get
    s, _, cat_url = _crawl_category(meta, prestashop.find_coffee_category_url)
    out = {}
    if not cat_url:
        return out
    url = cat_url
    for _ in range(20):
        resp = get(s, url)
        if resp.status_code != 200:
            break
        page_soup = BeautifulSoup(resp.text, "html.parser")
        for item in prestashop.parse_listing(resp.text, url):
            if not item.get("id"):
                continue
            detail = prestashop.scrape_product_detail(s, item["url"])
            text = strip_html(detail.get("description_html") or item.get("listing_description_html"))
            if text:
                out[f"p{item['id']}"] = text
        nxt = prestashop.find_next_page(page_soup, url)
        if not nxt or nxt == url:
            break
        url = nxt
    return out


def harvest_wizishop(meta):
    from scrapers.common.http import get
    s, _, cat_url = _crawl_category(meta, wizishop.find_coffee_category_url)
    out = {}
    if not cat_url:
        return out
    url = cat_url
    for _ in range(20):
        resp = get(s, url)
        if resp.status_code != 200:
            break
        items, page_soup = wizishop.parse_listing(resp.text, url)
        for item in items:
            if not item.get("name") or not item.get("url"):
                continue
            detail = wizishop.scrape_product_detail(s, item["url"])
            text = strip_html(detail.get("description_html"))
            if text:
                slug = item["url"].rstrip("/").rsplit("/", 1)[-1].replace(".html", "")
                out[slug] = text
        nxt = wizishop.find_next_page(page_soup, url)
        if not nxt or nxt == url:
            break
        url = nxt
    return out


def harvest_odoo(meta):
    from scrapers.common.http import session, get
    domain = meta["domain"]
    base_url = f"https://{domain}/shop"
    s = session()
    out = {}
    url = base_url
    for _ in range(20):
        resp = get(s, url)
        if resp.status_code != 200:
            break
        items, soup = odoo.parse_listing(resp.text, url)
        for item in items:
            if not item.get("id"):
                continue
            weight, desc_html = odoo.scrape_product_weight(s, item["url"])
            text = strip_html(desc_html)
            if text:
                out[f"p{item['id']}"] = text
        nxt = odoo.has_next_page(soup, 1, f"https://{domain}")
        if not nxt:
            break
        url = nxt
    return out


def harvest_squarespace(meta):
    items = squarespace.fetch_items(meta["url"])
    return {it.get("urlId", it.get("id")): strip_html(it.get("body") or it.get("excerpt")) for it in items}


DISPATCH = {
    "shopify": harvest_shopify,
    "woocommerce": harvest_woocommerce,
    "magento": harvest_magento,
    "custom-swell": harvest_lomi,
    "prestashop": harvest_prestashop,
    "wizishop": harvest_wizishop,
    "odoo": harvest_odoo,
    "squarespace": harvest_squarespace,
}


def main():
    only_ids = set(sys.argv[1:]) or None
    with open("config/roasters.json", encoding="utf-8") as f:
        roasters = {r["id"]: r for r in json.load(f)}

    os.makedirs("scratch", exist_ok=True)
    written = 0
    skipped_no_text = 0
    with open(OUT_PATH, "w", encoding="utf-8") as out_f:
        for fname in sorted(os.listdir("data")):
            if not fname.endswith(".json"):
                continue
            roaster_id = fname[:-5]
            if only_ids and roaster_id not in only_ids:
                continue
            meta = roasters.get(roaster_id)
            if not meta or meta["platform"] not in DISPATCH:
                continue

            with open(os.path.join("data", fname), encoding="utf-8") as f:
                d = json.load(f)

            candidates = [p for p in d["products"] if p.get("available", True) and needs_enrichment(p)]
            if not candidates:
                continue

            try:
                text_by_slug = DISPATCH[meta["platform"]](meta)
            except Exception as exc:
                print(f"{meta['name']}: harvest failed ({exc})", file=sys.stderr)
                continue

            n_this_roaster = 0
            for p in candidates:
                slug = p["id"][len(roaster_id) + 1:]
                text = text_by_slug.get(slug)
                if not text or len(text) < 15:
                    skipped_no_text += 1
                    continue
                out_f.write(json.dumps({
                    "id": p["id"], "roaster": d["roaster"]["name"], "name": p["name"],
                    "url": p["retailers"][0]["url"] if p.get("retailers") else None,
                    "text": text,
                }, ensure_ascii=False) + "\n")
                written += 1
                n_this_roaster += 1
            print(f"{meta['name']}: {n_this_roaster} dumped")

    print(f"\n{written} produits écrits dans {OUT_PATH} ({skipped_no_text} sans texte exploitable)")


if __name__ == "__main__":
    main()
