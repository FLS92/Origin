#!/usr/bin/env python3
"""Finds "Label :" / "Label /" boundaries in product description text that
label_extract.py's _LABEL_RE already detects (so they're already safe --
they can't corrupt a neighboring field) but that FIELD_LABELS doesn't map to
a schema field, meaning that label's value is currently just discarded. The
same manual check that found "Région", "Extraction recommandée", etc. after
a user reported a specific missing field, but run automatically across
every roaster's full raw text instead of waiting for someone to spot the
next one by hand.

This is the answer to "I can't manually check every roaster once there are
hundreds": re-run this periodically (after adding roasters, or on a
schedule) and treat its output as a to-do list for label_extract.py's
FIELD_LABELS — a frequent unmapped label is worth adding there.

Unlike harvest_raw_text.py (which only pulls products still missing every
field, for the one-time backfill), this pulls raw text for ALL available
products, since a product with some fields filled can still be missing
others behind an unmapped label.

Usage: python3 scripts/audit_labels.py [roaster_id ...]
"""
import collections
import json
import sys

sys.path.insert(0, ".")
from scripts.harvest_raw_text import DISPATCH  # noqa: E402
from scrapers.common.label_extract import _LABEL_RE, _LABEL_TO_FIELD, _norm  # noqa: E402

_CANDIDATE_LABEL_RE = _LABEL_RE
KNOWN = set(_LABEL_TO_FIELD.keys())


def main():
    only_ids = set(sys.argv[1:]) or None
    with open("config/roasters.json", encoding="utf-8") as f:
        roasters = {r["id"]: r for r in json.load(f)}

    unknown_counter = collections.Counter()
    unknown_examples = {}
    unknown_by_roaster = collections.defaultdict(collections.Counter)

    for fname in sorted(__import__("os").listdir("data")):
        if not fname.endswith(".json"):
            continue
        roaster_id = fname[:-5]
        if only_ids and roaster_id not in only_ids:
            continue
        meta = roasters.get(roaster_id)
        if not meta or meta["platform"] not in DISPATCH:
            continue

        with open(f"data/{fname}", encoding="utf-8") as f:
            d = json.load(f)
        if not any(p.get("available", True) for p in d["products"]):
            continue

        try:
            text_by_slug = DISPATCH[meta["platform"]](meta)
        except Exception as exc:
            print(f"{meta['name']}: skip ({exc})", file=sys.stderr)
            continue

        for text in text_by_slug.values():
            if not text:
                continue
            for m in _CANDIDATE_LABEL_RE.finditer(text):
                label = m.group(1).strip()
                if _norm(label) in KNOWN:
                    continue
                unknown_counter[label] += 1
                unknown_by_roaster[label][meta["name"]] += 1
                unknown_examples.setdefault(label, text[m.start():m.start() + 100])

        print(f"{meta['name']}: scanned {len(text_by_slug)} produits")

    print("\n" + "=" * 70)
    print("LABELS NON RECONNUS (fréquence >= 2), à évaluer pour label_extract.py")
    print("=" * 70)
    for label, count in unknown_counter.most_common(60):
        if count < 2:
            continue
        roasters_str = ", ".join(f"{r}×{c}" for r, c in unknown_by_roaster[label].most_common(3))
        print(f"{count:4d}  {label!r:30s} ({roasters_str})")
        print(f"       ex: {unknown_examples[label]!r}")


if __name__ == "__main__":
    main()
