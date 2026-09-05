#!/usr/bin/env python3
"""Re-applies label_extract.extract_labeled_fields to every available
product using freshly re-fetched text (not just the ones with every field
still null, unlike harvest_raw_text.py + backfill_labeled_fields.py) — for
when label_extract.py's rules improve and existing products could benefit,
not just newly-scraped ones. Never overwrites a field that already has a
value.

Usage: python3 scripts/backfill_all.py [roaster_id ...]
"""
import json
import os
import sys

sys.path.insert(0, ".")
from scripts.harvest_raw_text import DISPATCH  # noqa: E402
from scrapers.common.label_extract import extract_labeled_fields  # noqa: E402

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
            print(f"{meta['name']}: skip ({exc})", file=sys.stderr)
            continue

        roaster_changed = False
        roaster_updated = 0
        for p in available:
            slug = p["id"][len(roaster_id) + 1:]
            text = text_by_slug.get(slug)
            if not text:
                continue
            fields = extract_labeled_fields(text)
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
