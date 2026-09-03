"""Scraper for PrestaShop stores. There is no public JSON catalog API without a
webservice key, so this parses server-rendered HTML: the category listing page's
'.product-miniature' cards for the product list, then each product page's
itemprop microdata + a weight-pattern regex for price/weight detail.

Category discovery is generic: it looks at the homepage nav for a link whose
text reads like a coffee category ("café", "cafés", "coffee"), since the URL
path/id for that category differs on every PrestaShop install.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common.http import session, get
from .common.parsing import norm, parse_grams, parse_price_eur
from .common.schema import RawProduct, apply_products, save

COFFEE_LINK_WORDS = {"cafe", "cafes", "coffee"}
EXCLUDE_LINK_WORDS = {"machine", "machines", "accessoire", "accessoires", "the", "thes", "entreprise", "entreprises"}


def find_coffee_category_url(soup, base_url):
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].split("#")[0]
        if href.strip("/") in ("", base_url.strip("/")):
            continue
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
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".product-miniature, article.product-miniature")
    items = []
    for card in cards:
        pid = card.get("data-id-product")
        link = card.select_one("h3.product-title a") or card.select_one(".product-title a")
        title_el = card.select_one("h2.product-title, h3.product-title, .product-title")
        thumb = card.select_one("a.product-thumbnail")
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
        price_el = card.select_one(".price")
        price = parse_price_eur(price_el.get_text()) if price_el else None
        items.append({"id": pid, "name": name, "url": url, "image": image_url, "price": price})
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
    description_html = str(desc_el) if desc_el else None
    return {"price": price, "weight_g": weight, "description_html": description_html}


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
            raw_description_html=detail.get("description_html"),
            image_url=item["image"],
        ))

    data, summary = apply_products(roaster_meta, raw_products)
    save(roaster_meta["id"], data)
    if not cat_url:
        summary["warning"] = "no coffee category link found on homepage — 0 products scraped"
    return summary
