"""Scraper for Magento stores. Written for cime-cafe.fr specifically (the only
Magento site in this batch) rather than as a fully generic platform scraper —
its theme happens to expose rich structured data (country/variety/producer/
flavor notes) in a '.hover-item' panel per product card, which is worth
reading directly instead of falling back to null for everything.
"""
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common.http import session, get
from .common.parsing import norm, parse_grams
from .common.schema import RawProduct, apply_products, save

HOVER_FIELD_MAP = {
    "pays": "originCountry",
    "variete": "variety",
    "plantation": "producer",
    "producteur": "producer",
    "process": "process",
    "notes aromatiques": "flavors",
}


def parse_listing(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("li.product-item, div.product-item"):
        link = card.select_one("a.product-item-link")
        if not link:
            continue
        url = urljoin(base_url, link.get("href", ""))
        name = link.get_text(strip=True)
        img = card.select_one("img.product-image-photo")
        image_url = img.get("src") if img else None

        price_box = card.select_one(".price-box[data-product-id]")
        product_id = price_box.get("data-product-id") if price_box else None
        amount_el = card.select_one("[data-price-amount]")
        price = float(amount_el["data-price-amount"]) if amount_el and amount_el.get("data-price-amount") else None

        weight_el = card.select_one(".product-weight")
        weight_g = parse_grams(weight_el.get_text()) if weight_el else None

        extracted = {}
        for hover in card.select(".hover-item"):
            title_el = hover.select_one(".hover-item-title")
            text_el = hover.select_one(".hover-item-text")
            if not title_el or not text_el:
                continue
            field = HOVER_FIELD_MAP.get(norm(title_el.get_text()))
            if field:
                value = text_el.get_text(strip=True)
                extracted[field] = [v.strip() for v in value.split(",")] if field == "flavors" else value

        items.append({
            "id": product_id, "name": name, "url": url, "image": image_url,
            "price": price, "weight_g": weight_g, "extracted": extracted,
        })
    return items, soup


def find_next_page(soup, base_url):
    nxt = soup.select_one("a.action.next")
    if nxt and nxt.get("href"):
        return urljoin(base_url, nxt["href"])
    return None


def scrape(roaster_meta):
    domain = roaster_meta["domain"]
    start_url = roaster_meta["url"]
    s = session()
    all_items = []
    url = start_url
    for _ in range(20):
        resp = get(s, url)
        if resp.status_code != 200:
            break
        items, soup = parse_listing(resp.text, url)
        all_items.extend(items)
        nxt = find_next_page(soup, url)
        if not nxt or nxt == url:
            break
        url = nxt

    raw_products = []
    for item in all_items:
        if not item["id"] or not item["name"]:
            continue
        retailer = {
            "site": roaster_meta["name"],
            "url": item["url"],
            "price": item["price"],
            "currency": "EUR",
            "unitWeightG": item["weight_g"],
            "priceNote": None,
            "inStock": True,
            "stockStatus": "instock",
        }
        raw_products.append(RawProduct(
            slug=f"p{item['id']}",
            name=item["name"],
            retailers=[retailer],
            raw_description_html=None,
            image_url=item["image"],
            extracted=item["extracted"],
        ))

    data, summary = apply_products(roaster_meta, raw_products)
    save(roaster_meta["id"], data)
    return summary
