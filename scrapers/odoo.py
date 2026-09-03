"""Scraper for Odoo's website_sale e-commerce module. No public JSON API on the
storefront, so this parses the '/shop' listing pages (paginated via '?page=N'),
reading each '.oe_product' card's name/url/price/image directly from the
server-rendered HTML.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common.http import session, get
from .common.parsing import parse_grams
from .common.schema import RawProduct, apply_products, save

ID_SUFFIX_RE = re.compile(r"-(\d+)/?$")


def parse_listing(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".oe_product")
    items = []
    for card in cards:
        link = card.select_one("h2 a, .o_wsale_products_item_title a")
        if not link:
            continue
        href = link.get("href", "")
        url = urljoin(base_url, href)
        m = ID_SUFFIX_RE.search(href)
        pid = m.group(1) if m else None
        name = link.get_text(strip=True)
        img = card.select_one("img")
        image_url = urljoin(base_url, img["src"]) if img and img.get("src") else None
        price_el = card.select_one(".oe_currency_value")
        price = None
        if price_el:
            try:
                price = float(price_el.get_text(strip=True).replace(",", "."))
            except ValueError:
                pass
        items.append({"id": pid, "name": name, "url": url, "image": image_url, "price": price})
    return items, soup


def has_next_page(soup, current_page, base_url):
    for a in soup.select("a.page-link, .pagination a"):
        href = a.get("href", "")
        if f"page={current_page + 1}" in href:
            return urljoin(base_url, href)
    return None


def scrape_product_weight(s, url):
    resp = get(s, url)
    if resp.status_code != 200:
        return None, None
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    weight = parse_grams(text)
    desc_el = soup.select_one("#product_details, .product_page_description, [itemprop=description]")
    return weight, (str(desc_el) if desc_el else None)


def scrape(roaster_meta):
    domain = roaster_meta["domain"]
    base_url = f"https://{domain}/shop"
    s = session()
    all_items = []
    page = 1
    url = base_url
    while page <= 20:
        resp = get(s, url)
        if resp.status_code != 200:
            break
        items, soup = parse_listing(resp.text, url)
        all_items.extend(items)
        nxt = has_next_page(soup, page, f"https://{domain}")
        if not nxt:
            break
        url = nxt
        page += 1

    raw_products = []
    for item in all_items:
        if not item["id"] or not item["name"]:
            continue
        weight, description_html = scrape_product_weight(s, item["url"])
        retailer = {
            "site": roaster_meta["name"],
            "url": item["url"],
            "price": item["price"],
            "currency": "EUR",
            "unitWeightG": weight,
            "priceNote": None,
            "inStock": True,
            "stockStatus": "instock",
        }
        raw_products.append(RawProduct(
            slug=f"p{item['id']}",
            name=item["name"],
            retailers=[retailer],
            raw_description_html=description_html,
            image_url=item["image"],
        ))

    data, summary = apply_products(roaster_meta, raw_products)
    save(roaster_meta["id"], data)
    return summary
