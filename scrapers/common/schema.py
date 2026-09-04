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

from .coffee_filter import excluded_reason
from .label_extract import extract_labeled_fields
from .paraphrase import analyze_product, strip_html

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
    """What a platform scraper produces for one product, before merge.

    `extracted` carries fields the platform itself gave us with confidence
    (e.g. a WooCommerce "Producteur" attribute, Magento's hover-panel) — see
    the per-schema-field mapping in _new_product_dict. Anything extracted
    is trusted over anything the LLM later infers from free-text prose.
    """

    def __init__(self, slug, name, retailers, raw_description_html=None,
                 image_url=None, unit_weight_g=None, extracted=None):
        self.slug = slug
        self.name = name
        self.retailers = retailers  # list of dicts matching the schema's retailer shape
        self.raw_description_html = raw_description_html
        self.image_url = image_url
        self.extracted = extracted or {}


SCHEMA_FIELDS = [
    "originCountry", "originDetail", "process", "variety", "producer",
    "score", "acidity", "body", "method", "roastLevel", "flavors",
    "harvestYear",
]


def _new_product_dict(roaster_id, raw, ts):
    pid = f"{roaster_id}-{raw.slug}"
    labeled = extract_labeled_fields(strip_html(raw.raw_description_html))
    analysis = analyze_product(raw.name, raw.raw_description_html)

    # Precedence: the platform's own structured data first (a WooCommerce
    # attribute, Magento's hover-panel), then the deterministic "Label :
    # Value" reader (free, runs with no API key), then the LLM extraction
    # (needs ANTHROPIC_API_KEY) fills whatever's still missing.
    fields = {f: None for f in SCHEMA_FIELDS}
    for f in SCHEMA_FIELDS:
        if raw.extracted.get(f) is not None:
            fields[f] = raw.extracted[f]
        elif labeled.get(f) is not None:
            fields[f] = labeled[f]
        elif analysis.get(f) is not None:
            fields[f] = analysis[f]

    return {
        "id": pid,
        "name": raw.name,
        **fields,
        "description": analysis.get("description"),
        "imageUrl": raw.image_url,
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

    total_seen = len(raw_products)
    excluded_reasons = {}
    kept = []
    for raw in raw_products:
        reason = excluded_reason(raw.name)
        if reason:
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
        else:
            kept.append(raw)
    raw_products = kept
    excluded_n = total_seen - len(raw_products)

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

            # Backfill only — never overwrite a field that already has a
            # value. Without this, a scraper improvement (a new attribute
            # mapping, a fixed selector) would only ever benefit products
            # first seen after the fix; every existing one stays stuck with
            # whatever was extracted the day it was first scraped.
            labeled = extract_labeled_fields(strip_html(raw.raw_description_html))
            for f in SCHEMA_FIELDS:
                if p.get(f) is not None:
                    continue
                if raw.extracted.get(f) is not None:
                    p[f] = raw.extracted[f]
                    changed = True
                elif labeled.get(f) is not None:
                    p[f] = labeled[f]
                    changed = True

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
        "excluded": excluded_n,
    }
    # A handful of gift cards/workshops slipping through is normal; a large
    # share of the catalog being excluded means the platform's own category
    # filter probably isn't matching this site at all, and everything is
    # falling through to the keyword net instead — worth a human look.
    if total_seen >= 5 and excluded_n / total_seen > 0.3:
        top_reason = max(excluded_reasons, key=excluded_reasons.get)
        summary["warning"] = (
            f"{excluded_n}/{total_seen} produits exclus par mot-clé (ex: \"{top_reason}\" "
            f"x{excluded_reasons[top_reason]}) — le filtre catégorie de la plateforme ne "
            f"semble pas fonctionner pour ce site, à vérifier"
        )
    return existing, summary
