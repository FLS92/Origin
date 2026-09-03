"""Scraper for Wizishop (French e-commerce SaaS, identified by the
'WiziServer' response header). No public API, so this parses the
server-rendered category listing ('.prod__article' cards) and visits each
product page for the weight (Wizishop doesn't expose it on the listing)."""
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common.http import session, get
from .common.parsing import norm, parse_grams, parse_price_eur
from .common.schema import RawProduct, apply_products, save

COFFEE_SEGMENTS = {"cafe", "cafes", "nos-cafes", "coffee"}
EXCLUDE_SEGMENTS = {"cafetiere", "cafetieres", "accessoires-cafes", "decafeine", "cafe-aromatise"}


def find_coffee_category_url(soup, base_url):
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0].split("#")[0]
        segments = [s.lower() for s in href.strip("/").split("/") if s]
        if not segments:
            continue
        if segments[-1] in EXCLUDE_SEGMENTS:
            continue
        if any(seg in COFFEE_SEGMENTS for seg in segments):
            candidates.append((len(segments), urljoin(base_url, a["href"])))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


def parse_listing(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("article.prod__article"):
        link = card.select_one("a.prod__link")
        if not link:
            continue
        url = urljoin(base_url, link.get("href", ""))
        name_el = card.select_one(".prod__name__title")
        name = name_el.get_text(strip=True) if name_el else link.get("title", "").strip()
        img = card.select_one("img.prod__img")
        image_url = img.get("src") if img else None
        price_el = card.select_one(".prod__price__cur")
        price = parse_price_eur(price_el.get_text()) if price_el else None
        from_note = card.select_one(".prod__price__from")
        items.append({
            "name": name, "url": url, "image": image_url, "price": price,
            "priceNote": "à partir de" if from_note else None,
        })
    return items, soup


def find_next_page(soup, base_url):
    nxt = soup.select_one("a.pagination__next, a[rel=next]")
    if nxt and nxt.get("href"):
        return urljoin(base_url, nxt["href"])
    return None


def scrape_product_detail(s, url):
    resp = get(s, url)
    if resp.status_code != 200:
        return {}
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    desc_el = soup.select_one(".prod-detail__desc, [itemprop=description]")
    return {"weight_g": parse_grams(text), "description_html": str(desc_el) if desc_el else None}


def scrape(roaster_meta):
    domain = roaster_meta["domain"]
    base_url = f"https://www.{domain}/" if not domain.startswith("www.") else f"https://{domain}/"
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
            items, page_soup = parse_listing(resp.text, url)
            all_items.extend(items)
            nxt = find_next_page(page_soup, url)
            if not nxt or nxt == url:
                break
            url = nxt

    raw_products = []
    for item in all_items:
        if not item["name"] or not item["url"]:
            continue
        detail = scrape_product_detail(s, item["url"])
        retailer = {
            "site": roaster_meta["name"],
            "url": item["url"],
            "price": item["price"],
            "currency": "EUR",
            "unitWeightG": detail.get("weight_g"),
            "priceNote": item["priceNote"],
            "inStock": True,
            "stockStatus": "instock",
        }
        raw_products.append(RawProduct(
            slug=item["url"].rstrip("/").rsplit("/", 1)[-1].replace(".html", ""),
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
