#!/usr/bin/env python3
"""Re-applies title_extract.extract_from_title (always, from p["name"]) and
label_extract.extract_labeled_fields (when description text is available,
freshly re-fetched) to every available product — not just the ones with
every field still null, unlike harvest_raw_text.py + backfill_labeled_
fields.py — for when these rules improve and existing products could
benefit, not just newly-scraped ones. Never overwrites a field that
already has a value.

Usage: python3 scripts/backfill_all.py [roaster_id ...]
"""
import json
import os
import sys

sys.path.insert(0, ".")
from scripts.harvest_raw_text import DISPATCH  # noqa: E402
from scrapers.common.label_extract import extract_labeled_fields  # noqa: E402
from scrapers.common.title_extract import extract_from_title  # noqa: E402

SCHEMA_FIELDS = [
    "originCountry", "originDetail", "process", "variety", "producer",
    "score", "acidity", "body", "method", "roastLevel", "flavors",
]


def main():
    only_ids = set(sys.argv[1:]) or None
    with open("config/roasters.json", encoding="utf-8") as f:
        roasters = {r["id"]: r for r in json.load(f)}

    updated_products = updated_fields = 0

    for fname in sorted(os.listdir("data")):
        if not fname.endswith(".json"):
            continue
        roaster_id = fname[:-5]
        if only_ids and roaster_id not in only_ids:
            continue
        meta = roasters.get(roaster_id)
        if not meta or meta["platform"] not in DISPATCH:
            continue

        path = os.path.join("data", fname)
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        available = [p for p in d["products"] if p.get("available", True)]
        if not available:
            continue

        try:
            text_by_slug = DISPATCH[meta["platform"]](meta)
        except Exception as exc:
            # Title extraction below doesn't need this fetch at all -- don't
            # skip the whole roaster over it, just proceed with no
            # description text (label_extract simply won't run for it).
            print(f"{meta['name']}: description re-fetch failed ({exc}), title-only", file=sys.stderr)
            text_by_slug = {}

        roaster_changed = False
        roaster_updated = 0
        for p in available:
            slug = p["id"][len(roaster_id) + 1:]
            text = text_by_slug.get(slug)
            fields = extract_from_title(p["name"])
            if text:
                labeled = extract_labeled_fields(text)
                for k, v in labeled.items():
                    fields.setdefault(k, v)
            product_changed = False
            for field, value in fields.items():
                if p.get(field) is None and value is not None:
                    p[field] = value
                    product_changed = True
                    updated_fields += 1
            if product_changed:
                roaster_changed = True
                roaster_updated += 1

        if roaster_changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            updated_products += roaster_updated
        print(f"{meta['name']}: {roaster_updated} produits mis à jour")

    print(f"\n{updated_products} produits mis à jour ({updated_fields} champs remplis)")


if __name__ == "__main__":
    main()
