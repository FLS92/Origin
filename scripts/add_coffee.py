#!/usr/bin/env python3
"""Adds ONE product, by its product-page URL, to docs/my-coffees.json -- the
personal curated list loaded by the installed PWA (see manifest.json's
start_url and index.html's PERSONAL_MODE/COFFEE_DATA_PATH).

Deliberately separate from the main data/*.json + docs/coffees-data.json
pipeline: the weekly scrape bot never reads or writes this file, and adding
one coffee here never pulls in that roaster's full catalog. Re-running on
a URL already in the file updates that product in place rather than
duplicating it.

If the roaster is already in config/roasters.json (matched by domain), its
known platform is used for a structured fetch (Shopify's <url>.json,
WooCommerce's Store API by slug). Otherwise -- or for platforms with no
structured single-product endpoint here -- falls back to reading the page's
own meta tags and body text generically; the LLM extraction step still runs
either way; what's genuinely missing stays null rather than guessed.

Usage:
    python3 scripts/add_coffee.py <product-url> [<product-url> ...]
"""
import json
import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, ".")
from bs4 import BeautifulSoup  # noqa: E402

from scrapers.common.http import session, get, decode_json_body  # noqa: E402
from scrapers.common.schema import RawProduct, _new_product_dict, now_iso, slugify  # noqa: E402
from scripts.build_app_data import transform_product  # noqa: E402
from scrapers import prestashop  # noqa: E402

MY_COFFEES_PATH = "docs/my-coffees.json"
ROASTERS_CONFIG_PATH = "config/roasters.json"


def load_env_file(path=".env"):
    if not os.environ.get("ANTHROPIC_API_KEY") and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()


def load_roasters_config():
    with open(ROASTERS_CONFIG_PATH, encoding="utf-8") as f:
        return {r["domain"]: r for r in json.load(f) if r.get("domain")}


def find_roaster_by_domain(domain, by_domain):
    domain = domain.lower().removeprefix("www.")
    for d, r in by_domain.items():
        if d.lower().removeprefix("www.") == domain:
            return r
    return None


def fetch_shopify(s, url):
    resp = get(s, url.rstrip("/") + ".json")
    resp.raise_for_status()
    p = decode_json_body(resp)["product"]
    variants = p.get("variants") or [{}]
    cheapest = min(variants, key=lambda v: float(v.get("price") or "inf"))
    image_url = (p.get("images") or [{}])[0].get("src") if p.get("images") else None
    price = cheapest.get("price")
    return {
        "name": p["title"],
        "raw_description_html": p.get("body_html"),
        "image_url": image_url,
        "price": float(price) if price else None,
        "in_stock": bool(cheapest.get("available", True)),
    }


def fetch_woocommerce(s, url, domain):
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    resp = get(s, f"https://{domain}/wp-json/wc/store/v1/products", params={"slug": slug})
    resp.raise_for_status()
    results = decode_json_body(resp)
    if not results:
        raise ValueError(f"no WooCommerce product found for slug {slug!r}")
    p = results[0]
    price_data = p.get("prices", {})
    minor_unit = price_data.get("currency_minor_unit", 2)
    raw_price = price_data.get("price")
    price = float(raw_price) / (10 ** minor_unit) if raw_price else None
    image_url = (p.get("images") or [{}])[0].get("src") if p.get("images") else None
    return {
        "name": p["name"],
        "raw_description_html": p.get("short_description") or p.get("description"),
        "image_url": image_url,
        "price": price,
        "in_stock": p.get("is_in_stock", True),
    }


def fetch_prestashop(s, url):
    detail = prestashop.scrape_product_detail(s, url)
    generic = fetch_generic(s, url)  # name/image: PrestaShop's own detail scraper doesn't return these
    return {
        "name": generic["name"],
        "raw_description_html": detail.get("description_html") or generic["raw_description_html"],
        "image_url": generic["image_url"],
        "price": detail.get("price"),
        "in_stock": generic["in_stock"],
    }


