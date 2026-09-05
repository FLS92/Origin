"""Scraper for PrestaShop stores. There is no public JSON catalog API without a
webservice key, so this parses server-rendered HTML: the category listing page's
'.product-miniature' cards for the product list, then each product page's
itemprop microdata + a weight-pattern regex for price/weight detail.

Category discovery is generic: it looks at the homepage nav for a link whose
text reads like a coffee category ("café", "cafés", "coffee"), since the URL
path/id for that category differs on every PrestaShop install.
"""
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common.http import session, get
from .common.parsing import norm, normalize_method, parse_grams, parse_price_eur
from .common.schema import RawProduct, apply_products, save

# A handful of PrestaShop shops (confirmed on Terres de Café) run a "Stape"
# theme module that echoes the full product record — including a proper
# "Notes de Dégustation" block in real HTML, richer than the plain
# itemprop=description this scraper otherwise falls back to — as a JS
# variable assignment. It's valid JSON once isolated, so read it as JSON
# rather than regexing the surrounding markup.
_STAPE_VAR_RE = re.compile(r"stape_product\s*=\s*(\{)")


_METHOD_WORDS = {"filtre", "expresso", "espresso", "omni", "methode", "methodes"}


def _bold_flavor_candidates(tasting_html):
    """Within the "Notes de Dégustation" block, this theme bolds the actual
    tasting words inline in prose ("des notes de <strong>cardamome</strong>,
    de <strong>pâte d'amande</strong>...") rather than listing them — but
    also bolds sub-heading labels ("<strong>Au nez :</strong>") and other
    asides ("torréfié pour la <strong>méthode expresso</strong>") the same
    way, so filter those out rather than trust every bold span."""
    soup = BeautifulSoup(tasting_html, "html.parser")
    items = []
    for tag in soup.find_all("strong"):
        raw = tag.get_text(" ", strip=True)
        if not raw or ":" in raw or len(raw) > 25:
            continue
        text = raw.strip(" '’")
        if any(w in norm(text) for w in _METHOD_WORDS):
            continue
        if len(text.split()) > 3:
            continue
        items.append(text)
    return items


def extract_stape_product(html):
    """Reads the "Stape" theme's echoed product-record JS variable (confirmed
    on Terres de Café) for a richer description than plain itemprop=
    description, plus tasting-note words the site bolds inline in that text.
    Returns {} if this shop doesn't run this module."""
    m = _STAPE_VAR_RE.search(html)
    if not m:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, m.start(1))
    except (ValueError, json.JSONDecodeError):
        return {}

    tasting_html = obj.get("bloc3_z3") or ""
    parts = [tasting_html, obj.get("description")]
    description_html = " ".join(p for p in parts if p) or None

    extracted = {}
    if tasting_html:
        flavors = _bold_flavor_candidates(tasting_html)
        if flavors:
            extracted["flavors"] = flavors

    return {"description_html": description_html, "extracted": extracted}


COFFEE_LINK_WORDS = {"cafe", "cafes", "coffee"}
EXCLUDE_LINK_WORDS = {"machine", "machines", "accessoire", "accessoires", "the", "thes", "entreprise", "entreprises"}

# PrestaShop's standard "data sheet" (fiche technique) block — a <dl> of
# dt.name/dd.value pairs configured per-shop as custom product "features".
# Label wording varies by site ("Origine" vs "Pays", "Producteur" vs "Nom de
# la ferme et producteur"), so this maps synonyms same as WooCommerce's
# custom attributes. Ambiguous/non-schema labels (Altitude, Prix,
# Conditionnement...) are deliberately left unmapped.
DATA_SHEET_SYNONYMS = {
    "variety": {"variete", "varietes", "variete botanique", "cultivar"},
    "process": {"process", "procede", "traitement"},
    "producer": {"producteur", "producteurs", "nom de la ferme et producteur", "ferme et producteur"},
    "originCountry": {"origine", "pays"},
    "originDetail": {"region ferme", "region"},
}


def extract_data_sheet(soup):
    out = {}
    sheet = soup.select_one("dl.data-sheet")
    if not sheet:
        return out
    names = sheet.select("dt.name")
    values = sheet.select("dd.value")
    for dt, dd in zip(names, values):
        label = norm(dt.get_text())
        value = dd.get_text(strip=True)
        if not value:
            continue
        if label == "gamme":
            m = re.search(r"\d+(?:[.,]\d+)?", value)
            if m:
                n = float(m.group(0).replace(",", "."))
                out.setdefault("score", int(n) if n.is_integer() else n)
            continue
        if label == "torrefaction":
            method = normalize_method(value)
            if method:
                out.setdefault("method", method)
            continue
        for field, synonyms in DATA_SHEET_SYNONYMS.items():
            if label in synonyms:
                out.setdefault(field, value)
                break
    return out


