#!/usr/bin/env python3
"""One-time backfill: apply label_extract.extract_labeled_fields to existing
products in data/*.json using the raw text harvested by harvest_raw_text.py
(scratch/raw_text_dump.jsonl), filling only fields that are still null. Never
overwrites a field that already has a value from platform-native extraction.

Run harvest_raw_text.py first. Then: python3 scripts/backfill_labeled_fields.py
"""
import json
import os
import sys

sys.path.insert(0, ".")
from scrapers.common.label_extract import extract_labeled_fields  # noqa: E402

DUMP_PATH = "scratch/raw_text_dump.jsonl"
SCHEMA_FIELDS = [
    "originCountry", "originDetail", "process", "variety", "producer",
    "score", "acidity", "body", "method", "roastLevel", "flavors",
]


def main():
    text_by_id = {}
    with open(DUMP_PATH, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            text_by_id[d["id"]] = d["text"]

    updated_products = 0
    updated_fields = 0
    touched_roasters = set()

    for fname in sorted(os.listdir("data")):
        if not fname.endswith(".json"):
            continue
        path = os.path.join("data", fname)
        with open(path, encoding="utf-8") as f:
            d = json.load(f)

        changed = False
        for p in d["products"]:
            text = text_by_id.get(p["id"])
            if not text:
                continue
            fields = extract_labeled_fields(text)
            if not fields:
                continue
            product_changed = False
            for k, v in fields.items():
                if p.get(k) is None:
                    p[k] = v
                    updated_fields += 1
                    product_changed = True
            if product_changed:
                updated_products += 1
                changed = True

        if changed:
            touched_roasters.add(fname[:-5])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)

    print(f"{updated_products} produits mis à jour ({updated_fields} champs remplis) "
          f"sur {len(touched_roasters)} torréfacteurs")


if __name__ == "__main__":
    main()