def fetch_generic(s, url):
    resp = get(s, url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    def meta(prop):
        tag = soup.select_one(f'meta[property="{prop}"], meta[name="{prop}"]')
        return tag.get("content") if tag else None

    # h1 first: og:title/<title> are frequently SEO boilerplate ("Café de
    # spécialité | X | Vente en ligne") rather than the plain product name.
    h1 = soup.select_one("h1")
    name = (h1.get_text(strip=True) if h1 else None) or meta("og:title") or (soup.title.string.strip() if soup.title else None)
    image_url = meta("og:image")
    price_raw = meta("product:price:amount") or meta("og:price:amount")
    price = float(price_raw) if price_raw else None

    body = (
        soup.select_one('[itemprop="description"]')
        or soup.select_one(".product-description, .product__description, main, article")
        or soup.body
    )
    description_html = str(body) if body else resp.text

    return {
        "name": name or "Produit sans nom",
        "raw_description_html": description_html,
        "image_url": image_url,
        "price": price,
        "in_stock": True,
    }


def build_raw_product(slug, fetched, url, site_name):
    # Scraper-schema retailer shape (raw numeric price) -- transform_product()
    # (from build_app_data.py, reused below) is what turns this into the
    # display-formatted "14,90 €" / "Rupture de stock" string, same as the
    # main pipeline. Passing a pre-formatted string here would just get
    # re-formatted wrong.
    retailer = {
        "site": site_name,
        "url": url,
        "price": fetched["price"],
        "currency": "EUR",
        "inStock": fetched["in_stock"],
    }
    return RawProduct(
        slug=slug,
        name=fetched["name"],
        retailers=[retailer],
        raw_description_html=fetched["raw_description_html"],
        image_url=fetched["image_url"],
    )


def load_my_coffees():
    with open(MY_COFFEES_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_my_coffees(data):
    data["roasterCount"] = len(data["roasters"])
    data["coffeeCount"] = len(data["coffees"])
    data["generatedAt"] = now_iso()
    with open(MY_COFFEES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def add_one(url, roasters_by_domain, my_coffees, s):
    domain = urlparse(url).netloc
    config_entry = find_roaster_by_domain(domain, roasters_by_domain)
    platform = config_entry["platform"] if config_entry else None
    site_name = config_entry["name"] if config_entry else domain

    print(f"{url}")
    print(f"  plateforme: {platform or 'inconnue (site pas encore scrapé) -> lecture générique'}")

    if platform == "shopify":
        fetched = fetch_shopify(s, url)
    elif platform == "woocommerce":
        fetched = fetch_woocommerce(s, url, domain)
    elif platform == "prestashop":
        fetched = fetch_prestashop(s, url)
    else:
        fetched = fetch_generic(s, url)

    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or slugify(fetched["name"])
    roaster_id = config_entry["id"] if config_entry else slugify(domain.removeprefix("www."))

    raw = build_raw_product(slug, fetched, url, site_name)
    scraped = _new_product_dict(roaster_id, raw, now_iso())  # data/*.json shape
    product = transform_product(scraped, roaster_id)  # coffees-data.json shape (adds roasterId, formats price, etc.)

    if roaster_id not in my_coffees["roasters"]:
        my_coffees["roasters"][roaster_id] = {
            "name": site_name,
            "city": config_entry.get("city") if config_entry else None,
            "url": config_entry.get("url") if config_entry else f"https://{domain}/",
            "domain": domain,
            "logoUrl": config_entry.get("logoUrl") if config_entry else None,
        }

    existing_ids = [c["id"] for c in my_coffees["coffees"]]
    if product["id"] in existing_ids:
        my_coffees["coffees"][existing_ids.index(product["id"])] = product
        print(f"  -> mis à jour : {product['name']}")
    else:
        my_coffees["coffees"].append(product)
        print(f"  -> ajouté : {product['name']}")

    filled = [k for k in ("originCountry", "process", "variety", "producer", "score",
                          "roast", "flavors", "desc", "usage")
              if product.get(k)]
    print(f"  champs remplis : {', '.join(filled) if filled else '(aucun -- page pauvre en texte)'}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    load_env_file()
    roasters_by_domain = load_roasters_config()
    my_coffees = load_my_coffees()
    s = session()

    for url in sys.argv[1:]:
        try:
            add_one(url, roasters_by_domain, my_coffees, s)
        except Exception as exc:
            print(f"  ÉCHEC : {exc}", file=sys.stderr)

    save_my_coffees(my_coffees)
    print(f"\n{my_coffees['coffeeCount']} cafés dans {MY_COFFEES_PATH}")


if __name__ == "__main__":
    main()