def find_coffee_category_url(soup, base_url):
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].split("#")[0]
        if href.strip("/") in ("", base_url.strip("/")):
            continue
        if "/content/" in href or "/cms/" in href:
            continue  # static CMS page, not a product category
        label = norm(a.get_text())
        if not label:
            continue
        words = label.split()
        is_coffee = any(w.startswith("cafe") or w == "coffee" for w in words)
        is_excluded = any(w in EXCLUDE_LINK_WORDS for w in words)
        if is_coffee and not is_excluded:
            candidates.append(urljoin(base_url, a["href"]))
    return candidates[0] if candidates else None


def parse_listing(html, base_url):
    """Handles both PrestaShop 1.7/8 ('.product-miniature') and 1.6
    ('.product-container') themes — different installs in the wild use
    either, with different class names throughout."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".product-miniature, article.product-miniature, .product-container")
    items = []
    for card in cards:
        pid = card.get("data-id-product")
        if not pid:
            id_el = card.select_one("[data-id-product]")
            pid = id_el.get("data-id-product") if id_el else None

        link = (
            card.select_one("h3.product-title a")
            or card.select_one(".product-title a")
            or card.select_one("a.product-name")
        )
        title_el = card.select_one("h2.product-title, h3.product-title, .product-title, [itemprop=name]")
        thumb = card.select_one("a.product-thumbnail, a.product_img_link")
        if not link and not thumb:
            continue
        href = (link or thumb).get("href", "")
        url = urljoin(base_url, href.split("#")[0])
        name = (
            (title_el.get_text(strip=True) if title_el else "")
            or (link.get_text(strip=True) if link else "")
            or (thumb.get("title", "").strip() if thumb else "")
        )
        img = card.select_one("img")
        image_url = None
        if img:
            image_url = img.get("data-full-size-image-url") or img.get("src")
        price_el = card.select_one(".product-price, .price")
        price = parse_price_eur(price_el.get_text()) if price_el else None
        desc_el = card.select_one("[itemprop=description], .product-desc")
        items.append({
            "id": pid, "name": name, "url": url, "image": image_url, "price": price,
            "listing_description_html": str(desc_el) if desc_el else None,
        })
    return items


def find_next_page(soup, base_url):
    nxt = soup.select_one("a.next, a[rel=next]")
    if nxt and nxt.get("href"):
        return urljoin(base_url, nxt["href"])
    return None


def scrape_product_detail(s, url):
    resp = get(s, url)
    if resp.status_code != 200:
        return {}
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    price_el = soup.select_one('[itemprop="price"]')
    price = None
    if price_el:
        price = parse_price_eur(price_el.get("content") or price_el.get_text())
    weight = parse_grams(text)
    desc_el = soup.select_one('[itemprop="description"], .product-description')

    stape = extract_stape_product(resp.text)
    description_html = stape.get("description_html") or (str(desc_el) if desc_el else None)

    extracted = extract_data_sheet(soup)
    for field, value in (stape.get("extracted") or {}).items():
        extracted.setdefault(field, value)

    return {
        "price": price, "weight_g": weight, "description_html": description_html,
        "extracted": extracted,
    }


def scrape(roaster_meta):
    domain = roaster_meta["domain"]
    base_url = f"https://{domain}/"
    s = session()
    resp = get(s, base_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    cat_url = find_coffee_category_url(soup, base_url)

    all_items = []
    if cat_url:
        url = cat_url
        for _ in range(20):
            resp = get(s, url)
            if resp.status_code != 200:
                break
            page_soup = BeautifulSoup(resp.text, "html.parser")
            all_items.extend(parse_listing(resp.text, url))
            nxt = find_next_page(page_soup, url)
            if not nxt or nxt == url:
                break
            url = nxt

    raw_products = []
    for item in all_items:
        if not item["id"] or not item["name"]:
            continue
        detail = scrape_product_detail(s, item["url"])
        price = detail.get("price") if detail.get("price") is not None else item["price"]
        retailer = {
            "site": roaster_meta["name"],
            "url": item["url"],
            "price": price,
            "currency": "EUR",
            "unitWeightG": detail.get("weight_g"),
            "priceNote": None,
            "inStock": True,
            "stockStatus": "instock",
        }
        raw_products.append(RawProduct(
            slug=f"p{item['id']}",
            name=item["name"],
            retailers=[retailer],
            raw_description_html=detail.get("description_html") or item.get("listing_description_html"),
            image_url=item["image"],
            extracted=detail.get("extracted"),
        ))

    data, summary = apply_products(roaster_meta, raw_products)
    save(roaster_meta["id"], data)
    if not cat_url:
        summary["warning"] = "no coffee category link found on homepage — 0 products scraped"
    return summary
