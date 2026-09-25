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


def find_roaster_by_name(name, roasters_by_domain, my_coffees):
    """For marketplaces (kofio.co) that sell many roasters' coffee: the
    product's real roaster is named on the page, not the marketplace
    domain. Reuse the existing roaster entry (by name, case-insensitive)
    from either the main config or this file's own roasters if one
    already exists, so e.g. a Tanat Coffee bag bought via kofio still
    lands under the same roaster_id as Tanat's own scraped catalog."""
    name_norm = name.strip().lower()
    for r in roasters_by_domain.values():
        if r["name"].strip().lower() == name_norm:
            return r["id"], r
    for rid, r in my_coffees["roasters"].items():
        if r["name"].strip().lower() == name_norm:
            return rid, None
    return slugify(name), None


_KOFIO_ROAST_TYPE_TO_METHOD = {"filter": "Filtre", "espresso": "Espresso", "omni": "Omni"}


def fetch_kofio(s, url):
    """kofio.co is a Czech marketplace reselling many roasters' coffee, not
    a roaster's own shop -- see find_roaster_by_name for how the real
    roaster (read off this page, not the kofio.co domain) gets attributed.
    Its product pages carry a clean schema.org JSON-LD block plus a
    "Product Specs" table (real Label/Value pairs, not free-text prose),
    both far more reliable than the generic fallback -- worth a dedicated
    parser rather than leaving this only to title/label/LLM guessing."""
    resp = get(s, url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    ld_tag = soup.find("script", type="application/ld+json")
    ld = json.loads(ld_tag.string) if ld_tag and ld_tag.string else {}
    offers = ld.get("offers", {})

    specs = {}
    for row in soup.select("table.table-hover tr.product_parameter_item"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        value_cell = cells[1]
        title_div = value_cell.select_one(".xs_product_parameter_item_title")
        if title_div:
            title_div.extract()
        # Multi-value cells (Variety, Flavour Profile, ...) are a run of
        # <a> tags with literal ", " text nodes already between them in the
        # markup -- get_text(", ") would add a SECOND separator on top of
        # those and produce "Caturra, ,, Colombia". Read the links' own
        # text directly instead; cells with no links (Roast Date, Cupping
        # Score) have none, so this falls back to the plain cell text.
        links = value_cell.find_all("a")
        specs[label] = ", ".join(a.get_text(strip=True) for a in links) if links else value_cell.get_text(strip=True)

    method = _KOFIO_ROAST_TYPE_TO_METHOD.get((specs.get("Roast Type") or "").strip().lower())
    score = None
    score_raw = (specs.get("Cupping Score") or "").split("/")[0].strip().replace(",", ".")
    if score_raw:
        try:
            score = float(score_raw)
        except ValueError:
            pass

    extracted = {}
    if specs.get("Coffee Origin"): extracted["originCountry"] = specs["Coffee Origin"]
    if specs.get("Region"): extracted["originDetail"] = specs["Region"]
    if specs.get("Variety"): extracted["variety"] = specs["Variety"]
    if specs.get("Process"): extracted["process"] = specs["Process"]
    if method: extracted["method"] = method
    if specs.get("Roast Level"): extracted["roastLevel"] = specs["Roast Level"]
    if specs.get("Flavour Profile"):
        extracted["flavors"] = [f.strip() for f in specs["Flavour Profile"].split(",") if f.strip()]
    if score is not None: extracted["score"] = score

    desc_div = soup.select_one(".product_description_body")
    # JSON-LD's own price/availability are unreliable here -- a sold-out
    # product still says "InStock" with price "0" there (confirmed on a
    # genuinely sold-out listing). The visible availability badge and a
    # non-zero price are what the page actually shows the shopper.
    price_raw = offers.get("price")
    price = float(price_raw) if price_raw else None
    if not price:
        price = None
    availability_text = soup.select_one(".product_availability")
    in_stock = "sold out" not in (availability_text.get_text(strip=True).lower() if availability_text else "")

    # kofio.co bakes the roastery's name into the product title itself
    # ("Kaffa Colombia INDIAN SUMMER") -- redundant once that roastery is
    # also the card's own roaster label, so strip it back off.
    name = ld.get("name") or specs.get("name") or ""
    roastery_name = specs.get("Roastery")
    if roastery_name and name.lower().startswith(roastery_name.lower()):
        name = name[len(roastery_name):].strip(" -–—")

    return {
        "name": name,
        "raw_description_html": str(desc_div) if desc_div else None,
        "image_url": ld.get("image"),
        "price": price,
        "currency": offers.get("priceCurrency", "EUR"),
        "in_stock": in_stock,
        "extracted": extracted,
        "roastery_name": specs.get("Roastery"),
    }


def fetch_every_coffee(s, url, roasters_by_domain):
    """every.coffee is another aggregator (like kofio.co) reselling many
    roasters' coffee, but its schema.org Product node's AggregateOffer
    carries a `url` straight back to the roaster's own product page. That
    page is almost always richer than every.coffee's own generic
    description ("X coffee from Y."), so when the target is a domain we
    already know how to fetch structurally (Shopify/WooCommerce/
    PrestaShop), redirect there entirely rather than settling for the
    thin aggregator copy. Falls back to every.coffee's own data (still
    attributed to the real roaster by name) if there's no usable
    redirect, or if fetching it fails for any reason."""
    resp = get(s, url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    product = None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string)
        except (TypeError, ValueError):
            continue
        for node in data.get("@graph", [data]):
            if node.get("@type") == "Product":
                product = node
        if product:
            break
    if not product:
        raise ValueError("no Product JSON-LD found on every.coffee page")

    offers = product.get("offers", {})
    roastery_name = (product.get("brand") or {}).get("name")
    redirect_url = offers.get("url")
    redirect_domain = urlparse(redirect_url).netloc.lower().removeprefix("www.") if redirect_url else None

    if redirect_domain and redirect_domain != "every.coffee":
        target_roaster = find_roaster_by_domain(redirect_domain, roasters_by_domain)
        platform = target_roaster["platform"] if target_roaster else None
        try:
            if platform == "shopify":
                fetched = fetch_shopify(s, redirect_url)
            elif platform == "woocommerce":
                fetched = fetch_woocommerce(s, redirect_url, redirect_domain)
            elif platform == "prestashop":
                fetched = fetch_prestashop(s, redirect_url)
            else:
                fetched = fetch_generic(s, redirect_url)
            fetched["roastery_name"] = roastery_name
            fetched["resolved_url"] = redirect_url
            return fetched
        except Exception:
            pass  # fall through to every.coffee's own (thinner) data below

    price_raw = offers.get("lowPrice")
    return {
        "name": product.get("name") or "",
        "raw_description_html": product.get("description"),
        "image_url": product.get("image"),
        "price": float(price_raw) if price_raw else None,
        "currency": offers.get("priceCurrency", "EUR"),
        "in_stock": "instock" in (offers.get("availability") or "").lower(),
        "roastery_name": roastery_name,
    }


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
    # The Store API's `slug` param isn't a strict filter on every store --
    # a slug that no longer exists (product renamed/removed) can come back
    # with an unfiltered page of unrelated products instead of an empty
    # list (confirmed on a stale every.coffee redirect: a coffee's dead
    # slug returned a completely unrelated brewer product as results[0]).
    # Only trust an exact slug match.
    match = next((p for p in results if p.get("slug") == slug), None)
    if not match:
        raise ValueError(f"no WooCommerce product found for slug {slug!r}")
    p = match
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
    # Some themes (seen on a French Shopify store) put a comma-decimal
    # price in this meta tag ("14,00") despite the tag being meant for a
    # plain float -- float() rejects that outright.
    price = float(price_raw.replace(",", ".")) if price_raw else None

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
        "currency": fetched.get("currency", "EUR"),
        "inStock": fetched["in_stock"],
    }
    return RawProduct(
        slug=slug,
        name=fetched["name"],
        retailers=[retailer],
        raw_description_html=fetched["raw_description_html"],
        image_url=fetched["image_url"],
        extracted=fetched.get("extracted"),
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


MARKETPLACE_DOMAINS = {"kofio.co", "every.coffee"}


def add_one(url, roasters_by_domain, my_coffees, s):
    # Strip tracking query strings (e.g. Google's ?srsltid=...) -- harmless
    # for URLs that don't have any, but left in place they'd get appended
    # BEFORE the ".json" fetch_shopify adds, breaking that request entirely.
    url = urlparse(url)._replace(query="", fragment="").geturl()

    domain = urlparse(url).netloc
    is_marketplace = domain.lower().removeprefix("www.") in MARKETPLACE_DOMAINS
    config_entry = None if is_marketplace else find_roaster_by_domain(domain, roasters_by_domain)
    if config_entry:
        platform = config_entry["platform"]
    elif domain.lower().removeprefix("www.") == "every.coffee":
        platform = "every_coffee"
    elif is_marketplace:
        platform = "kofio"
    else:
        platform = None
    site_name = config_entry["name"] if config_entry else domain

    print(f"{url}")
    print(f"  plateforme: {platform or 'inconnue (site pas encore scrapé) -> lecture générique'}")

    if platform == "shopify":
        fetched = fetch_shopify(s, url)
    elif platform == "woocommerce":
        fetched = fetch_woocommerce(s, url, domain)
    elif platform == "prestashop":
        fetched = fetch_prestashop(s, url)
    elif platform == "kofio":
        fetched = fetch_kofio(s, url)
    elif platform == "every_coffee":
        fetched = fetch_every_coffee(s, url, roasters_by_domain)
        if fetched.get("resolved_url"):
            # Redirected to the roaster's own product page -- use that as
            # the retailer link and slug source from here on, not the
            # every.coffee aggregator page.
            url = fetched["resolved_url"]
            print(f"  every.coffee -> redirection vers la fiche du torréfacteur : {url}")
    else:
        # Unknown platform: plenty of roasters run Shopify or WooCommerce
        # without being in config/roasters.json yet, and either's
        # structured endpoint gives far better data (real variants/stock,
        # no meta-tag price parsing that a page might not even carry --
        # confirmed missing entirely on a WooCommerce store that has no
        # product:price:amount/og:price:amount meta tag) than the generic
        # fallback -- worth trying both before settling for it.
        try:
            fetched = fetch_shopify(s, url)
        except Exception:
            try:
                fetched = fetch_woocommerce(s, url, domain)
            except Exception:
                fetched = fetch_generic(s, url)

    # Marketplaces resell many roasters' coffee -- the real roaster is named
    # on the page itself (fetched["roastery_name"]), never the marketplace's
    # own domain. Reuse an existing roaster entry by name when there is one
    # (e.g. a roaster already in the main scraped catalog) instead of always
    # minting a fresh id.
    roastery_name = fetched.get("roastery_name") if is_marketplace else None
    if roastery_name:
        roaster_id, matched_config_entry = find_roaster_by_name(roastery_name, roasters_by_domain, my_coffees)
        if matched_config_entry:
            config_entry = matched_config_entry
        site_name = roastery_name
        print(f"  torréfacteur (lu sur la page) : {roastery_name} -> roaster_id={roaster_id}")
    else:
        # A roaster first met through a marketplace listing (kofio.co,
        # every.coffee) has no domain on file, so a later direct add from
        # their own site would otherwise mint a second, differently-slugged
        # roaster for the same real torréfacteur. Reuse the existing entry
        # when one already carries this domain.
        domain_norm = domain.lower().removeprefix("www.")
        existing_by_domain = next(
            (rid for rid, r in my_coffees["roasters"].items()
             if (r.get("domain") or "").lower().removeprefix("www.") == domain_norm),
            None,
        )
        roaster_id = config_entry["id"] if config_entry else (existing_by_domain or slugify(domain.removeprefix("www.")))

    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or slugify(fetched["name"])

    raw = build_raw_product(slug, fetched, url, site_name)
    scraped = _new_product_dict(roaster_id, raw, now_iso())  # data/*.json shape
    product = transform_product(scraped, roaster_id)  # coffees-data.json shape (adds roasterId, formats price, etc.)

    if roaster_id not in my_coffees["roasters"]:
        my_coffees["roasters"][roaster_id] = {
            "name": site_name,
            "city": config_entry.get("city") if config_entry else None,
            "url": config_entry.get("url") if config_entry else (None if is_marketplace else f"https://{domain}/"),
            "domain": config_entry.get("domain") if config_entry else (None if is_marketplace else domain),
            "logoUrl": config_entry.get("logoUrl") if config_entry else None,
        }

    existing_ids = [c["id"] for c in my_coffees["coffees"]]
    if product["id"] in existing_ids:
        # Merge rather than replace: re-running without ANTHROPIC_API_KEY
        # (see load_env_file) still refreshes price/stock and whatever the
        # free platform-native + label extraction finds, but must not wipe
        # out a field (desc, above all -- LLM-only, no free equivalent)
        # that an earlier run with the key already filled in.
        existing = my_coffees["coffees"][existing_ids.index(product["id"])]
        for k, v in product.items():
            if v not in (None, "", []) or k not in existing:
                existing[k] = v
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
