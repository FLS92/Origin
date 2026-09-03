"""Load/merge/save a roaster's JSON file per schema-scraping-origin.md.

Merge is non-destructive: a product missing from the latest scrape is kept and
flipped to available=false, never deleted. IDs are '<roaster_id>-<platform_slug>'
and are stable as long as the source platform's own slug/handle/reference for that
product doesn't change — that's the one assumption this makes to avoid tracking a
separate internal identity, since the schema's product object has no field for it.
"""
import json
import os
import re
import unicodedata
from datetime import datetime, timezone

from .paraphrase import paraphrase

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text):
    n = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-zA-Z0-9]+", "-", n).strip("-").lower()
    return n or "produit"


def load(roaster_id):
    path = os.path.join(DATA_DIR, f"{roaster_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(roaster_id, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{roaster_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


class RawProduct:
    """What a platform scraper produces for one product, before merge."""

    def __init__(self, slug, name, retailers, raw_description_html=None,
                 image_url=None, unit_weight_g=None):
        self.slug = slug
        self.name = name
        self.retailers = retailers  # list of dicts matching the schema's retailer shape
        self.raw_description_html = raw_description_html
        self.image_url = image_url


def _new_product_dict(roaster_id, raw, ts):
    pid = f"{roaster_id}-{raw.slug}"
    description = paraphrase(raw.name, raw.raw_description_html)
    return {
        "id": pid,
        "name": raw.name,
        "originCountry": None,
        "originDetail": None,
        "process": None,
        "variety": None,
        "producer": None,
        "score": None,
        "acidity": None,
        "body": None,
        "method": None,
        "roastLevel": None,
        "flavors": None,
        "description": description,
        "imageUrl": raw.image_url,
        "harvestYear": None,
        "retailers": raw.retailers,
        "available": True,
        "firstSeenAt": ts,
        "lastSeenAt": ts,
    }


def apply_products(roaster_meta, raw_products):
    """roaster_meta: dict with id/name/city/country/url/domain.
    raw_products: list of RawProduct.
    Returns (data_dict, summary_dict) — caller decides whether/how to save.
    """
    roaster_id = roaster_meta["id"]
    ts = now_iso()
    existing = load(roaster_id)
    if existing is None:
        existing = {"roaster": roaster_meta, "scrapedAt": ts, "products": []}
    else:
        existing["roaster"] = roaster_meta

    by_id = {p["id"]: p for p in existing["products"]}
    seen = set()
    new_n = updated_n = unchanged_n = 0

    for raw in raw_products:
        pid = f"{roaster_id}-{raw.slug}"
        seen.add(pid)
        if pid in by_id:
            p = by_id[pid]
            changed = (
                p["name"] != raw.name
                or p["retailers"] != raw.retailers
                or p["imageUrl"] != raw.image_url
                or not p["available"]
            )
            p["name"] = raw.name
            p["retailers"] = raw.retailers
            p["imageUrl"] = raw.image_url
            p["available"] = True
            p["lastSeenAt"] = ts
            if changed:
                updated_n += 1
            else:
                unchanged_n += 1
        else:
            by_id[pid] = _new_product_dict(roaster_id, raw, ts)
            new_n += 1

    newly_unavailable = 0
    for pid, p in by_id.items():
        if pid not in seen and p["available"]:
            p["available"] = False
            newly_unavailable += 1

    existing["scrapedAt"] = ts
    existing["products"] = list(by_id.values())

    summary = {
        "roaster": roaster_meta["name"],
        "new": new_n,
        "updated": updated_n,
        "unchanged": unchanged_n,
        "newly_unavailable": newly_unavailable,
        "total_products": len(by_id),
    }
    return existing, summary
